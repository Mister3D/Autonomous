# Global vault

**Status**: in place  
**Key files**: `autonomous/services/{vault,crypto_box,vault_inject,vnc_type_worker}.py`, `autonomous/api/{vault_routes,bots}.py`, `autonomous/migrations/001_schema.sql`, `autonomous/pi_extensions/vault.ts`, `frontend/src/components/{VaultRequestCard,SettingsModal,ChatPane}.vue`  
**Last updated**: 2026-11-16 (credential cards wait indefinitely; composer queues)

## User behaviour

- A vault **global** to the application (not per bot). Secrets encrypted at rest (`data/vault.key` + SQLite blob).
- By default, **no bot has access** to any entry.
- In **Settings**: list the entries. No add form — the bot asks for a secret in the chat. Deletion is a **bin icon** (accessible label "Delete"), then a check (tooltip « Confirm? »). The first click does not delete. Values are never returned by the list API.
- When the bot needs credentials:
  - the agent **defines the form fields itself** (`request_credentials`) — e.g. only an API key, or login+password, or token+endpoint;
  - a **form card** appears in the chat;
  - the bot goes into **`waiting`** status (UI: "Waiting for your answer…", not the "In progress…" orb) while the tool polls the approval;
  - the user enters / approves / declines → if the Pi session is still alive: `busy` and the run continues; otherwise (session died during the wait): `idle` + `running` tools closed as errors + **auto-resume** (`mark_interrupted_after_wait` → `retry_unprocessed`). A Resume card is only a fallback if auto-retry cannot start;
  - While a request is `pending`, the agent stays blocked with no elapsed-time expiry. Composer messages and attachments still go to the FIFO queue; they do not cancel the form. The user must submit or decline the form, or stop the bot.
  - **"Decline"** while a message is already queued: same `cancelled` + guidance handling (avoids the false "User denied").
  - secret values **never go through the LLM** (redacted result: ok / denied / cancelled+human_redirect / `entry_id` / public keys / names of secret fields).
- The agent **must never** quote a vault secret. Hint + guard-rail:
  - **Exception**: a one-time password, security code, 2FA / OTP, or other short-lived login code that arrived in a mail, SMS, or webhook payload is written in the chat as received. It is not reported via `report_user_secret`, not redacted, and not stored in the vault. Passwords, API keys, long-lived tokens, and anything already in the vault stay hidden. An already open Pi session keeps the previous hint until the next start.
  - stream / persist: secrets **removed**;
  - assistant leak → red card (provider) + **relaunch** to continue the reply without the secret;
  - secret **already in the vault** pasted in the composer → API refusal `secret_disclosure` (never to the LLM), text put back in the input;
  - **new** secret pasted in chat → **`report_user_secret`** tool (without passing the value, **without assistant text**): user message replaced by "This message has been deleted…" (dotted red bubble), **original text put back in the input** (SSE, not in history), "sent to your LLM provider" card, **silent abort**, **Pi stop + scrub of `pi/sessions/*.jsonl`** (otherwise the model keeps the secret in session context).
- Request types:
  - `credential` — free-form form defined by the agent (`fields`);
  - `login` / `secret` — shortcuts with default fields (username+password, or a secret);
  - `access` — authorise access to an entry already in the vault.

### Example agent fields

```json
{
  "kind": "credential",
  "label": "OpenAI",
  "fields": [
    {"id": "api_key", "label": "Clé API", "secret": true, "required": true}
  ]
}
```

```json
{
  "kind": "credential",
  "label": "GitHub",
  "origin": "https://github.com",
  "fields": [
    {"id": "username", "label": "Email", "secret": false, "required": true},
    {"id": "password", "label": "Mot de passe", "secret": true, "required": true}
  ]
}
```

## Implementation

