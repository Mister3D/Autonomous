# Interactive terminal (PTY)

**Status**: in place  
**Key files**:
- `frontend/src/components/TerminalPane.vue` (+ `@xterm/xterm`, `@xterm/addon-fit`)
- `autonomous/ptyws.py`
- `autonomous/wsproxy.py` (`/ws/terminal/<bot>`)
- `autonomous/cli.py` (`terminal_handler` MuxServer)
- Legacy API: `POST /bots/:name/terminal/exec` (one-shot, CLI)

**Last updated**: 2026-11-05 (WS requires session/Bearer)

## User behaviour

- **Terminal** tab = **real shell** (login bash in the same container as the screen), not a command queue. Creating the VM opens both tabs.
- TUI-compatible (`top`, editors, interactive input). `nano` is in the desktop image (rebuild); old VMs may not have it.
- No **Reconnect** button: when the tab is activated (`active=true`) the client reconnects / refits / focuses on its own.
- If the desk is **asleep**: "Waking desktop…" message then `POST /desk/wake` — not "create a desktop".
- xterm area in an orange accent frame (like the screen).

## Implementation

- Same-origin WS: `ws(s)://<host>/ws/terminal/<bot>`.
- Upgrade requires the web **session cookie** (sent automatically same-origin) or `Authorization: Bearer <API token>`. Unauthenticated clients get `401` before the 101.
- Server: `docker exec` TTY + stdin → WS frame bridge.
  - **Binary** frames = PTY bytes.
  - JSON **text** frames: `{"type":"resize","cols":N,"rows":M}` → `exec_resize`.
- Container user: `autonomous`, cwd `/home/autonomous/workspace`, `TERM=xterm-256color`.
- Frontend: `Terminal` + `FitAddon`, keystrokes sent as `Uint8Array`.

## Pitfalls / non-regressions

- **Never** `let ws = None` in JS (ReferenceError, empty panel) — that was a real bug.
- xterm import: the Vite bundle exposes `Terminal` correctly; in Node CJS it is sometimes `default.Terminal`.
- The old "composer + SQL log" mode is no longer enough for the UI; the `terminal/exec` API remains for the CLI **and** the Pi agent (`vm_terminal_exec`, without a browser — see `agent-vm-terminal.md`).
- MuxServer must route `/ws/terminal/` **before** / in addition to `/novnc/`.

## Quick check

```bash
# Handshake + echo (adapt bot name)
python3 -c "..."  # or open /b/<bot>/terminal and type echo ok
```

1. `/b/<bot>/terminal` → coloured bash prompt.
2. `stty size` after resizing the window follows the cols/rows.
3. Leave the tab then come back → session restored without a manual button.
