//! Outbound WebSocket to the instance. The PC dials targets and answers DNS.

use crate::api::put_mcp;
use crate::config::{ws_url, Config, McpServer};
use crate::mcp::{self, Running};
use crate::proto::{self, decode, encode};
use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::mpsc::{Receiver, Sender};
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio::sync::mpsc;
use tokio_tungstenite::tungstenite::client::IntoClientRequest;
use tokio_tungstenite::tungstenite::http::HeaderValue;
use tokio_tungstenite::tungstenite::Message;

pub enum Command {
    Mcp(Vec<McpServer>),
    Shutdown,
}

pub enum Status {
    Connected,
    Disconnected(String),
    Note(String),
    Alert {
        title: String,
        body: String,
        bot: String,
    },
}

pub fn serve(config: Config, commands: Receiver<Command>, status: Sender<Status>) {
    let runtime = match tokio::runtime::Runtime::new() {
        Ok(runtime) => runtime,
        Err(err) => {
            let _ = status.send(Status::Disconnected(err.to_string()));
            return;
        }
    };
    runtime.block_on(async move {
        let mut mcp_servers = config.mcp.clone();
        loop {
            if let Ok(command) = commands.try_recv() {
                match command {
                    Command::Shutdown => return,
                    Command::Mcp(servers) => mcp_servers = servers,
                }
            }
            match connect_once(&config, &mcp_servers, &commands, &status).await {
                Err(Stop::Shutdown) => return,
                Err(Stop::Reload(servers)) => {
                    mcp_servers = servers;
                    continue;
                }
                Ok(()) => {
                    let _ = status.send(Status::Disconnected("tunnel closed".into()));
                }
                Err(Stop::Lost(message)) => {
                    let _ = status.send(Status::Disconnected(message));
                }
            }
            tokio::time::sleep(Duration::from_secs(3)).await;
        }
    });
}

enum Stop {
    Shutdown,
    Lost(String),
    Reload(Vec<McpServer>),
}

async fn connect_once(
    config: &Config,
    mcp_servers: &[McpServer],
    commands: &Receiver<Command>,
    status: &Sender<Status>,
) -> Result<(), Stop> {
    let mut request = ws_url(&config.instance_url)
        .into_client_request()
        .map_err(|e| Stop::Lost(e.to_string()))?;
    request.headers_mut().insert(
        "Authorization",
        HeaderValue::from_str(&format!("Bearer {}", config.device_token))
            .map_err(|e| Stop::Lost(e.to_string()))?,
    );
    let (socket, _) = tokio_tungstenite::connect_async(request)
        .await
        .map_err(|e| Stop::Lost(e.to_string()))?;
    let _ = status.send(Status::Connected);
    let (mut write, mut read) = socket.split();
    let (out_tx, mut out_rx) = mpsc::unbounded_channel::<Vec<u8>>();
    let writer = tokio::spawn(async move {
        while let Some(frame) = out_rx.recv().await {
            if write.send(Message::Binary(frame.into())).await.is_err() {
                break;
            }
        }
    });

    let mut processes = mcp::start_all(mcp_servers).await;
    publish_catalog(config, &processes, status);
    let mut streams: HashMap<u32, mpsc::UnboundedSender<Vec<u8>>> = HashMap::new();
    let mut ping = tokio::time::interval(Duration::from_secs(20));

    loop {
        tokio::select! {
            _ = ping.tick() => {
                if out_tx.send(encode(proto::PING, 0, b"")).is_err() {
                    break;
                }
            }
            incoming = read.next() => {
                let Some(message) = incoming else { break };
                let message = match message {
                    Ok(message) => message,
                    Err(err) => return Err(Stop::Lost(err.to_string())),
                };
                if message.is_close() {
                    break;
                }
                let Message::Binary(bytes) = message else { continue };
                let Some((op, stream_id, payload)) = decode(&bytes) else { continue };
                handle_frame(
                    op,
                    stream_id,
                    payload,
                    &out_tx,
                    &mut streams,
                    &mut processes,
                    status,
                )
                .await;
            }
            _ = tokio::time::sleep(Duration::from_millis(250)) => {
                match commands.try_recv() {
                    Ok(Command::Shutdown) => return Err(Stop::Shutdown),
                    Ok(Command::Mcp(servers)) => return Err(Stop::Reload(servers)),
                    Err(_) => {}
                }
            }
        }
    }
    writer.abort();
    for process in &mut processes {
        process.shutdown().await;
    }
    Ok(())
}

fn publish_catalog(config: &Config, processes: &[Running], status: &Sender<Status>) {
    let servers: Vec<Value> = processes.iter().map(|p| p.catalog_entry()).collect();
    for process in processes {
        if let Some(error) = &process.error {
            let _ = status.send(Status::Note(format!("{}: {error}", process.name)));
        }
    }
    if let Err(err) = put_mcp(config, Value::Array(servers)) {
        let _ = status.send(Status::Note(format!("catalogue MCP: {err}")));
    }
}

