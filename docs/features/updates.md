# Self-update (git channel)

**Status**: in place  
**Key files**: `autonomous/services/updates.py`, `autonomous/api/setup_routes.py` (`/setup/update*`), `frontend/src/components/SetupPanel.vue`, Settings → Agent  
**Last updated**: 2026-11-05

## User behaviour

- On the ready home (`/` tagline), update status sits under the setup link: quiet “Up to date · channel · Check” when current; a compact callout with **Update** only when behind (or fetch/dirty/apply in progress). Hidden if the install is not a git checkout.
- **Check** forces a remote check (otherwise results are cached **24 h** under `~/.autonomous/update-check.json`).
- **Update** fast-forwards to `origin/<channel>`, runs `npm ci` + `npm run build` in `frontend/`, `pip install -e .` in the venv, then **restarts** `autonomous.service` via `systemctl` when a unit is active (delayed ~2 s). Manual restart if no unit.
- Settings → Agent → **Channel**: `main` (stable) or `dev` (pre-release). Switching **to** `dev` requires a confirm dialog (`confirm_dev=true` on the API). Switching **back to** `main` is refused when the DB has migration versions absent from that branch (`migrations_ahead`).

## Implementation

- Setting key: `update.channel` (default `main`). Changing it via generic `PUT /settings` is rejected — use `PUT /setup/update`.
- Apply is a background job (`setup.self_update` on bot `_setup`); working tree must be clean; no user-supplied shell.
- Restart tries `systemctl`, `systemctl --user`, then `sudo -n systemctl` for the first active unit among `AUTONOMOUS_SERVICE_NAME`, `autonomous.service`, `autonomous`.

## Pitfalls / non-regressions

- Dirty tree → apply returns 400 `dirty`; banner explains it.
- Non-git installs (no `.git`) → UI shows unavailable; no fake update path.
- Do not allow channel flips through `set_many` without the migration / confirm_dev guards.
- After apply, expect the HTTP process to die if systemd restart succeeds — the job log may truncate.

## Quick check

`GET /api/v1/setup/update` → `{ channel, available, behind, cached, … }`.  
`POST /api/v1/setup/update/check` forces refresh.  
`PUT /api/v1/setup/update` with `{ "channel": "dev", "confirm_dev": true }`.
