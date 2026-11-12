# Self-update (git channel)

**Status**: in place  
**Key files**: `autonomous/services/updates.py`, `autonomous/api/setup_routes.py` (`/setup/update*`), `frontend/src/components/SetupPanel.vue`, Settings → General  
**Last updated**: 2026-11-13 (home row shows version, refresh icon, pill; force update still resets to the remote tip)

## User behaviour

- On the ready home (`/` tagline), the status card row reads `Autonomous - {branch} - {version}` with a refresh icon and a green **Up to date** pill. When the remote tip’s `__version__` is newer, the row adds `→ {latest}` and **Update** replaces the pill. A dirty or diverged tree shows **Force** on that row. Hidden if the install is not a git checkout. `GET /setup/update` includes `version` and `latest_version`.
- The same update card stays at the bottom of the incomplete setup checklist (`/setup`, or home while required items are missing), so you can apply an update before finishing config.
- **Check** forces a remote check (otherwise results are cached **24 h** under `$AUTONOMOUS_HOME/update-check.json`). The home line also keeps that result in the browser (`localStorage`) for the same 24 h, so a page load does not call `/setup/update` again and the line does not pop in late. Changing the branch or the remote URL drops that copy. After an apply, it is dropped so the restarted page checks once.
- **Update** fast-forwards to `<remote>/<branch>`, runs `npm ci` + `npm run build` in `frontend/`, `pip install -e .` in the venv, then **restarts** `autonomous.service` via `systemctl` when a unit is active (delayed ~2 s). Manual restart if no unit.
- **Force** (home card, next to a dirty or diverged state, including the “local changes” error) and **Force update** (Settings → General → Updates) do the same rebuild, but first discard local commits and tracked edits (`git checkout -f -B <branch> <remote>/<branch>`) and untracked files (`git clean -fd`, ignored paths such as `data/` and `.venv` stay). Use it when a fast-forward cannot apply — a dirty tree, or a rewritten local commit.
- Settings → General → **Updates**:
  - **Repository URL** (optional): empty keeps `origin`; a fork URL configures a dedicated git remote named `updates`. Only `https://`, `ssh://`, or `git@…` — applying an update from that remote runs `npm`/`pip` and may restart the service (**code execution**).
  - **Branch**: presets Stable (`main`) / Pre-release (`dev`) / Custom (any valid branch name). Leaving `main` asks for confirmation. Returning to `main` is refused when the DB has migration versions absent from that branch (`migrations_ahead`).

## Implementation

- Setting keys: `update.channel` (branch name), `update.remote_url` (optional). Changing either via generic `PUT /settings` is rejected — use `PUT /setup/update`.
- Fetch/apply use remote `updates` when `update.remote_url` is set, otherwise `origin`.
- Apply is a background job (`setup.self_update` on bot `_setup`). A normal apply requires a clean tree and a fast-forward. `POST /setup/update/apply` with `{ "force": true }` skips that and resets to the remote tip. No user-supplied shell.
- Restart tries `systemctl`, `systemctl --user`, then `sudo -n systemctl` for the first active unit among `AUTONOMOUS_SERVICE_NAME`, `autonomous.service`, `autonomous`.

## Pitfalls / non-regressions

- Do not hide the update UI behind `setup.ready` — operators on a fresh install must be able to pull before LLM/desk are configured.
- Dirty tree → a normal apply returns 400 `dirty`; the home card explains it and offers **Force**.
- Non-git installs (no `.git`) → UI shows unavailable; no fake update path.
- Do not allow channel / remote_url flips through `set_many` without the migration / confirm guards.
- After apply, expect the HTTP process to die if systemd restart succeeds — the job log may truncate. The UI must **not** show `NetworkError`: on job `done` (or a fetch drop while applying), poll `/api/v1/health` then `location.reload()`.
- Branch names are validated (`[A-Za-z0-9._/-]`, no `..`); remote URLs must be `https://` / `ssh://` / `git@…` (`http://` and `git://` rejected).
- Do not point `update.remote_url` at a repo you do not control.

## Quick check

`GET /api/v1/setup/update` → `{ channel, version, latest_version, remote_url, origin_url, available, behind, cached, … }`.  
`POST /api/v1/setup/update/check` forces refresh.  
`PUT /api/v1/setup/update` with `{ "channel": "dev", "confirm_dev": true }` and/or `{ "remote_url": "https://github.com/you/Autonomous.git" }` (empty string clears the custom remote).