async fn handle_frame(
    op: u8,
    stream_id: u32,
    payload: &[u8],
    out_tx: &mpsc::UnboundedSender<Vec<u8>>,
    streams: &mut HashMap<u32, mpsc::UnboundedSender<Vec<u8>>>,
    processes: &mut [Running],
    status: &Sender<Status>,
) {
    match op {
        proto::OPEN => {
            let text = String::from_utf8_lossy(payload);
            let mut parts = text.split('\n');
            let host = parts.next().unwrap_or("").to_string();
            let port: u16 = parts.next().unwrap_or("0").parse().unwrap_or(0);
            let tx = out_tx.clone();
            let (data_tx, data_rx) = mpsc::unbounded_channel();
            streams.insert(stream_id, data_tx);
            tokio::spawn(async move {
                dial(stream_id, host, port, tx, data_rx).await;
            });
        }
        proto::DATA => {
            if let Some(tx) = streams.get(&stream_id) {
                let _ = tx.send(payload.to_vec());
            }
        }
        proto::CLOSE => {
            streams.remove(&stream_id);
        }
        proto::DNS => {
            let tx = out_tx.clone();
            let query = payload.to_vec();
            tokio::spawn(async move {
                match forward_dns(&query).await {
                    Ok(reply) => {
                        let _ = tx.send(encode(proto::DNS_OK, stream_id, &reply));
                    }
                    Err(err) => {
                        let _ = tx.send(encode(proto::DNS_ERR, stream_id, err.as_bytes()));
                    }
                }
            });
        }
        proto::MCP_CALL => {
            let tx = out_tx.clone();
            let payload = payload.to_vec();
            let result = call_mcp(processes, &payload).await;
            let _ = tx.send(encode(proto::MCP_RESULT, stream_id, &result));
        }
        proto::PING => {
            let _ = out_tx.send(encode(proto::PONG, stream_id, payload));
        }
        proto::NOTIFY => {
            let value: Value = serde_json::from_slice(payload).unwrap_or(json!({}));
            let title = value
                .get("title")
                .and_then(|v| v.as_str())
                .unwrap_or("Autonomous")
                .to_string();
            let body = value
                .get("body")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let bot = value
                .get("bot")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let _ = status.send(Status::Alert { title, body, bot });
        }
        _ => {}
    }
}

async fn dial(
    stream_id: u32,
    host: String,
    port: u16,
    tx: mpsc::UnboundedSender<Vec<u8>>,
    mut data_rx: mpsc::UnboundedReceiver<Vec<u8>>,
) {
    let stream = match TcpStream::connect((host.as_str(), port)).await {
        Ok(stream) => stream,
        Err(err) => {
            let _ = tx.send(encode(proto::OPEN_ERR, stream_id, err.to_string().as_bytes()));
            return;
        }
    };
    if tx.send(encode(proto::OPEN_OK, stream_id, b"")).is_err() {
        return;
    }
    let (mut read_half, mut write_half) = stream.into_split();
    let tx_up = tx.clone();
    let uplink = tokio::spawn(async move {
        let mut buf = vec![0u8; 32768];
        loop {
            match read_half.read(&mut buf).await {
                Ok(0) | Err(_) => break,
                Ok(n) => {
                    if tx_up.send(encode(proto::DATA, stream_id, &buf[..n])).is_err() {
                        break;
                    }
                }
            }
        }
        let _ = tx_up.send(encode(proto::CLOSE, stream_id, b""));
    });
    while let Some(chunk) = data_rx.recv().await {
        if write_half.write_all(&chunk).await.is_err() {
            break;
        }
    }
    uplink.abort();
}

async fn forward_dns(query: &[u8]) -> Result<Vec<u8>, String> {
    let server = dns_server();
    let socket = tokio::net::UdpSocket::bind("0.0.0.0:0")
        .await
        .map_err(|e| e.to_string())?;
    socket
        .send_to(query, server)
        .await
        .map_err(|e| e.to_string())?;
    let mut buf = vec![0u8; 4096];
    let n = tokio::time::timeout(Duration::from_secs(3), socket.recv(&mut buf))
        .await
        .map_err(|_| "dns timeout".to_string())?
        .map_err(|e| e.to_string())?;
    buf.truncate(n);
    Ok(buf)
}

fn dns_server() -> String {
    if let Ok((config, _)) = hickory_resolver::system_conf::read_system_conf() {
        if let Some(ns) = config.name_servers().first() {
            return ns.socket_addr.to_string();
        }
    }
    "1.1.1.1:53".to_string()
}

async fn call_mcp(processes: &mut [Running], payload: &[u8]) -> Vec<u8> {
    let parsed: Value = match serde_json::from_slice(payload) {
        Ok(value) => value,
        Err(err) => return json!({"ok": false, "error": err.to_string()}).to_string().into_bytes(),
    };
    let server = parsed.get("server").and_then(|v| v.as_str()).unwrap_or("");
    let tool = parsed.get("tool").and_then(|v| v.as_str()).unwrap_or("");
    let arguments = parsed.get("arguments").cloned().unwrap_or_else(|| json!({}));
    let Some(process) = processes.iter_mut().find(|p| p.name == server) else {
        return json!({"ok": false, "error": "unknown mcp server"}).to_string().into_bytes();
    };
    match process.call(tool, &arguments).await {
        Ok(text) => json!({"ok": true, "text": text}).to_string().into_bytes(),
        Err(err) => json!({"ok": false, "error": err}).to_string().into_bytes(),
    }
}

