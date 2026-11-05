# Companion (the user's PC)

**Status**: in place  
**Key files**: `companion/` (Rust), `autonomous/services/devices.py`, `autonomous/services/companion_link.py`, `autonomous/services/companion_egress.py`, `autonomous/companion_ws.py`, `autonomous/pi_extensions/companion.ts`, `frontend/src/components/SettingsModal.vue`  
**Last updated**: 2026-11-05 (pairing off switch + pair-poll rate-limit)

## User behaviour

- Install the companion on the PC (Windows first; Linux and macOS = the same Rust project).
- Enter the instance URL, **Next**. An `ABCD-EFGH` code is displayed.
- In the hub: menu → **Settings**, **Companions** tab → Allow. A switch **Allow new pairing** (`companions.enabled`, default on) can refuse new `pair` / `pair-poll` requests (already paired PCs keep working). The justified intro text explains the role (connect the PC, traffic via the companion, installed and configured MCPs) and points to the bot configuration. A sentence reminds that the user is solely responsible for what the bots might run on the machine. This page lists the PCs, says whether they are online, revokes them, and chooses which ones receive notifications. The name and platform (Windows, Linux, macOS) are on the same line. The companion keeps a device token (`adc_…`), revocable here or via "Forget this device".
- Closing the window does not quit: icon in the notification area. The same orange A, drawn crisply (not a 32-pixel grid), is the window and taskbar icon. A click on the icon near the clock opens the instance in the browser. Right click: reopen the window or quit.
- **Connection forwarding**: in the bot's details, a checkbox. Ticked with no paired companion, it saves nothing and opens Settings → Companions with the message "To route the connection through a companion, please add a companion." If there is at least one companion, the menu (same family as the model picker) asks which one; the button shows the name and an online / offline dot. Traffic from **this** bot (container labelled `autonomous.bot` = its slug) then goes out through that PC: TCP, plus DNS (UDP 53). QUIC (other UDP) is blocked so that Chrome falls back to TCP. Two bots can go through two different PCs. The host's other Docker containers are not affected. A bot with Internet off (`network=none`) has no address to redirect. Unticking stops forwarding and the kill switch; the chosen companion stays remembered for the next forwarding.
- **Kill switch**: bot option, visible only once the companion is chosen and forwarding is active. Tunnel down + kill switch = **this** VM has no more network to the outside. Without kill switch, it falls back to the server. Other bots are not cut off.
- **MCP**: the user adds a command and arguments on the companion. `%LOCALAPPDATA%` and other `%NAME%` are expanded at launch (the saved value keeps the `%NAME%`). The companion speaks JSON-RPC, one object per line (VectorCraft and the MCP standard). No automatic detection of already installed MCPs. Running the command by hand in a terminal does not connect it: it just waits on its standard input.
- **Per-bot authorisation**: in the bot's details, the **+** icon opens a small window: choose the companion, then the MCP server, then Add. Without this row, `mcp_list` is empty and `mcp_call` is refused, even if the companion is online. The row stays if the PC shuts down; the tools come back on reconnection. Two companions can expose the same name: the pair is what counts. An already launched Pi session only sees the new extension in the next process.
- **Notifications**: the agent calls `notify_user` only when the user asked to be notified. In the thread: centred yellow card (title + text), not a tool line, and not the "Notification sent…" bubble that repeats the same thing. In Settings → Companions, a **Notifications** checkbox per PC (ticked by default) chooses who receives them. **Test notification**, on that same page, sends "This is a test notification." to the ticked, online companions, without a conversation. The companion shows, according to its checkboxes: badge on the icon, Windows on-screen message, sound. A click on this message (or on the icon while the badge is there) brings up `/b/<bot>/discussion`. If a hub tab is already open, that tab comes to the foreground instead of opening another. Otherwise the browser opens. Nothing is sent on each webhook.
- The companion program no longer offers these two checkboxes: they stay in the bot's details. An old binary may still send `egress` / `killswitch` on `PATCH /devices/me`; the server stores them on the device and no longer uses them for iptables.

## Implementation

- Public pairing: `POST /api/v1/devices/pair` then `POST /api/v1/devices/pair-poll`. The token is returned only once. It does not open the rest of the API (only `/api/v1/devices/me` and `/ws/companion`). Pair starts: 5 / min / IP. Pair-poll: 60 / min / IP and 120 / min / `pair_id`. Both return 403 when `companions.enabled` is false.
- Tunnel: outgoing WebSocket `/ws/companion`, binary frames from `companion_proto.py` (OPEN / DATA / DNS / MCP_CALL). The server listens on a SOCKS and a DNS on `0.0.0.0` (needed for iptables `REDIRECT` onto the docker bridge address) but **accepts only** loopback and IPs of running `autonomous.bot` containers — LAN clients are dropped.
- `AUTONOMOUS_COMPANION_IPTABLES=0` disables iptables (pytest tests set it).
- Rules live in the `AUTONOMOUS_EGRESS` and `AUTONOMOUS_EGRESS_FILTER` chains. When `serve` starts, the current policy is reapplied (often "off", which removes the chains).
- Pi extension `companion.ts`: `mcp_list`, `mcp_call`, `notify_user`. An already launched Pi session only sees the extension in the next process.
- Grants: table `bot_mcp_grants` (bot, device, server). `GET /devices/mcp/tools?bot=` and `POST /devices/mcp/call` only see these rows. Revoking the companion removes its grants.

## Pitfalls / non-regressions

- Don't give the device token to the model, nor commit it.
- iptables must only match `autonomous.bot` IPs, never the whole Docker bridge.
- Traffic to the Docker subnet (instance API) is neither redirected nor cut.
- The kill switch only concerns bots that ticked it, and only while their companion is offline. Don't apply it to all desktops.
- Don't hand the whole MCP catalogue to a bot: without a grant, the list is empty.
- `notify_user` remains a tool `event` message in the database: the UI takes it out of the tool group and shows it as a card. Don't put it back into `ToolGroup`.

## Quick check

```bash
python3 -m pytest tests/test_companion.py -q
cd companion && cargo test --no-default-features --lib
```

Window: `cargo build --release` then launch the binary, pair from Settings. Internet egress is ticked in a bot's details, not in the companion. Don't enable it on an instance that has other containers if iptables is not understood.

## Build

`companion_build.py` builds in Docker when it works: image `autonomous-companion-builder:<Dockerfile hash>` from `companion/build/Dockerfile`, one `docker run --rm` per target (`x86_64-unknown-linux-gnu`, `x86_64-pc-windows-gnu`), sources mounted read-only, no privileged mode, no Docker socket. Caches: `$AUTONOMOUS_HOME/companion/docker-target` and `docker-cargo`. Without Docker (or with `AUTONOMOUS_COMPANION_DOCKER=0`) the host `cargo` is used. macOS is not built by the server. Logs stream to the setup job `companion`.

## Persistent notifications

Companion option `persistent_notifications` (off by default): Windows toast with `scenario="reminder"` plus **Open**/**Dismiss** buttons, stays until clicked or dismissed; Linux: critical urgency, no timeout; macOS: no effect.
