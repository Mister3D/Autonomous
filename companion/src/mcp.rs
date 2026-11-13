//! Minimal MCP stdio client. Messages are one JSON object per line.
//! A Content-Length frame is still accepted, for servers that speak that older form.

use crate::config::{expand_env, split_args, McpServer};
use serde_json::{json, Value};
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, Command};

const MAX_TEXT: usize = 16_000;
const MAX_IMAGES: usize = 4;
/// Base64 chars. About 3.7 MB decoded, under the tunnel frame limit.
const MAX_IMAGE_B64: usize = 5_000_000;
/// JSON of text + images. Leaves room under `proto::MAX_PAYLOAD`.
const MAX_RESULT: usize = 6 * 1024 * 1024;

pub struct McpImage {
    pub mime: String,
    pub data: String,
}

pub struct McpReply {
    pub text: String,
    pub images: Vec<McpImage>,
}

/// Text blocks stay text. Image blocks (and embedded image resources) are kept
/// so a screenshot can be shown in the chat. Other blocks are ignored.
pub fn reply_from_result(result: &Value) -> McpReply {
    let mut text = String::new();
    let mut images: Vec<McpImage> = Vec::new();
    if let Some(parts) = result.get("content").and_then(|v| v.as_array()) {
        for part in parts {
            if part.get("type").and_then(|v| v.as_str()) == Some("text") {
                if let Some(chunk) = part.get("text").and_then(|v| v.as_str()) {
                    if !text.is_empty() {
                        text.push('\n');
                    }
                    text.push_str(chunk);
                }
            } else if images.len() < MAX_IMAGES {
                if let Some(image) = image_from_part(part) {
                    images.push(image);
                }
            }
        }
    }
    if text.is_empty() && images.is_empty() {
        text = result.to_string();
    } else if text.is_empty() {
        text = "Image captured.".into();
    }
    truncate_text(&mut text);
    let mut omitted = false;
    images.retain(|image| {
        if image.data.len() <= MAX_IMAGE_B64 {
            true
        } else {
            omitted = true;
            false
        }
    });
    while !images.is_empty() && reply_len(&text, &images) > MAX_RESULT {
        images.pop();
        omitted = true;
    }
    if omitted {
        if !text.is_empty() {
            text.push('\n');
        }
        text.push_str("[image omitted: too large to send]");
        truncate_text(&mut text);
    }
    McpReply { text, images }
}

fn truncate_text(text: &mut String) {
    if text.len() > MAX_TEXT {
        text.truncate(MAX_TEXT);
    }
}

fn reply_len(text: &str, images: &[McpImage]) -> usize {
    let images_json: Vec<Value> = images
        .iter()
        .map(|image| json!({"mime": image.mime, "data": image.data}))
        .collect();
    json!({"ok": true, "text": text, "images": images_json})
        .to_string()
        .len()
}

fn image_from_part(part: &Value) -> Option<McpImage> {
    let kind = part.get("type").and_then(|v| v.as_str()).unwrap_or("");
    let (mime, data) = if kind == "image" {
        (
            part.get("mimeType").and_then(|v| v.as_str()).unwrap_or(""),
            part.get("data").and_then(|v| v.as_str()).unwrap_or(""),
        )
    } else if kind == "resource" {
        let resource = part.get("resource")?;
        (
            resource.get("mimeType").and_then(|v| v.as_str()).unwrap_or(""),
            resource.get("blob").and_then(|v| v.as_str()).unwrap_or(""),
        )
    } else {
        return None;
    };
    let mime = mime.split(';').next().unwrap_or("").trim().to_ascii_lowercase();
    if !mime.starts_with("image/") || mime == "image/svg+xml" || data.is_empty() {
        return None;
    }
    Some(McpImage {
        mime,
        data: data.to_string(),
    })
}

struct Session {
    #[allow(dead_code)]
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<tokio::process::ChildStdout>,
    next_id: i64,
}

pub struct Running {
    pub name: String,
    pub tools: Vec<Value>,
    pub error: Option<String>,
    session: Option<Session>,
}

pub async fn start_all(servers: &[McpServer]) -> Vec<Running> {
    let mut out = Vec::new();
    for server in servers {
        if server.name.trim().is_empty() || server.command.trim().is_empty() {
            continue;
        }
        out.push(start_one(server).await);
    }
    out
}

