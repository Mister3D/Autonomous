# Agent → VM desktop screenshot

**Status**: in place  
**Key files**: `autonomous/services/{screenshot,x11_screenshot_worker}.py`, `autonomous/pi_extensions/vm.ts` (`vm_screenshot`), `POST/GET …/screen/screenshot(s)`, `ChatPane`  
**Last updated**: 2026-10-29 (capture under the tool, no "Screenshot" line)

## User behaviour

- The agent can capture the screen of the bot's Docker desktop (**without an open UI**).
- By default a chat event `kind=screenshot` is created, **absorbed** into the run's `ToolGroup`: **no** standalone card / image line. The user sees the image by **expanding** the `vm_screenshot` tool line.
- The Pi tool result is **text only** (id/url) — the PNG is **never** pasted into the LLM prompt (some providers accept max ~2 images/prompt). Tool meta enriched with `screenshot_id` / `screenshot_url` to link the image.
- Pixel localisation / GUI vision → **`vm_ground`** (UI-TARS), not `vm_screenshot`.
- `show_in_chat: false` → silent capture (file only).

## Implementation

- **X11 root** capture in the container via ctypes/`libX11` + stdlib PNG.
- Worker copied into `…/home/.autonomous/`, run by `docker exec`.
- Files: `data/bots/<bot>/home/.autonomous/screenshots/<uuid>.png`.
- API:
  - `POST /bots/:name/screen/screenshot` `{ show_in_chat? }` → meta + optional chat message;
  - `GET /bots/:name/screen/screenshots/:id.png` → PNG (auth).
- Chat message: `role=event`, `meta.kind=screenshot`, `meta.url=…`.

## Pitfalls / non-regressions

- Desk **running** required.
- Restart the Pi session after updating `vm.ts` (`DELETE …/messages` or stop_all).
- Don't reintroduce `attach_to_model`: the model tends to force it to `true` and saturated the image limit.

## Quick check

```bash
curl -s -H "Authorization: Bearer $(cat data/token)" -X POST \
  http://127.0.0.1:8787/api/v1/bots/<bot>/screen/screenshot \
  -H 'Content-Type: application/json' -d '{"show_in_chat":true}'
```
