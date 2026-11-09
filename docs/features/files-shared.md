# Files (`~/shared`)

**Status**: in place  
**Key files**:
- `frontend/src/components/LibraryPane.vue` (**Files** inspector tab)
- `frontend/src/api.js` (`listFiles`, `uploadFile`, `mkdir`, `downloadUrl`, `deleteFile`)
- `autonomous/services/files.py`
- `autonomous/api/bots.py` (`/files`, `/files/upload`, `/files/mkdir`, `/files/download`)
- `autonomous/services/desk.py` (mounts shared + workspace)

**Last updated**: 2026-11-09 (live Files refresh via `files.changed` only — no poll)

## User behaviour

- Inspector: tab renamed **Files** (i18n key `panel.files`).
- UI root = `~/shared` (breadcrumb with folder icon).
- **Icon-only** actions (tooltip): create folder, upload file(s).
- Drag & drop of files onto the panel.
- Folder creation: **inline form** (not `window.prompt` — often blocked → "it doesn't work").
- List: accent-themed folder/file icons; download / delete as icons on hover.
- Content synced with the VM under `~/shared` (and `~/workspace`, same volume).
- **Live list**: agent/UI writes (`files_write` / mkdir / upload / delete) emit SSE `files.changed` → the Files tab reloads quietly (debounced). No interval poll — shell/`vm_terminal_exec` writes that skip the files API are not auto-detected until the next API mutation or manual navigation.
- **Not "inside" the VM**: host bind mount → if the desktop goes to sleep (`docker stop`) or is destroyed, the files **remain**. Only a **desktop reset** (or manual deletion of the host folder) erases them.

## Implementation

- Host root: `data/bots/<bot>/home/` (= former desk "home").
- API paths relative to this root; `shared/` or `~/shared/` prefixes accepted then normalised.
- `files._notify_changed` → `BUS.publish("files.changed", {bot, op, path})`; UI `state.filesFeed` + `LibraryPane` debounce reload.
- Upload: `POST /api/v1/bots/:name/files/upload?path=.` multipart field `file` (don't force `Content-Type: application/json` on FormData).
- Text content (agent): `GET|PUT /api/v1/bots/:name/files/content` — see [`agent-files.md`](./agent-files.md).
- Mkdir: `POST /api/v1/bots/:name/files/mkdir` JSON `{ "path": ".", "name": "dossier" }`.
- New desks: two Docker `Mount`s on the same source → `/home/autonomous/shared` and `/home/autonomous/workspace`.
- Already running VMs: often `ln -sfn /home/autonomous/workspace /home/autonomous/shared`.

## Pitfalls / non-regressions

- Don't reintroduce `window.prompt` / `confirm` for critical UI flows.
- Action buttons = icons only (`aria-label` + `title` mandatory).
- File names: `_safe_filename` sanitisation (no `/`, no `..`).

## Quick check

1. Files tab → folder+/upload icons visible.
2. Create a folder via the inline field → appears in the list **and** in `ls ~/shared` in the container.
3. Upload / download / delete OK.
