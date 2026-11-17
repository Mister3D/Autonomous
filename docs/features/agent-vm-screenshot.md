# Agent → VM desktop screenshot

**Status**: in place  
**Key files**: `autonomous/services/{screenshot,x11_screenshot_worker,files}.py`, `autonomous/pi_extensions/vm.ts` (`vm_screenshot`), `POST/GET …/screen/screenshot(s)`, `ChatPane`  
**Last updated**: 2026-11-17 (markdown for the user bubble)

## User behaviour

- The agent can capture the screen of the bot's Docker desktop (**without an open UI**).
- `vm_screenshot` with `show_in_chat=true` (default) returns a **markdown image line** (via `files_share_image` on `.autonomous/screenshots/<id>.png`). The agent **must paste** that markdown into the assistant reply so the picture appears in the bubble. The tools-list event is technical only — not a user-facing card.
- The server also folds that markdown into the streaming assistant bubble (`pending_images_md`), same path as `files_share_image`.
- The Pi tool result is **text only** (id/url/path/markdown) — the PNG is **never** pasted into the LLM prompt. Tool meta keeps `screenshot_id` / `screenshot_url` for nesting under the tool row when expanded.
- Pixel localisation / GUI vision → **`vm_ground`** (UI-TARS), not `vm_screenshot`.
- `show_in_chat: false` → silent capture (file only, no markdown).

## Implementation

- **X11 root** capture in the container via ctypes/`libX11` + stdlib PNG.
- Worker copied into `…/home/.autonomous/`, run by `docker exec`.
- Files: `data/bots/<bot>/home/.autonomous/screenshots/<uuid>.png`.
- API:
  - `POST /bots/:name/screen/screenshot` `{ show_in_chat? }` → meta + optional chat event;
  - `GET /bots/:name/screen/screenshots/:id.png` → PNG (auth).
- Chat event: `role=event`, `meta.kind=screenshot`, `meta.url=…` (absorbed into `ToolGroup`).
- After capture, `vm.ts` calls `POST …/files/share` on the screenshot path to build the pasteable markdown.

## Pitfalls / non-regressions

- Desk **running** required.
- Restart the Pi session after updating `vm.ts` (`DELETE …/messages` or stop_all).
- Don't reintroduce `attach_to_model`: the model tends to force it to `true` and saturated the image limit.
- Do not tell the model that `show_in_chat` already shows the image to the user — that made it skip pasting markdown.

## Quick check

```bash
curl -s -H "Authorization: Bearer $(cat data/token)" -X POST \
  http://127.0.0.1:8787/api/v1/bots/<bot>/screen/screenshot \
  -H 'Content-Type: application/json' -d '{"show_in_chat":true}'
```
