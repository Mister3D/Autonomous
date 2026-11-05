# Auth secrets (session vs Bearer)

**Status**: in place  
**Key files**: `autonomous/auth.py`, `autonomous/app.py`, `autonomous/services/client_ip.py`, `autonomous/wsproxy.py`, `autonomous/services/grounding.py`  
**Last updated**: 2026-11-05

## User behaviour

- `autonomous init` writes **`data/token`** (admin API Bearer) and **`data/secret`** (Flask cookie signing key). They are never the same value.
- Login rate limits / webhook / pairing use the TCP peer IP by default. Behind a reverse proxy that overwrites `X-Forwarded-For`, set **`AUTONOMOUS_TRUST_PROXY=1`**.
- Companion WebSocket upgrades are refused with **401** if the `adc_…` Bearer is missing or invalid — **before** the HTTP 101.
- Grounding API keys come only from Settings / `grounder.env` / `AUTONOMOUS_GROUNDER_TOKEN` (not a bare `TOKEN` file).

## Implementation

- `ensure_session_secret()` creates `data/secret` on first serve if missing (existing installs get a new cookie key once → re-login).
- `AUTONOMOUS_SECRET` overrides the session key only; equal to `data/token` → serve refuses to start.
- `client_ip(request)` centralizes XFF handling for login, hooks, pairing.

## Pitfalls / non-regressions

- Do not fall back `SECRET_KEY` to `data/token`.
- Do not trust XFF without `AUTONOMOUS_TRUST_PROXY=1`.
- Do not send HTTP 101 on `/ws/companion` before `device_from_token`.

## Quick check

```bash
pytest tests/test_security_fixes.py tests/test_security_hardening.py -q
```