async fn start_one(server: &McpServer) -> Running {
    let program = expand_env(server.command.trim());
    let args: Vec<String> = split_args(&server.args)
        .into_iter()
        .map(|arg| expand_env(&arg))
        .collect();
    let mut command = Command::new(&program);
    command
        .args(&args)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .kill_on_drop(true);
    #[cfg(windows)]
    {
        command.creation_flags(0x08000000);
    }
    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(err) => return Running::failed(&server.name, err.to_string()),
    };
    let Some(stdin) = child.stdin.take() else {
        return Running::failed(&server.name, "mcp stdin missing".into());
    };
    let Some(stdout) = child.stdout.take() else {
        return Running::failed(&server.name, "mcp stdout missing".into());
    };
    let mut running = Running {
        name: server.name.clone(),
        tools: Vec::new(),
        error: None,
        session: Some(Session {
            child,
            stdin,
            stdout: BufReader::new(stdout),
            next_id: 1,
        }),
    };
    if let Err(err) = running.initialize().await {
        running.error = Some(err);
        running.tools.clear();
        running.session = None;
    }
    running
}

impl Running {
    fn failed(name: &str, error: String) -> Self {
        Self {
            name: name.to_string(),
            tools: Vec::new(),
            error: Some(error),
            session: None,
        }
    }

    pub async fn shutdown(&mut self) {
        if let Some(session) = self.session.as_mut() {
            let _ = session.child.start_kill();
        }
        self.session = None;
    }

    pub fn catalog_entry(&self) -> Value {
        json!({
            "name": self.name,
            "tools": self.tools,
        })
    }

    async fn initialize(&mut self) -> Result<(), String> {
        self.request(
            "initialize",
            json!({
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "autonomous-companion", "version": "0.1.0"}
            }),
        )
        .await?;
        self.notify("notifications/initialized", json!({})).await?;
        let listed = self.request("tools/list", json!({})).await?;
        self.tools = listed
            .get("tools")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default()
            .into_iter()
            .map(|tool| {
                json!({
                    "name": tool.get("name").and_then(|v| v.as_str()).unwrap_or(""),
                    "description": tool.get("description").and_then(|v| v.as_str()).unwrap_or(""),
                    "input_schema": tool.get("inputSchema").cloned().unwrap_or_else(|| json!({}))
                })
            })
            .filter(|tool| tool.get("name").and_then(|v| v.as_str()).unwrap_or("") != "")
            .collect();
        Ok(())
    }

    pub async fn call(&mut self, tool: &str, arguments: &Value) -> Result<McpReply, String> {
        let result = self
            .request(
                "tools/call",
                json!({ "name": tool, "arguments": arguments }),
            )
            .await?;
        Ok(reply_from_result(&result))
    }

    async fn notify(&mut self, method: &str, params: Value) -> Result<(), String> {
        let body = json!({"jsonrpc": "2.0", "method": method, "params": params});
        self.write_message(&body).await
    }

    async fn request(&mut self, method: &str, params: Value) -> Result<Value, String> {
        let id = {
            let session = self
                .session
                .as_mut()
                .ok_or_else(|| "mcp not running".to_string())?;
            let id = session.next_id;
            session.next_id += 1;
            id
        };
        let body = json!({"jsonrpc": "2.0", "id": id, "method": method, "params": params});
        self.write_message(&body).await?;
        let deadline = tokio::time::Instant::now() + Duration::from_secs(45);
        loop {
            let message = tokio::time::timeout_at(deadline, self.read_message())
                .await
                .map_err(|_| "mcp timed out".to_string())??;
            if message.get("id").and_then(|v| v.as_i64()) == Some(id) {
                if let Some(err) = message.get("error") {
                    return Err(err.to_string());
                }
                return Ok(message.get("result").cloned().unwrap_or(Value::Null));
            }
        }
    }

    async fn write_message(&mut self, body: &Value) -> Result<(), String> {
        let session = self.session.as_mut().ok_or_else(|| "mcp not running".to_string())?;
        let bytes = frame_message(body)?;
        session
            .stdin
            .write_all(&bytes)
            .await
            .map_err(|e| e.to_string())?;
        session.stdin.flush().await.map_err(|e| e.to_string())
    }

    async fn read_message(&mut self) -> Result<Value, String> {
        let session = self.session.as_mut().ok_or_else(|| "mcp not running".to_string())?;
        loop {
            let mut line = String::new();
            let n = session
                .stdout
                .read_line(&mut line)
                .await
                .map_err(|e| e.to_string())?;
            if n == 0 {
                return Err("mcp closed stdout".into());
            }
            match classify_line(&line) {
                StdioLine::Empty | StdioLine::Ignore => continue,
                StdioLine::Json(value) => return Ok(value),
                StdioLine::ContentLength(length) => {
                    loop {
                        let mut extra = String::new();
                        let n = session
                            .stdout
                            .read_line(&mut extra)
                            .await
                            .map_err(|e| e.to_string())?;
                        if n == 0 {
                            return Err("mcp closed stdout".into());
                        }
                        if extra.trim().is_empty() {
                            break;
                        }
                    }
                    let mut buf = vec![0u8; length];
                    session
                        .stdout
                        .read_exact(&mut buf)
                        .await
                        .map_err(|e| e.to_string())?;
                    return serde_json::from_slice(&buf).map_err(|e| e.to_string());
                }
            }
        }
    }
}

