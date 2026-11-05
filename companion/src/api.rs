use crate::config::{api_url, platform_name, Config};
use serde::Deserialize;
use serde_json::json;

fn client() -> Result<reqwest::blocking::Client, String> {
    reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .map_err(|e| e.to_string())
}

#[derive(Debug, Deserialize)]
pub struct PairStart {
    pub pair_id: String,
    pub user_code: String,
    pub poll_secret: String,
}

#[derive(Debug, Deserialize)]
pub struct PairPoll {
    pub status: String,
    pub device_id: Option<String>,
    pub device_token: Option<String>,
}

pub fn pair(instance: &str, name: &str) -> Result<PairStart, String> {
    let response = client()?
        .post(api_url(instance, "/devices/pair"))
        .json(&json!({ "name": name, "platform": platform_name() }))
        .send()
        .map_err(|e| e.to_string())?;
    let status = response.status();
    let text = response.text().map_err(|e| e.to_string())?;
    if !status.is_success() {
        return Err(text);
    }
    serde_json::from_str(&text).map_err(|e| e.to_string())
}

pub fn poll(instance: &str, pair_id: &str, poll_secret: &str) -> Result<PairPoll, String> {
    let response = client()?
        .post(api_url(instance, "/devices/pair-poll"))
        .json(&json!({ "pair_id": pair_id, "poll_secret": poll_secret }))
        .send()
        .map_err(|e| e.to_string())?;
    let status = response.status();
    let text = response.text().map_err(|e| e.to_string())?;
    if !status.is_success() {
        return Err(text);
    }
    serde_json::from_str(&text).map_err(|e| e.to_string())
}

pub fn set_options(config: &Config) -> Result<(), String> {
    authed(config, reqwest::Method::PATCH, "/devices/me")?
        .json(&json!({
            "egress": config.egress,
            "killswitch": config.killswitch,
        }))
        .send()
        .map_err(|e| e.to_string())?
        .error_for_status()
        .map_err(|e| e.to_string())?;
    Ok(())
}

pub fn put_mcp(config: &Config, servers: serde_json::Value) -> Result<(), String> {
    authed(config, reqwest::Method::PUT, "/devices/me/mcp")?
        .json(&json!({ "servers": servers }))
        .send()
        .map_err(|e| e.to_string())?
        .error_for_status()
        .map_err(|e| e.to_string())?;
    Ok(())
}

/// Ask the instance to reuse an open hub tab. `Ok(true)` means a tab was listening.
pub fn focus_open(config: &Config, bot: &str) -> Result<bool, String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .build()
        .map_err(|e| e.to_string())?;
    let response = client
        .post(api_url(&config.instance_url, "/devices/me/focus"))
        .header(
            "Authorization",
            format!("Bearer {}", config.device_token),
        )
        .json(&json!({ "bot": bot }))
        .send()
        .map_err(|e| e.to_string())?;
    let status = response.status();
    let text = response.text().map_err(|e| e.to_string())?;
    if !status.is_success() {
        return Err(text);
    }
    let value: serde_json::Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    Ok(value.get("open").and_then(|v| v.as_bool()).unwrap_or(false))
}

pub fn forget(config: &Config) -> Result<(), String> {
    authed(config, reqwest::Method::DELETE, "/devices/me")?
        .send()
        .map_err(|e| e.to_string())?
        .error_for_status()
        .map_err(|e| e.to_string())?;
    Ok(())
}

fn authed(
    config: &Config,
    method: reqwest::Method,
    path: &str,
) -> Result<reqwest::blocking::RequestBuilder, String> {
    Ok(client()?
        .request(method, api_url(&config.instance_url, path))
        .header(
            "Authorization",
            format!("Bearer {}", config.device_token),
        ))
}
