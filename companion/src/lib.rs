//! Protocol, config, and tunnel used by the desktop companion.
//! The window and tray live behind the `gui` feature.

mod api;
mod autostart;
mod config;
mod update;
mod mcp;
mod proto;
mod tunnel;

pub use api::{forget, pair, poll, put_mcp, set_options, PairStart};
pub use config::{load, save, Config, McpServer};
pub use tunnel::{serve, Command, Status};

#[cfg(feature = "gui")]
mod gui;

#[cfg(feature = "gui")]
pub use gui::run;