fn frame_message(body: &Value) -> Result<Vec<u8>, String> {
    let mut bytes = serde_json::to_vec(body).map_err(|e| e.to_string())?;
    bytes.push(b'\n');
    Ok(bytes)
}

enum StdioLine {
    Empty,
    Ignore,
    Json(Value),
    ContentLength(usize),
}

fn classify_line(line: &str) -> StdioLine {
    let trimmed = line.trim();
    if trimmed.is_empty() {
        return StdioLine::Empty;
    }
    if trimmed.starts_with('{') || trimmed.starts_with('[') {
        return match serde_json::from_str(trimmed) {
            Ok(value) => StdioLine::Json(value),
            Err(_) => StdioLine::Ignore,
        };
    }
    if let Some(rest) = trimmed.to_ascii_lowercase().strip_prefix("content-length:") {
        if let Ok(length) = rest.trim().parse::<usize>() {
            return StdioLine::ContentLength(length);
        }
    }
    StdioLine::Ignore
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frames_one_json_line() {
        let bytes = frame_message(&json!({"jsonrpc": "2.0", "id": 1})).unwrap();
        assert_eq!(bytes.last(), Some(&b'\n'));
        assert!(bytes.iter().filter(|b| **b == b'\n').count() == 1);
        match classify_line(std::str::from_utf8(&bytes).unwrap()) {
            StdioLine::Json(value) => assert_eq!(value["id"], 1),
            _ => panic!("expected json"),
        }
    }

    #[test]
    fn reads_vectorcraft_lines_and_content_length() {
        match classify_line("vectorcraft-cli: MCP server on stdio (headless)\n") {
            StdioLine::Ignore => {}
            _ => panic!("banner is not a message"),
        }
        match classify_line("Content-Length: 12\r\n") {
            StdioLine::ContentLength(12) => {}
            _ => panic!("expected length"),
        }
    }

    #[test]
    fn keeps_screenshot_image_and_text() {
        let result = json!({
            "content": [
                {"type": "text", "text": "Screenshot Size: (1920,1080)"},
                {"type": "image", "data": "abc", "mimeType": "image/png"},
                {"type": "resource", "resource": {"mimeType": "image/jpeg", "blob": "zzz"}}
            ]
        });
        let reply = reply_from_result(&result);
        assert_eq!(reply.text, "Screenshot Size: (1920,1080)");
        assert_eq!(reply.images.len(), 2);
        assert_eq!(reply.images[0].mime, "image/png");
        assert_eq!(reply.images[0].data, "abc");
        assert_eq!(reply.images[1].mime, "image/jpeg");
    }

    #[test]
    fn drops_an_image_that_would_not_fit_the_frame() {
        let huge = "A".repeat(MAX_IMAGE_B64 + 8);
        let result = json!({
            "content": [
                {"type": "text", "text": "too big"},
                {"type": "image", "data": huge, "mimeType": "image/png"}
            ]
        });
        let reply = reply_from_result(&result);
        assert!(reply.images.is_empty());
        assert!(reply.text.contains("too large"));
    }
}
