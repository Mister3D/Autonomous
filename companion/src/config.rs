use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct McpServer {
    pub name: String,
    pub command: String,
    pub args: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub instance_url: String,
    #[serde(default)]
    pub device_token: String,
    #[serde(default)]
    pub device_id: String,
    #[serde(default)]
    pub egress: bool,
    #[serde(default)]
    pub killswitch: bool,
    #[serde(default = "on")]
    pub notify_badge: bool,
    #[serde(default = "on")]
    pub notify_toast: bool,
    #[serde(default = "on")]
    pub notify_sound: bool,
    /// Toasts stay on screen until clicked or dismissed (Windows reminder scenario).
    #[serde(default)]
    pub persistent_notifications: bool,
    /// Start the companion when the user signs in (desktop session, not pre-login boot).
    #[serde(default)]
    pub launch_at_login: bool,
    #[serde(default)]
    pub mcp: Vec<McpServer>,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            instance_url: String::new(),
            device_token: String::new(),
            device_id: String::new(),
            egress: false,
            killswitch: false,
            notify_badge: true,
            notify_toast: true,
            notify_sound: true,
            persistent_notifications: false,
            launch_at_login: false,
            mcp: Vec::new(),
        }
    }
}

fn on() -> bool {
    true
}

/// `%APPDATA%\Autonomous\config` on Windows, `~/.config/autonomous` on Linux.
pub fn config_path() -> Option<PathBuf> {
    directories::ProjectDirs::from("", "", "Autonomous")
        .map(|dirs| dirs.config_dir().join("companion.json"))
}

/// Location used by versions <= 0.1.0; read once if the new file is absent.
fn legacy_config_path() -> Option<PathBuf> {
    directories::ProjectDirs::from("fr", "mister3d", "Autonomous")
        .map(|dirs| dirs.config_dir().join("companion.json"))
}

pub fn load() -> Config {
    let Some(path) = config_path() else {
        return Config::default();
    };
    let text = match fs::read_to_string(&path) {
        Ok(text) => text,
        Err(_) => match legacy_config_path().and_then(|p| fs::read_to_string(p).ok()) {
            Some(text) => text,
            None => return Config::default(),
        },
    };
    serde_json::from_str(&text).unwrap_or_default()
}

pub fn save(config: &Config) -> Result<(), String> {
    let path = config_path().ok_or_else(|| "no config directory".to_string())?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let text = serde_json::to_string_pretty(config).map_err(|e| e.to_string())?;
    fs::write(&path, text).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(path, fs::Permissions::from_mode(0o600));
    }
    Ok(())
}

pub fn normalize_url(input: &str) -> Result<String, String> {
    let url = input.trim().trim_end_matches('/').to_string();
    if !(url.starts_with("http://") || url.starts_with("https://")) {
        return Err("L'URL doit commencer par http:// ou https://".into());
    }
    Ok(url)
}

pub fn ws_url(instance: &str) -> String {
    let base = instance.trim_end_matches('/');
    if let Some(rest) = base.strip_prefix("https://") {
        format!("wss://{rest}/ws/companion")
    } else if let Some(rest) = base.strip_prefix("http://") {
        format!("ws://{rest}/ws/companion")
    } else {
        format!("ws://{base}/ws/companion")
    }
}

pub fn api_url(instance: &str, path: &str) -> String {
    format!("{}/api/v1{path}", instance.trim_end_matches('/'))
}

/// Page de discussion du bot, à ouvrir quand l'utilisateur clique une notification.
pub fn discussion_url(instance: &str, bot: &str) -> String {
    let bot = bot.trim();
    let base = instance.trim().trim_end_matches('/');
    if bot.is_empty() || base.is_empty() {
        return String::new();
    }
    format!("{base}/b/{}/discussion", encode_segment(bot))
}

/// Bot slug when `url` is the discussion page of this instance.
pub fn discussion_bot(instance: &str, url: &str) -> Option<String> {
    let base = instance.trim().trim_end_matches('/');
    let url = url.trim().trim_end_matches('/');
    let rest = url.strip_prefix(base)?;
    let rest = rest.strip_prefix("/b/")?;
    let bot = rest.strip_suffix("/discussion")?;
    if bot.is_empty() || bot.contains('/') {
        return None;
    }
    Some(bot.to_string())
}

fn encode_segment(raw: &str) -> String {
    let mut out = String::new();
    for b in raw.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char);
            }
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

/// Replace `%NAME%` with the environment variable. Unknown names stay as written.
/// `%%` is a literal percent. The looked-up value is not expanded again.
pub fn expand_env(input: &str) -> String {
    let chars: Vec<char> = input.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < chars.len() {
        if chars[i] != '%' {
            out.push(chars[i]);
            i += 1;
            continue;
        }
        if chars.get(i + 1) == Some(&'%') {
            out.push('%');
            i += 2;
            continue;
        }
        let end = chars[i + 1..].iter().position(|c| *c == '%');
        if let Some(end) = end {
            let name: String = chars[i + 1..i + 1 + end].iter().collect();
            if let Some(value) = env_name(&name).and_then(lookup_env) {
                out.push_str(&value);
                i += end + 2;
                continue;
            }
        }
        out.push('%');
        i += 1;
    }
    out
}

