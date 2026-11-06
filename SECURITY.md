# Security

Autonomous is a **mono-user local hub**. The default threat model is: one trusted operator on `127.0.0.1`, untrusted desk VMs, and optional companions on the user's PCs. It is **not** a multi-tenant SaaS. Exposing the raw HTTP port on the internet without a reverse proxy and TLS is unsupported.

## Do not commit

These live under `$AUTONOMOUS_HOME` (default `./data/`) and must stay **out of git**:

| Path | What |
|------|------|
| `data/token` | Admin API Bearer (`autonomous init`) — not used to sign cookies |
| `data/secret` | Flask session signing key (distinct from `token`) |
| `data/password.hash` | Web login password hash |
| `data/vault.key` | Vault encryption key |
| `data/db.sqlite` | Bots, chat, grants, schedules |
| `data/bots/` | Per-bot Pi sessions + VM home volumes |
| `data/grounder.env` | Grounding URL / token (mode 600) |
| `data/initial-password` | One-shot generated password from `install.sh` (deleted on first login) |
| `data/password.must_change` | Flag: web UI forces a password change before the hub unlocks |

Also never commit ad-hoc copies such as a root-level `TOKEN` / `db.sqlite` / `*.sqlite` file, `.env`, or provider API keys.

## Reporting

If you discover a vulnerability in Autonomous, open a **private** GitHub Security Advisory on [Mister3D/Autonomous](https://github.com/Mister3D/Autonomous) before public disclosure. Do not file a public issue with exploit details.

## License note

Autonomous is **AGPL-3.0-only**. Network deployment of a *modified* version requires offering the corresponding source to the users of that service (see [LICENSE](LICENSE) and [NOTICE](NOTICE)).

## Threat model (self-host)

| Surface | Default | Notes |
|---------|---------|--------|
| HTTP API | Session cookie (signed with `data/secret`) or admin Bearer (`data/token`) | Login rate-limited (10 / 5 min / IP); Bearer ≠ session key |
| Pi agent HTTP | Bot Bearer `abt_…` | Rotated per Pi RPC start; hash in `bots.api_token_hash`; scoped to that bot + agent allowlist (not admin) |
| WebSockets VNC / terminal | Session cookie or **admin** Bearer | Bot tokens are rejected; unauthenticated upgrades are rejected |
| Companion WebSocket | Device token `adc_…` | Validated before HTTP 101; scoped; cannot call admin API |
| Public webhooks | `POST /api/v1/hooks` + `Authorization: Bearer` | Token not in the URL; GET rejected; rate-limited (30 / min / token, 60 / min / IP); treat the token as a secret |
| Companion SOCKS / DNS | Bound `0.0.0.0` (iptables REDIRECT) | Only loopback + desk IPs of bots assigned to that companion with egress |
| Self-update remote | Optional `update.remote_url` | `git fetch` + `npm`/`pip` + service restart — **treat as code execution**. Only a fork **you** control; `https://` / `ssh://` / `git@` only (`http://` and `git://` rejected) |
| LLM / grounding URLs | Admin Settings + NL search | Cloud metadata / link-local blocked at save **and** runtime (incl. chat NL search); redirects re-checked. LAN/localhost allowed for self-hosted endpoints |
| Desk VMs | Untrusted | Prefer Internet off; `seccomp=unconfined` for Chrome — assume escape possible |
| Host bash (Pi `bash` tool) | **Removed** | Always `--exclude-tools bash`; shell only inside desk VMs. Host access = credentials via vault if needed |
| OpenAPI `/api/docs` | Auth required | Session / admin Bearer only |
| Vault at rest | HMAC + SHA-256 keystream (stdlib) | Mono-user local; not a HSM / multi-tenant KMS |

## Operational tips

- Bind `serve` to **`127.0.0.1`** (default). Non-loopback binds require `AUTONOMOUS_BIND_PUBLIC=1` and should sit behind TLS.
- Set `AUTONOMOUS_COOKIE_SECURE=1` (or `AUTONOMOUS_PUBLIC_URL=https://…`) when the UI is served over HTTPS.
- Run `autonomous init` before `serve`. Without `data/token`, serve refuses to start (`AUTONOMOUS_ALLOW_INSECURE=1` only for throwaway local experiments). Session key is `data/secret` (or `AUTONOMOUS_SECRET`), never the API Bearer.
- Grounding keys come from Settings / `grounder.env` / `AUTONOMOUS_GROUNDER_TOKEN` — never a bare `TOKEN` file (that often held the admin Bearer).
- Treat desk VMs as untrusted: prefer Internet off when not needed. Pi has no host bash — only VM shells.
- Webhook tokens are capabilities: prefer Bearer header invokes (avoids token-in-URL proxy logs); do not paste tokens into public chats; rotate by deleting and recreating the webhook.
- Rotate `data/token` / `data/secret` / vault key / login password if they may have leaked (chat logs, agent handoff files, screenshots). Restarting a bot's Pi session rotates its `abt_…` token automatically.
- Non-interactive `install.sh` writes a generated password + `password.must_change`: the first web login deletes `initial-password` and blocks the API until `POST /auth/password` sets a new one. The same endpoint is available later from Settings → General to rotate the login password.
- `curl \| sh` installers inherit supply-chain risk: prefer cloning the repo and reading `install.sh` when you can.
- Companion pairing is public but rate-limited (`pair` + `pair-poll`); disable new pairing in Settings → Companions when unused. Only approve codes you initiated on your own PC.
- Custom update repository URL: empty keeps `origin`. A wrong or hostile remote can replace the installed code on apply — same trust as cloning that repo yourself.

## Reverse proxy checklist

1. Terminate TLS at the proxy; set `AUTONOMOUS_PUBLIC_URL=https://…` and `AUTONOMOUS_COOKIE_SECURE=1`.
2. Proxy WebSocket upgrades for `/novnc/`, `/ws/terminal/`, `/ws/companion`.
3. Keep `serve` on localhost; do not publish Docker VNC ports.
4. Set `AUTONOMOUS_TRUST_PROXY=1` only when the proxy **overwrites** `X-Forwarded-For` (rate limits use it then). Without this flag, XFF is ignored.
