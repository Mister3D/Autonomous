# Agent → VM terminal (server)

**Status**: in place (one-shot exec; interactive PTY = UI tab only)  
**Key files**: `autonomous/services/terminal.py`, `autonomous/pi_extensions/vm.ts`, `autonomous/services/pi_rpc.py`, `POST /bots/:name/terminal/exec`  
**Last updated**: 2026-11-19 (UI shows elapsed / timeout while the command runs)

## User behaviour

- In the chat, the Pi agent runs commands (`date`, `curl`, `ping`, everything else) **in the VM** via `vm_terminal_exec`. Without a desktop, the tool requests the VM and waits. It does not invent the output.
- The desk user `autonomous` has **passwordless sudo**. Installing packages (`sudo apt-get install -y …`) for the task is normal. The agent must not invent an “I don’t have permission / authorize apt” story, and must not `ask_approval` for ordinary VM installs. The only desk gate is `vm_request_desk`.
- Opening a GUI app then showing a capture: `command -v` (install if missing), launch with `DISPLAY=:1`, **do not** redirect stderr to `/dev/null` on the first try, confirm the process is alive, then screenshot. Do not claim success from a silent `exit_code=0`. Pixel check → `vm_look` (not inventing from `vm_screenshot`, which never sends the PNG to the model).
- **Using** a native GUI (press calculator buttons, menus): prefer `vm_ground` → `vm_click` / `vm_type`. Do not drive the UI with `xdotool` or guessed clicks in `vm_terminal_exec`; shell is for install/launch/checks. See [`grounding.md`](./grounding.md).
- Calls are made **server-side** (`docker exec`) — **no open UI** is needed.
- While a `vm_terminal_exec` is running, the tool row / folded live line shows **elapsed / timeout** (e.g. `26s / 30s`) from `meta.args.timeout` (default **30** s when omitted, max 600).
- There is **no host bash**: Pi always starts with `--exclude-tools bash`. To act on the Autonomous host machine itself, the operator gives credentials via the vault (or works outside Autonomous).
- Pi VM tools:
  - `vm_desk_status` — capability + desk state (if not ready → says to call `vm_request_desk`, **without** posting the card);
  - `vm_request_desk` — card + **blocking wait** until desk `running` / refusal (like the vault);
  - `vm_terminal_exec` / `vm_screenshot` — if the desk is absent, they request the desktop and **wait** too (then retry).
- VM prerequisite: desk **running** (or **sleeping** → the tool waits). One creation gives the shell and the screen (`capability=screen`). `terminal` is still read as "VM present" for old rows. A chat message does not start the VM.
- Desk `sleeping`: the VM tools wake it. The server inserts one `vm_wake` tool card and blocks that tool until the container is up; the model does not check or call it. **Don't** re-post a `vm_request_desk` card just for that. `POST /desk/wake` (Screen **Wake**) and the Terminal tab wake with no card.

## Implementation

- `term_svc.exec_command`: `docker exec … timeout -k 5 <seconds> bash -lc` inside the desk container. The host closes the pipes at the deadline, so a stuck read cannot keep the tool running. The Pi tool aborts its own HTTP call 15s after that deadline if the reply never arrives.
- `GET /bots/:name/desk` exposes `pending_request_id` / `pending_state` for agent polling.

## Pitfalls / non-regressions

- This is **not** the Terminal tab's WebSocket PTY.
- A `timeout` of 300s must end the tool around that mark. Killing only the `docker exec` client leaves the command alive in the VM and the chat on "en cours". The tool result then says `[timeout after Ns] The timeout stopped this command.` A click on **Arrêter l’outil** says `[user stopped] The user stopped this command.`
- Don't make `vm_request_desk` return immediately after the card: the agent would carry on for nothing.
- Restart the Pi session after changing `vm.ts`.

## Quick check

```bash
python3 -m pytest tests/test_terminal_exec.py -q
```
