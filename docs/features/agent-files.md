# Agent → bot files (`files_*`)

**Status**: in place  
**Key files**: `pi_extensions/files.ts`, `services/files.py`, `GET|PUT /files/content`, `POST /files/share`, `POST /files/attach`, `POST /files/claim-mail`  
**Last updated**: 2026-11-12 (`~/files` is private to the bot; `~/shared` is a legacy alias)

## User behaviour

- The agent can **list / read / write / mkdir / delete** in `~/files` (= `~/workspace`, private to this bot) **without** a host shell and **without** a desktop. Other bots cannot see this folder. The prompt forbids using `~/shared`.
- **Images** (png/jpg/webp/gif/svg/bmp): `files_share_image` → markdown `![](/api/v1/bots/…/files/raw?path=…)` **in the text** (thumbnail + lightbox). The host re-injects this markdown if the model forgets it. Inventing external URLs is **forbidden**.
- **PDF, zip, and other non-previewable formats**: `files_attach` → download card on the reply bubble (like user attachments).
- **Inter-bot mail files**: peer attachments land under `.autonomous/mail-inbox/<inbox_id>/`. Use **`files_claim_mail(path, dest)`** to move them to a chosen path under `~/files` (recipient decides). See [botmail.md](./botmail.md). There is no directory shared between bots.
- Same volume as the **Files** tab / VM bind-mount.

## Implementation

- `share_image`: validates + returns `{markdown, url}` (no chat write).
- `attach_file`: refuses images (`use_share_image`); attaches `{type:file,…}` to the streaming assistant bubble (or creates one); `ensure_assistant` reuses that bubble.
- `stage_mail_attachments` / `claim_mail_attachment` in `files.py` (copy then move; path-traversal safe).
- `files_share_image` / `files_attach` / `files_claim_mail` tool cards hidden.
- Mutating tools (`files_write` / `files_mkdir` / `files_delete` / uploads / claim-mail) publish `files.changed` so the Files inspector updates without a manual refresh (see [files-shared.md](./files-shared.md)).
- Chat: marked + DOMPurify allows `<img>`; thumbnail in the bubble, click → lightbox.

## Pitfalls / non-regressions

- Don't attach images as attachments — inline markdown only.
- Don't request desk/screen to display a workspace file.
- Don't auto-place mail attachments outside staging — claim is explicit.
- After changing `files.ts`, `MANAGER.stop` the Pi sessions.

## Quick check

```bash
python3 -m pytest tests/test_files.py tests/test_botmail.py -q
```
