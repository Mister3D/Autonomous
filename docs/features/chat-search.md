# Chat history search

**Status**: in place  
**Key files**: `autonomous/migrations/001_schema.sql`, `autonomous/services/search.py`, `autonomous/api/search_routes.py`, `autonomous/pi_extensions/chat_search.ts`, `frontend/src/views/HubView.vue`  
**Last updated**: 2026-10-31 (rail button = round settings-style)

## User behaviour

- **Search** icon in the rail: round white bordered button, same size as the settings menu (40px). Always filters **bots**, and also searches **messages** (all bots).
- Input (≥ 2 characters) → message results (excerpt + bot + role); **Enter** forces sentence mode.
- Click on a hit → opens `/b/<bot>/discussion?msg=<id>` (scroll + flash, like mentions).
- **auto** mode:
  - short keyword (`raclette`) → exact FTS (AND);
  - **sentence / question** → LLM: meaning expansion → FTS/recent candidates → the LLM keeps only truly relevant messages (not just word overlap).

## Implementation

- FTS5 index `messages_fts` (body + UNINDEXED metadata). Synced on `create_message` / `send_message` / `update_message`; purged on `clear_messages`; backfilled once at startup (`ensure_fts`).
- Indexed roles: `user` / `assistant` / `system`. Excluded: `hidden_prompt`, `queued`, tool events / vault-memory-approval cards.
- LLM: `~/.pi/agent/models.json` (`baseUrl`) + key (`AUTONOMOUS_LLM_API_KEY`, legacy `MISTER3D_API_KEY`, or `apiKey`).
- API: `GET /search/messages?q=&bot=&limit=&mode=auto|lexical|nl`; `POST /search/messages/nl`.
- Agent: **`chat_search`** tool (hidden from the thread), system hint.

## Pitfalls / non-regressions

- Scrubbed secrets only appear as an indexed placeholder ("message a été supprimé…") — not the cleartext.
- FTS5 required (stdlib SQLite OK on our targets).
- Sentence with no LLM configured → `search_nl_no_llm` error (no misleading "exact words" fallback).
- On an existing DB after first FTS setup: backfill on the first `ensure_fts` (`serve` boot / app tests).

## Quick check

```bash
python3 -m pytest tests/test_search.py -q

curl -s -b cookies 'http://127.0.0.1:8787/api/v1/search/messages?q=raclette&mode=lexical' | jq .
curl -s -b cookies -X POST http://127.0.0.1:8787/api/v1/search/messages/nl \
  -H 'Content-Type: application/json' \
  -d '{"q":"où on parlait de mon adresse ?"}' | jq .
```
