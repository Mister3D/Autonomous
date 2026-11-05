# Data model (SQLite)

Directory: `$AUTONOMOUS_HOME` (default `~/.autonomous` or `./data` depending on the README).

## Files

```
$AUTONOMOUS_HOME/
  token                 # Bearer, mode 0600
  password.hash         # werkzeug hash (web login)
  vault.key             # 32 bytes, mode 0600 (vault encryption)
  db.sqlite             # SQLite (single schema: migrations/001_schema.sql)
  bots/<name>/
    home/               # bind-mount → /home/autonomous/workspace
    downloads/
    pi/                 # Pi cwd (host) + sessions/
```

## SQLite tables

### bots
```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "name": "demo",
  "label": "Demo",
  "capability": "none",
  "internet": true,
  "auto_sleep": true,
  "tokens_in": 0,
  "tokens_out": 0,
  "status": "idle",
  "model": "ollama/llama3.2",
  "pi_session_id": "autonomous-a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "api_token_hash": null,
  "guard": { "review_every": null, "max_actions": null },
  "desk": null,
  "last_message_at": "2026-10-27T00:00:00+00:00",
  "created_at": "2026-10-27T00:00:00+00:00",
  "updated_at": "2026-10-27T00:00:00+00:00"
}
```

- `id`: **stable UUID** (real identity). Used by `bot_inbox` / `bot_asks` / schedules / webhooks / vault grants & requests. Recreating the same slug → new `id` → no reattachment of zombie mail/grants.
- `name`: **technical slug** (`^[a-z0-9][a-z0-9_-]{0,31}$`) — legacy SQLite PK, URL `/b/<name>/…`, Docker, chat messages. Reusable after deletion.
- `label`: **display name** (capitals / spaces OK). On creation, derived from the entered name; the slug is automatic (or explicit `slug`). See [features/bots-create.md](./features/bots-create.md).
- `api_token_hash`: SHA-256 of the current Pi Bearer `abt_…` (plaintext only in the Pi process env; rotated on each RPC start). Never returned by the HTTP API.

`last_message_at` is computed when listing (`MAX(messages.created_at)`), not a SQLite column. No messages → `null`; the UI then sorts on `created_at`.

Desktop sleep columns: `auto_sleep` (default 1), `desk_last_active_at`. See [features/desk-screen.md](./features/desk-screen.md).

`desk` when present:
```json
{
  "state": "running",
  "container_id": "abc",
  "container_name": "autonomous-a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "image": "autonomous-desktop:latest",
  "vnc_port": 5901,
  "novnc_path": "/novnc/…",
  "created_at": "…",
  "last_error": null
}
```

### messages
```json
{
  "bot": "demo",
  "conversation_id": "main",
  "id": "uuid",
  "role": "user",
  "content": "Bonjour",
  "attachments": [],
  "meta": {},
  "created_at": "…"
}
```

FTS5 index `messages_fts` (chat search): `message_id`, `bot`, `role`, `created_at`, `body`. See [features/chat-search.md](./features/chat-search.md).

### terminal_logs
```json
{
  "bot": "demo",
  "id": "uuid",
  "command": "echo ok",
  "exit_code": 0,
  "output": "ok\n",
  "created_at": "…"
}
```

### jobs
```json
{
  "id": "uuid",
  "bot": "demo",
  "kind": "desk.create",
  "state": "running",
  "progress": 40,
  "log": ["pull image…", "start container…"],
  "error": null,
  "created_at": "…",
  "updated_at": "…"
}
```

### bot_inbox / bot_asks (inter-bot messaging)

Queue to a bot (`tell` | `ask` | `reply`) and request correlation. See [features/botmail.md](./features/botmail.md).

### bot_schedules / bot_webhooks (Events)

- `bot_schedules`: `cron` column = **UTC** expression (API input is converted from the `settings.timezone` time zone, otherwise the host local time). `next_run_at` / `last_run_at` in UTC. `recurring`, `instruction`, `anchor_message_id`, `enabled`. The display converts back to the current time zone.
- `bot_webhooks`: unique `token` (prefer `Authorization: Bearer` on `/api/v1/hooks`; legacy URL `/api/v1/hooks/<token>`), `instruction`, `enabled`.

See [features/events.md](./features/events.md).

### settings
```json
{ "key": "guard.review_every", "value": 100 }
{ "key": "guard.max_actions", "value": 1000 }
{ "key": "agent_backend", "value": "pi" }
{ "key": "desktop_image", "value": "autonomous-desktop:latest" }
{ "key": "timezone", "value": "Europe/Paris" }
```

### vault_entries / vault_grants / vault_requests
**Global** vault. `secret_blob` encrypted; bots only get access after a grant.
See `docs/features/vault.md`.

### memory_entries / memory_proposals
Memory **shared by bots** (facts, not secrets). `tier` = `core` (always in the prompt) or `browse` (tools).  
`bots.memory_access` (default 1) for opt-out. Agent proposals → non-blocking chat card.  
`bots.is_manager` (default 0): orchestrator — **at most one** bot set to 1 (otherwise 409 `manager_exists`) — see [features/manager.md](./features/manager.md).  
See `docs/features/memory.md`.

### approval_requests
Generic approval requests (Accept / Decline). `bot` = UUID. State `pending` → `approved` \| `denied` \| `cancelled`.  
See `docs/features/approval.md`.

### clarify_requests
Structured questions (choices and/or short text). `bot` = UUID. `choices_json`, `allow_text`. State `pending` → `answered` \| `cancelled`.  
See `docs/features/clarify.md`.
