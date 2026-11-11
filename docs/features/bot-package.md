# Bot package size (Details)

**Status**: in place  
**Key files**: `autonomous/services/bot_package.py`, `GET /bots/:name/package`, `frontend/src/components/DetailsPane.vue`  
**Last updated**: 2026-11-10 (auto-refresh, Total row, SizeRw via `docker df`)

## User behaviour

- In the inspector **Details** tab, a **Bot size** block shows the full footprint (title + breakdown under it, aligned with the title column — no subtitle hint).
- Breakdown lines (same type): files, screenshots / browser profile when any, conversation, agent session, VM layer — then a rule + **Total**.
- Updates by itself: on open, when the desk / files change, and every ~20s while Details is open (no refresh button).

## Implementation

- Host paths under `data/bots/<bot>/`:
  - `home/` (= `~/files`) → files + screenshots + browser profile
  - `pi/` → agent session JSONL
  - `downloads/`
- Conversation size = SQLite `messages` UTF-8 lengths for that bot (content + attachments_json + meta_json). File bytes for uploads/images/screenshots are **not** double-counted here — they sit under `home/`.
- VM size = Docker `SizeRw` via `client.df()` (writable layer only). Current docker-py has no `inspect_container(size=…)`. Shared image (`SizeRootFs`) is **not** attributed per bot.
- Icon column aligned like MCP / toggles (same `ui-toggle-main` + badge, no nested `info-row` padding).

## Pitfalls / non-regressions

- Do not use image virtual size as the VM weight — it would count the same multi-GB image once per bot.
- Do not call `inspect_container(..., size=True)` — TypeError on current SDK; use `df()`.
- Symlinks under `home/` are not followed (`os.walk(followlinks=False)`).

## Quick check

```bash
python3 -m pytest tests/test_bot_package.py -q
curl -sS -H "Authorization: Bearer $(cat data/token)" \
  http://127.0.0.1:8787/api/v1/bots/<bot>/package | jq .vm_bytes,.vm_state,.total_bytes
```

Open Details with a running VM → Couche VM shows MB (not “Unknown”); Total under the rule.
