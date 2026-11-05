# Auth secrets (session vs Bearer)

**Status**: in place  
**Key files**: `autonomous/auth.py`, `autonomous/api/auth_routes.py`, `autonomous/app.py`, `autonomous/services/client_ip.py`, `autonomous/wsproxy.py`, `autonomous/services/grounding.py`, `frontend/src/views/LoginView.vue`, `install.sh`  
**Last updated**: 2026-11-06 (grounding SSRF aligned + redirect re-check)

## User behaviour

- `autonomous init` writes **`data/token`** (admin API Bearer) and **`data/secret`** (Flask cookie signing key). They are never the same value.
- Login rate limits / webhook / pairing use the TCP peer IP by default. Behind a reverse proxy that overwrites `X-Forwarded-For`, set **`AUTONOMOUS_TRUST_PROXY=1`**.
- Companion WebSocket upgrades are refused with **401** if the `adc_…` Bearer is missing or invalid — **before** the HTTP 101.
- Grounding API keys come only from Settings / `grounder.env` / `AUTONOMOUS_GROUNDER_TOKEN` (not a bare `TOKEN` file).
- Settings → Companions can disable new pairing. Saving an LLM or grounding `*_url` runs the same SSRF checks as runtime calls (metadata / link-local blocked; LAN/localhost allowed). HTTP clients re-validate each redirect hop (`urlopen_safe`).
- Non-interactive install (generated password): first web login deletes `data/initial-password`, keeps `data/password.must_change`, and the UI/API stay locked until `POST /auth/password` with a new password (≥ 8 chars, different from the current one). Admin Bearer and bot `abt_…` tokens are not gated.

## Implementation

- `ensure_session_secret()` creates `data/secret` on first serve if missing (existing installs get a new cookie key once → re-login).
- `AUTONOMOUS_SECRET` overrides the session key only; equal to `data/token` → serve refuses to start.
- `client_ip(request)` centralizes XFF handling for login, hooks, pairing.
- `init --must-change-password` (used by `install.sh` when it generated the password) creates `password.must_change`. Presence of `initial-password` alone also counts as must-change.
- Session flag `must_change_password`; gate in `app._auth_gate` → 403 `password_change_required`. VNC/terminal WS reject that session until unlocked.

## Pitfalls / non-regressions

- Do not fall back `SECRET_KEY` to `data/token`.
- Do not trust XFF without `AUTONOMOUS_TRUST_PROXY=1`.
- Do not send HTTP 101 on `/ws/companion` before `device_from_token`.
- Do not leave `initial-password` on disk after a successful login.

## Quick check

```bash
pytest tests/test_security_fixes.py tests/test_security_hardening.py tests/test_forced_password_change.py tests/test_updates.py tests/test_setup.py -q
```