- Tables: `vault_entries`, `vault_grants`, `vault_requests` (+ `fields_json` / `public_json` in schema).
- `vault_grants.bot` / `vault_requests.bot` = **`bots.id` (UUID)** (not the slug) — a bot recreated under the same name does not inherit the grants.
- Stdlib encryption: `crypto_box.encrypt/decrypt` (HMAC-SHA256 + SHA-256 keystream).
- HTTP API under `/api/v1/vault/…`; `POST /requests` accepts `fields`; `POST …/resolve` accepts `values` (and legacy `username`/`secret`).
- Pi extension: main tool `request_credentials`; aliases `request_login` / `request_secret`; `vault_catalog` / `vault_granted` / `request_vault_access`; **`vault_type`** (injects a secret field into the focused desktop window).
- Vault system hint via `--append-system-prompt`.
- **Identifier**: `vault_catalog` AND `vault_granted` show `(user: …)` (real case: without it the bot didn't know the e-mail, typed the secret into the identifier field and "invented an account"). `vault_type` = secret only; the username is typed with `vm_type`.

### Desktop injection (`vault_type` / `POST …/vault/inject`)

- Prerequisites: bot grant + desk **running** + target window **focused** (e.g. terminal).
- **Focus guard-rail**: if Chrome has focus and the active element is not editable (`browser focus_info`), the injection is **refused** (nothing is typed, explicit error message). Cross-origin iframe, terminal or unreachable CDP → not blocked. Field aliases: `password`/`pass`/`pwd`… → the entry's single secret.
- Host decrypts → `docker exec -i` → local RFB worker (`127.0.0.1:5901`, stdin = cleartext, **never argv**).
- `method=type`: key-by-key typing; `method=paste`: `ClientCutText` + Ctrl+Shift+V.
- API / tool response: `{ok, entry_id, field, method, chars, secret_returned:false}` — **no** clear value.

## Pitfalls / non-regressions

- Never put the secret in chat `content`, tool `result_json`, or Pi replies. A temporary code from a mail is not a vault needle: scrub only removes values stored in the vault.
- No add form in Settings. The entry comes through the chat card (`request_credentials` / login / secret). The list and the bin remain.
- Don't delete a vault entry on the first click of the bin, and don't use `window.confirm`. Arm → check, same as Files.
- `report_user_secret`: the agent must **not** write "I'm calling the tool…" — hint + `hidden_prompt` masking of the turn's assistant bubbles.
- Abort after report = `mark_silent_abort`: no `⚠️ This operation was aborted`; `restore_text` only via SSE to the composer.
- Pi scrub: `MANAGER.stop` then `scrub_pi_session_files` (user message + known `mot de passe:` / vault fragments). The provider has already seen the secret; we just no longer **keep** it in the session.
- If the model invents a password (e.g. from a "raclette" memory) that is **not** in the vault, neither scrub nor steer applies — the system hint remains mandatory.
- The relaunch must **never** send the secret value back to the model; it must **finish the useful task** without being patronising.
- `POST /bots/:name/messages` + vault secret → 400 `secret_disclosure` **before** insert.
- Don't allow a chat message to cancel a vault form. Queue it instead and keep the agent waiting for the form.
- Push / approval on another device ≠ OTP: the agent must not open a code form; if it did, the user's message + `human_redirect` corrects course.
- `fields[].id`: `^[a-z][a-z0-9_]{0,31}$`; at least one `secret: true` field.
- `GET /vault/entries` without `?bot=` = admin; with `?bot=` = grants only.
- After changing the TS extension: restart the bot's Pi session.
- RFB ServerInit handshake = **20** bytes before `name-length` (not 24).
- Targeted browser injection (CDP fill) = later step; for now generic keyboard/clipboard.

## Quick check

```bash
python3 -m pytest tests/test_vault.py tests/test_vault_inject.py -q
# Prompt: temporary mail/SMS/webhook codes are shown; vault secrets stay hidden.
# An already open Pi session keeps the old hint until that bot's Pi restarts.

curl -s -b cookies -X POST http://127.0.0.1:8787/api/v1/vault/requests \
  -H 'Content-Type: application/json' \
  -d '{"bot":"demo","kind":"credential","label":"OpenAI","fields":[{"id":"api_key","label":"Clé API","secret":true}]}'

# Inject (desk running + focused window) — the response never contains the secret:
curl -s -b cookies -X POST http://127.0.0.1:8787/api/v1/bots/<bot>/vault/inject \
  -H 'Content-Type: application/json' \
  -d '{"entry_id":"<id>","field":"password","method":"type"}'
```
