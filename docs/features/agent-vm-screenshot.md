# Agent → VM desktop screenshot

**Status**: in place  
**Key files**: `autonomous/services/{screenshot,x11_screenshot_worker,files,agent}.py`, `autonomous/pi_extensions/vm.ts` (`vm_screenshot`), `POST/GET …/screen/screenshot(s)`, `ToolGroup.vue`  
**Last updated**: 2026-11-18 (tool-row only — no assistant-bubble auto-embed)

## User behaviour

- The agent can capture the screen of the bot's Docker desktop (**without an open UI**).
- `vm_screenshot` with `show_in_chat=true` (default): the PNG lives in the **tool group** (`screenshot_id` / `screenshot_url` on tool meta). When the group is folded, a preview of the latest user-facing capture sits under the summary bar; when the list is open, it is nested under the `vm_screenshot` row.
- The host does **not** inject screenshot markdown into an assistant bubble (`pending_images_md` is only for `files_share_image` / MCP images). The model must **not** paste desk-capture markdown into the bubble either (duplicates the picture).
- The Pi tool result is **text only** (id/url/path + guidance) — the PNG is **never** pasted into the LLM prompt.
- Pixel localisation / GUI vision → **`vm_ground`** (UI-TARS), not `vm_screenshot`.
- `show_in_chat: false` → silent capture (file only, no tool-row preview).

## Implementation

- **X11 root** capture in the container via ctypes/`libX11` + stdlib PNG.
- Worker copied into `…/home/.autonomous/`, run by `docker exec`.
- Files: `data/bots/<bot>/home/.autonomous/screenshots/<uuid>.png`.
- API:
  - `POST /bots/:name/screen/screenshot` `{ show_in_chat? }` → meta + optional chat event;
  - `GET /bots/:name/screen/screenshots/:id.png` → PNG (auth).
- Chat event: `role=event`, `meta.kind=screenshot`, `meta.url=…` (absorbed into `ToolGroup`).
- `vm.ts` may still call `POST …/files/share` for an internal markdown line kept in tool details — not for bubble paste.
- `agent.py` on `tool_execution_end`: auto-embed only `files_share_image` (+ MCP images), never `vm_screenshot`.

## Pitfalls / non-regressions

- Desk **running** required.
- Restart the Pi session after updating `vm.ts` (`DELETE …/messages` or stop_all).
- Don't reintroduce `attach_to_model`: the model tends to force it to `true` and saturated the image limit.
- Do not re-enable host auto-embed of `vm_screenshot` into assistant bubbles — the tool row is the product surface.

## Quick check

```bash
curl -s -H "Authorization: Bearer $(cat data/token)" -X POST \
  http://127.0.0.1:8787/api/v1/bots/<bot>/screen/screenshot \
  -H 'Content-Type: application/json' -d '{"show_in_chat":true}'
```
