# Files (`~/shared`)

**Status**: in place  
**Key files**:
- `frontend/src/components/LibraryPane.vue` (**Files** inspector tab)
- `frontend/src/api.js` (`listFiles`, `uploadFile`, `mkdir`, `moveFile`, `downloadUrl`, `deleteFile`)
- `autonomous/services/files.py`
- `autonomous/api/bots.py` (`/files`, `/files/upload`, `/files/mkdir`, `/files/move`, `/files/download`)
- `autonomous/services/desk.py` (mounts shared + workspace)

**Last updated**: 2026-11-11 (dir sizes, DnD into folders/crumbs, click=download, delete confirm)

## User behaviour

- Inspector: tab renamed **Files** (i18n key `panel.files`).
- UI root = `~/shared` (breadcrumb with folder icon).
- **Icon-only** actions (tooltip): create folder, upload file(s).
- Drag & drop of files onto the panel.
- Folder creation: **inline form** (not `window.prompt` — often blocked → "it doesn't work").
- List: accent-themed folder/file icons; **size** (B / KB / MB / GB) for files **and folders** (recursive total) to the right of the name. Hover the name → **immediate custom tooltip** (same family as avatar / token tip — **no** browser `title`) with the full filename.
- **Click a file** → download (no separate download icon). **Click a folder** → enter it.
- **Delete**: arm → check confirm (same pattern as Manage / Settings), then delete.
- **Drag & drop**:
  - OS files onto the panel, a **folder row**, a breadcrumb crumb (incl. root `~/shared`), or `..` → upload into that directory;
  - an existing library entry onto a folder / crumb / `..` → `POST /files/move` (basename kept).
- Content synced with the VM under `~/shared` (and `~/workspace`, same volume).
- **Live list**: agent/UI writes (`files_write` / mkdir / upload / delete / move) emit SSE `files.changed` → the Files tab reloads quietly (debounced). No interval poll — shell/`vm_terminal_exec` writes that skip the files API are not auto-detected until the next API mutation or manual navigation.
- **Not "inside" the VM**: host bind mount → if the desktop goes to sleep (`docker stop`) or is destroyed, the files **remain**. Only a **desktop reset** (or manual deletion of the host folder) erases them.

## Implementation

- Host root: `data/bots/<bot>/home/` (= former desk "home").
- API paths relative to this root; `shared/` or `~/shared/` prefixes accepted then normalised.
- `files._notify_changed` → `BUS.publish("files.changed", {bot, op, path})`; UI `state.filesFeed` + `LibraryPane` debounce reload.
- Upload: `POST /api/v1/bots/:name/files/upload?path=.` multipart field `file`. The client **must not** set `Content-Type: application/json` on `FormData` (breaks the boundary → opaque `Failed to fetch` / empty body). Snapshot `dataTransfer.files` synchronously on drop; OS drops on a file row upload into the **current** folder (folder rows / crumbs still target that directory).
- Text content (agent): `GET|PUT /api/v1/bots/:name/files/content` — see [`agent-files.md`](./agent-files.md).
- Mkdir: `POST /api/v1/bots/:name/files/mkdir` JSON `{ "path": ".", "name": "dossier" }`.
- Move: `POST /api/v1/bots/:name/files/move` JSON `{ "src": "a.pdf", "dest": "CV" }` — moves into directory `dest`, keeps basename; refuses self/descendant and name clashes.
- Folder `size` = recursive byte sum (capped walk) from `list_dir`.
- New desks: two Docker `Mount`s on the same source → `/home/autonomous/shared` and `/home/autonomous/workspace`.
- Already running VMs: often `ln -sfn /home/autonomous/workspace /home/autonomous/shared`.

## Pitfalls / non-regressions

- Don't reintroduce `window.prompt` / `confirm` for critical UI flows — use arm → check for delete.
- Don't put a redundant download icon next to the row: a normal click on a file downloads.
- Action buttons = icons only (`aria-label` + `title` mandatory).
- File names: `_safe_filename` sanitisation (no `/`, no `..`).
- Internal DnD must not treat the drag as an OS file upload (check `application/x-autonomous-file` first).

## Quick check

1. Files tab → folder+/upload icons visible; folder sizes shown.
2. Create a folder via the inline field → appears in the list **and** in `ls ~/shared` in the container.
3. Click a PDF → download starts; drag it onto another folder / root crumb → moved.
4. Delete → check confirm → gone.

```bash
python3 -m pytest tests/test_files.py -q
```