fn env_name(name: &str) -> Option<&str> {
    let mut chars = name.chars();
    match chars.next() {
        Some(c) if c.is_ascii_alphabetic() || c == '_' => {}
        _ => return None,
    }
    if chars.all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '(' | ')')) {
        Some(name)
    } else {
        None
    }
}

fn lookup_env(name: &str) -> Option<String> {
    if let Ok(value) = std::env::var(name) {
        return Some(value);
    }
    std::env::vars()
        .find(|(key, _)| key.eq_ignore_ascii_case(name))
        .map(|(_, value)| value)
}

/// Split a command-line argument string. Quotes keep spaces together.
pub fn split_args(input: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let mut quote: Option<char> = None;
    for c in input.chars() {
        match quote {
            Some(q) if c == q => quote = None,
            Some(_) => cur.push(c),
            None if c == '"' || c == '\'' => quote = Some(c),
            None if c.is_whitespace() => {
                if !cur.is_empty() {
                    out.push(std::mem::take(&mut cur));
                }
            }
            None => cur.push(c),
        }
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

pub fn default_device_name() -> String {
    if let Ok(name) = std::env::var("COMPUTERNAME") {
        if !name.is_empty() {
            return name;
        }
    }
    std::env::var("HOSTNAME").unwrap_or_else(|_| "companion".into())
}

pub fn platform_name() -> &'static str {
    if cfg!(windows) {
        "windows"
    } else if cfg!(target_os = "macos") {
        "macos"
    } else {
        "linux"
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn urls() {
        assert_eq!(
            ws_url("https://bots.example/"),
            "wss://bots.example/ws/companion"
        );
        assert_eq!(
            api_url("http://127.0.0.1:8787", "/devices/pair"),
            "http://127.0.0.1:8787/api/v1/devices/pair"
        );
        assert_eq!(
            discussion_url("https://bots.example/", "fnac"),
            "https://bots.example/b/fnac/discussion"
        );
        assert_eq!(discussion_url("https://bots.example", ""), "");
        assert_eq!(
            discussion_url("https://bots.example", "a b"),
            "https://bots.example/b/a%20b/discussion"
        );
        assert_eq!(
            discussion_bot("https://bots.example/", "https://bots.example/b/fnac/discussion"),
            Some("fnac".into())
        );
        assert_eq!(
            discussion_bot("https://bots.example", "https://other.example/b/fnac/discussion"),
            None
        );
    }

    #[test]
    fn quoted_args() {
        assert_eq!(
            split_args(r#"--root "C:\Mes fichiers" -y"#),
            vec!["--root", r"C:\Mes fichiers", "-y"]
        );
    }

    #[test]
    fn expands_percent_env() {
        let key = "AUTONOMOUS_COMPANION_ENV_TEST";
        std::env::set_var(key, r"C:\Users\user\AppData\Local");
        assert_eq!(
            expand_env(r"%AUTONOMOUS_COMPANION_ENV_TEST%\Programs\ArtCraft\VectorCraft\vectorcraft-cli.exe"),
            r"C:\Users\user\AppData\Local\Programs\ArtCraft\VectorCraft\vectorcraft-cli.exe"
        );
        assert_eq!(
            expand_env(r"%autonomous_companion_env_test%\x"),
            r"C:\Users\user\AppData\Local\x"
        );
        assert_eq!(expand_env("100%"), "100%");
        assert_eq!(expand_env("%%AUTONOMOUS_COMPANION_ENV_TEST%%"), "%AUTONOMOUS_COMPANION_ENV_TEST%");
        assert_eq!(expand_env("%MISSING_VAR_XYZ%"), "%MISSING_VAR_XYZ%");
        assert_eq!(
            split_args(r#"mcp --root "%AUTONOMOUS_COMPANION_ENV_TEST%\work files""#)
                .into_iter()
                .map(|arg| expand_env(&arg))
                .collect::<Vec<_>>(),
            vec![
                "mcp",
                "--root",
                r"C:\Users\user\AppData\Local\work files",
            ]
        );
        std::env::remove_var(key);
    }
}

#[cfg(test)]
mod persist_tests {
    use super::*;

    #[test]
    fn persistent_notifications_default_off() {
        assert!(!Config::default().persistent_notifications);
        let old: Config = serde_json::from_str(r#"{"instance_url":"http://x"}"#).unwrap();
        assert!(!old.persistent_notifications);
        let on: Config =
            serde_json::from_str(r#"{"instance_url":"http://x","persistent_notifications":true}"#).unwrap();
        assert!(on.persistent_notifications);
    }
}
