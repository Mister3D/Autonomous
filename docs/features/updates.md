# Self-update (git channel)

**Status**: in place  
**Key files**: `autonomous/services/updates.py`, `autonomous/api/setup_routes.py` (`/setup/update*`), `frontend/src/components/SetupPanel.vue`, Settings → General  
**Last updated**: 2026-11-06 (auto-reload after apply; no NetworkError flash)

## User behaviour

- Update status is shown on the ready home (`/` tagline, under the setup link) **and** at the bottom of the incomplete setup checklist (`/setup` or home while required items are missing), so you can apply an update before finishing config. Quiet “Up to date · channel · Check” when current; a compact callout with **Update** only when behind (or fetch/dirty/apply in progress). Hidden if the install is not a git checkout.
- **Check** forces a remote check (otherwise results are cached **24 h** under `$AUTONOMOUS_HOME/update-check.json`).
- **Update** fast-forwards to `<remote>/<branch>`, runs `npm ci` + `npm run build` in `frontend/`, `pip install -e .` in the venv, then **restarts** `autonomous.service` via `systemctl` when a unit is active (delayed ~2 s). Manual restart if no unit.
- Settings → General → **Updates**:
  - **Repository URL** (optional): empty keeps `origin`; a fork URL configures a dedicated git remote named `updates`. Only `https://`, `ssh://`, or `git@…` — applying an update from that remote runs `npm`/`pip` and may restart the service (**code execution**).
  - **Branch**: presets Stable (`main`) / Pre-release (`dev`) / Custom (any valid branch name). Leaving `main` asks for confirmation. Returning to `main` is refused when the DB has migration versions absent from that branch (`migrations_ahead`).

## Implementation

- Setting keys: `update.channel` (branch name), `update.remote_url` (optional). Changing either via generic `PUT /settings` is rejected — use `PUT /setup/update`.
- Fetch/apply use remote `updates` when `update.remote_url` is set, otherwise `origin`.
- Apply is a background job (`setup.self_update` on bot `_setup`); working tree must be clean; no user-supplied shell.
- Restart tries `systemctl`, `systemctl --user`, then `sudo -n systemctl` for the first active unit among `AUTONOMOUS_SERVICE_NAME`, `autonomous.service`, `autonomous`.

## Pitfalls / non-regressions

- Do not hide the update UI behind `setup.ready` — operators on a fresh install must be able to pull before LLM/desk are configured.
- Dirty tree → apply returns 400 `dirty`; banner explains it.
- Non-git installs (no `.git`) → UI shows unavailable; no fake update path.
- Do not allow channel / remote_url flips through `set_many` without the migration / confirm guards.
- After apply, expect the HTTP process to die if systemd restart succeeds — the job log may truncate. The UI must **not** show `NetworkError`: on job `done` (or a fetch drop while applying), poll `/api/v1/health` then `location.reload()`.
- Branch names are validated (`[A-Za-z0-9._/-]`, no `..`); remote URLs must be `https://` / `ssh://` / `git@…` (`http://` and `git://` rejected).
- Do not point `update.remote_url` at a repo you do not control.

## Quick check

`GET /api/v1/setup/update` → `{ channel, remote_url, origin_url, available, behind, cached, … }`.  
`POST /api/v1/setup/update/check` forces refresh.  
`PUT /api/v1/setup/update` with `{ "channel": "dev", "confirm_dev": true }` and/or `{ "remote_url": "https://github.com/you/Autonomous.git" }` (empty string clears the custom remote).
