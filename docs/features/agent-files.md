# Agent → bot files (`files_*`)

**Status**: in place  
**Key files**: `pi_extensions/files.ts`, `services/files.py`, `GET|PUT /files/content`, `POST /files/share`, `POST /files/attach`  
**Last updated**: 2026-10-29 (images = inline markdown; attachments = PDF/zip/…)

## User behaviour

- The agent can **list / read / write / mkdir / delete** in `~/shared` (= `~/workspace`) **without** a host shell and **without** a desktop.
- **Images** (png/jpg/webp/gif/svg/bmp): `files_share_image` → markdown `![](/api/v1/bots/…/files/raw?path=…)` **in the text** (thumbnail + lightbox). The host re-injects this markdown if the model forgets it. Inventing external URLs is **forbidden**.
- **PDF, zip, and other non-previewable formats**: `files_attach` → download card on the reply bubble (like user attachments).
- Same volume as the **Files** tab / VM bind-mount.

## Implementation

- `share_image`: validates + returns `{markdown, url}` (no chat write).
- `attach_file`: refuses images (`use_share_image`); attaches `{type:file,…}` to the streaming assistant bubble (or creates one); `ensure_assistant` reuses that bubble.
- `files_share_image` / `files_attach` tool cards hidden.
- Chat: marked + DOMPurify allows `<img>`; thumbnail in the bubble, click → lightbox.

## Pitfalls / non-regressions

- Don't attach images as attachments — inline markdown only.
- Don't request desk/screen to display a workspace file.
- After changing `files.ts`, `MANAGER.stop` the Pi sessions.

## Quick check

```bash
python3 -m pytest tests/test_files.py -q
```
