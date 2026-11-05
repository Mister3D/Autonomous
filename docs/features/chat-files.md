# Chat file attachments

**Status**: in place  
**Key files**:
- `frontend/src/components/ChatPane.vue` (+ picker, drag & drop, bubbles)
- `frontend/src/api.js` (`uploadChatFile`)
- `autonomous/services/files.py` (`save_chat_upload`)
- `autonomous/services/chat_attachments.py` (normalize + agent prompt)
- `autonomous/api/bots.py` (`POST /bots/:name/chat/files`)

**Last updated**: 2026-10-28 (thumbnail grid + side-by-side cards)

## User behaviour

- Composer **+** button → system file picker (multiple).
- **Drag and drop** onto the conversation area → same attachments.
- Storage: `~/shared/upload/<uuid>/<user_file_name>` (name collision = different UUID).
- In the thread: images (pasted **or** uploaded `.png`/`.jpg`/…) in a **thumbnail grid**; other files as side-by-side **cards** (wrap), not stacked.
- Pasting an **image** (Ctrl+V) remains the vision flow (`chat-attachments/`), distinct from uploaded files.
- The agent receives **absolute paths** (host + VM) — never `~/shared` (Pi runs as the host user, so `~` points to that user's home → ENOENT).

## Implementation

- `POST /api/v1/bots/:name/chat/files` multipart `file` → `{ type, name, path, url, size }`.
- `POST /messages`: `attachments` = mix of image URLs (str) and file objects.
- No cap on the number of attached files; max 4 **pasted** images (vision); files ≤ 50 MB each.

## Pitfalls

- Don't overwrite a file with the same name: always a UUID folder.
- Show `name` in the UI, never just the UUID.
- The **Files** inspector tab remains available via the Manage menu (the composer + no longer opens the panel).

## Quick check

```bash
pytest tests/test_chat.py -q
# UI: + → PDF → Send → white card (PDF icon + name + "PDF"); ls data/bots/<bot>/home/upload/
```
