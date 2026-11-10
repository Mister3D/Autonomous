# Bot package size (Details)

**Status**: in place  
**Key files**: `autonomous/services/bot_package.py`, `GET /bots/:name/package`, `frontend/src/components/DetailsPane.vue`  
**Last updated**: 2026-11-10

## User behaviour

- In the inspector **Details** tab, a **Package size** block shows the full footprint of the bot.
- Total + breakdown: workspace files, screenshots (when any), Chrome profile (when any), conversation (DB text + message count), Pi agent session (when any), Docker VM writable layer (or “No VM”).
- Refresh button re-measures without leaving the panel.

## Implementation

- Host paths under `data/bots/<bot>/`:
  - `home/` (= `~/shared`) → files + screenshots + browser profile
  - `pi/` → agent session JSONL
  - `downloads/`
- Conversation size = SQLite `messages` UTF-8 lengths for that bot (content + attachments_json + meta_json). File bytes for uploads/images/screenshots are **not** double-counted here — they sit under `home/`.
- VM size = Docker `SizeRw` (writable layer only). The shared desktop image (`SizeRootFs`) is **not** attributed per bot.
- Hidden rows stay at 0 until data exists (screenshots / browser / agent).

## Pitfalls / non-regressions

- Do not use image virtual size as the VM weight — it would count the same multi-GB image once per bot.
- Measuring `SizeRw` needs `inspect_container(..., size=True)` and can be slow on huge layers; Details loads it on open / refresh only (no poll).
- Symlinks under `home/` are not followed (`os.walk(followlinks=False)`).

## Quick check

```bash
python3 -m pytest tests/test_bot_package.py -q
curl -sS -b /tmp/cj http://127.0.0.1:8787/api/v1/bots/<bot>/package | jq .
```

Open Details → total + lines update; refresh icon reloads.
