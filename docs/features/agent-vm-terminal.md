# Agent → VM terminal (server)

**Status**: in place (one-shot exec; interactive PTY = UI tab only)  
**Key files**: `autonomous/services/terminal.py`, `autonomous/pi_extensions/vm.ts`, `autonomous/services/pi_rpc.py`, `POST /bots/:name/terminal/exec`  
**Last updated**: 2026-11-14 (a vm_terminal_exec timeout kills the VM process and the wait)

## User behaviour

- In the chat, the Pi agent runs commands (`date`, `curl`, `ping`, everything else) **in the VM** via `vm_terminal_exec`. Without a desktop, the tool requests the VM and waits. It does not invent the output.
- Calls are made **server-side** (`docker exec`) — **no open UI** is needed.
- There is **no host bash**: Pi always starts with `--exclude-tools bash`. To act on the Autonomous host machine itself, the operator gives credentials via the vault (or works outside Autonomous).
- Pi VM tools:
  - `vm_desk_status` — capability + desk state (if not ready → says to call `vm_request_desk`, **without** posting the card);
  - `vm_request_desk` — card + **blocking wait** until desk `running` / refusal (like the vault);
  - `vm_terminal_exec` / `vm_screenshot` — if the desk is absent, they request the desktop and **wait** too (then retry).
- VM prerequisite: desk **running** (or **sleeping** → automatic wake). One creation gives the shell and the screen (`capability=screen`). `terminal` is still read as "VM present" for old rows.
- Desk `sleeping`: the VM tools / `POST /desk/wake` wake it; **don't** re-post a `vm_request_desk` card just for that.

## Implementation

- `term_svc.exec_command`: `docker exec … timeout -k 5 <seconds> bash -lc` inside the desk container. The host closes the pipes at the deadline, so a stuck read cannot keep the tool running. The Pi tool aborts its own HTTP call 15s after that deadline if the reply never arrives.
- `GET /bots/:name/desk` exposes `pending_request_id` / `pending_state` for agent polling.

## Pitfalls / non-regressions

- This is **not** the Terminal tab's WebSocket PTY.
- A `timeout` of 300s must end the tool around that mark. Killing only the `docker exec` client leaves the command alive in the VM and the chat on "en cours".
- Don't make `vm_request_desk` return immediately after the card: the agent would carry on for nothing.
- Restart the Pi session after changing `vm.ts`.

## Quick check

```bash
python3 -m pytest tests/test_terminal_exec.py -q
```
