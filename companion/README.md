# Autonomous Companion

Program for the user's computer (Windows first; the same code targets Linux and macOS).

1. Enter the instance URL (`http://…` or `https://…`).
2. Next: a code is displayed. In Autonomous, **Settings → Companions → Allow**.
3. The device token is kept in the config folder. Closing the window leaves it in the notification area.
4. Options:
   - **Bots' Internet via this PC**: TCP traffic from the Autonomous VMs, and their DNS, go out through this computer. Only one companion can carry this Internet at a time.
   - **Kill switch**: if the tunnel drops, the VMs lose network access (they keep access to the instance). Otherwise they fall back to the server.
   - **MCP**: name, command and arguments. The companion launches the process and the bots call `mcp_list` / `mcp_call`.
   - **Notifications**: badge on the tray icon, on-screen message, sound, and **Keep notifications on screen** (off by default; also on the main companion screen). When on, Windows shows the toast as a *reminder* with **Open** / **Dismiss** buttons: it stays until you click it (opens the bot chat, or the URL it refers to), click **Open**, or close it with **Dismiss** / X. Linux: critical urgency with no timeout (the notification daemon decides). macOS: no effect.

## Build

The server builds it automatically at startup — in a throwaway Docker container when Docker works (`build/Dockerfile`, image `autonomous-companion-builder`: Rust + MinGW-w64 + GTK/tray dev libs; Linux and Windows binaries, caches under `$AUTONOMOUS_HOME/companion/`), otherwise with the host Rust — and serves it at **Settings → Companions** (`/settings/companions`). To build by hand:

Prerequisite: [Rust](https://rustup.rs) stable.

```bash
cd companion
cargo build --release
```

- Windows: `target\release\autonomous-companion.exe`
- Linux: same sources. The UI requires the system GTK/tray libs; `cargo test --no-default-features --lib` checks the protocol without a window.
- macOS: same command `cargo build --release` on a Mac (the server does not build macOS).

The server download is named `autonomous-companion-<Autonomous version>.exe` (Linux: no `.exe`). The version follows Autonomous, not this crate's `0.1.0`.

A paired companion checks for a new binary each time its tunnel connects (a server restart drops that connection). If a compile is still running, it waits until the build is finished and does not install the previous file. When the sha256 differs, it downloads that file with its device token, replaces itself in place, and restarts. A build launched from `target/debug` or `target/release` does not replace itself.

**Start when you sign in** is a checkbox in the companion (off by default). It runs at login, not before the desktop session exists. Windows: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Autonomous Companion.cmd`. Linux: `~/.config/autostart/autonomous-companion.desktop`. macOS: `~/Library/LaunchAgents/fr.mister3d.autonomous-companion.plist`. Untick to remove it.

The config is in the application folder (`%APPDATA%\Autonomous\config\companion.json` on Windows, `~/.config/autonomous/companion.json` on Linux; an older `%APPDATA%\mister3d\Autonomous\config\companion.json` is still read). Do not commit it: it contains the device token.
