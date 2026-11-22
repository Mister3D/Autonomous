# Agent → VM desktop screenshot

**Status**: in place  
**Key files**: `autonomous/services/{screenshot,x11_screenshot_worker,files,agent}.py`, `autonomous/pi_extensions/vm.ts` (`vm_screenshot`), `POST/GET …/screen/screenshot(s)`, `ToolGroup.vue`  
**Last updated**: 2026-11-19 (bot pastes capture markdown into its reply — no host auto-embed)

## User behaviour

- The agent can capture the screen of the bot's Docker desktop (**without an open UI**).
- `vm_screenshot` with `show_in_chat=true` (default): the tool result includes **image markdown** (via `files/share`). The **model** pastes that markdown into its assistant reply wherever it wants the picture — same idea as `files_share_image`. The host does **not** inject it (`pending_images_md` stays for `files_share_image` / MCP only).
- A tool-group event / nested preview may still exist for history; the product surface for the user is the **assistant bubble** after the bot pastes. The agent must **not** tell the user to open the tool row.
- The Pi tool result text is guidance + id/url/path + markdown — the PNG bytes are **never** pasted into the LLM prompt.
- Pixel localisation / GUI vision → **`vm_ground`** (UI-TARS), not `vm_screenshot`.
- `show_in_chat: false` → silent capture (file only, no reply markdown).

## Implementation

- **X11 root** capture in the container via ctypes/`libX11` + stdlib PNG.
- Worker copied into `…/home/.autonomous/`, run by `docker exec`.
- Files: `data/bots/<bot>/home/.autonomous/screenshots/<uuid>.png`.
- API:
  - `POST /bots/:name/screen/screenshot` `{ show_in_chat? }` → meta + optional chat event;
  - `GET /bots/:name/screen/screenshots/:id.png` → PNG (auth).
- Chat event: `role=event`, `meta.kind=screenshot`, `meta.url=…` (absorbed into `ToolGroup`).
- `vm.ts` calls `POST …/files/share` when `show_in_chat` and returns the markdown for the model to paste.
- `agent.py` on `tool_execution_end`: auto-embed only `files_share_image` (+ MCP images), **never** `vm_screenshot` — desk captures are the bot’s choice in its reply text.
- Pi hints (`_VM_SYSTEM_HINT` + tool description) tell the model to paste the markdown into the assistant bubble.

## Pitfalls / non-regressions

- Desk **running** required.
- Restart the Pi session after updating `vm.ts` / hints (`DELETE …/messages` or stop_all) so the new instructions load.
- Don't reintroduce `attach_to_model`: the model tends to force it to `true` and saturated the image limit.
- Do **not** host-auto-embed `vm_screenshot` into bubbles — the bot chooses where the image sits in its message.

## Quick check

```bash
curl -s -H "Authorization: Bearer $(cat data/token)" -X POST \
  http://127.0.0.1:8787/api/v1/bots/<bot>/screen/screenshot \
  -H 'Content-Type: application/json' -d '{"show_in_chat":true}'
```
