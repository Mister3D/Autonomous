# Manager bot (orchestrator)

**Status**: in place  
**Key files**:
- `autonomous/migrations/001_schema.sql` — `bots.is_manager`
- `autonomous/services/bots.py` — `get_manager`, `ensure_manager_slot` (uniqueness)
- `autonomous/services/botmail.py` — `list_peers`, `format_delegate_content`
- `autonomous/api/bots.py` — `GET …/mail/peers`, `POST …/mail/delegate`
- `autonomous/pi_extensions/botmail.ts` — `bot_list` / `bot_delegate` (managers)
- `autonomous/services/pi_rpc.py` — `_MANAGER_SYSTEM_HINT`
- UI: `CreateBotModal`, `DetailsPane`, `HubView` (Managers rail)

**Last updated**: 2026-10-31 (a single Manager)

## User behaviour

- A **Manager** bot is a normal bot + the "Manager (orchestrator)" checkbox (creation or Details).
- **A single Manager** in the household: creating or promoting a second one → 409 `manager_exists`. The UI disables the checkbox if another Manager already exists.
- To change Manager: disable the current one (Details), then enable / create the other.
- **Rail**: Managers are **featured at the top** (md avatar + name below, centred); the other bots stay in the list below.
- It can **list** the other bots (`bot_list` / `GET /bots/:name/mail/peers`): name, label, status, capability. No persona.
- For a multi-bot task: it **delegates** with `bot_delegate` (or the `mail/delegate` API) — **without waiting**.
- The message to the worker includes the instruction to **relaunch** it via `Dit à @manager …` when done (success or failure).
- When the worker does `Dit à @manager`, the Manager is relaunched like a regular tell.
- `bot_ask` (blocking) is **refused** on the tool side if the bot is a Manager — use `bot_delegate`.

## Implementation

- Column `is_manager` (bool). Patch → restarts the Pi session (manager prompt).
- `ensure_manager_slot` before INSERT / UPDATE that sets `is_manager=1`.
- Manager system prompt: don't wait / don't poll; plans built around the `Dit à` callback.
- Non-manager: `bot_tell` / `bot_ask` unchanged; `bot_list` / `bot_delegate` → 403 `manager_required`.

## Pitfalls / non-regressions

- Don't make the Manager wait (`status=waiting`) for a long delegation.
- Users can still type `Dit à` / `Demande à` in the composer (not reserved to the Manager).
- `bot_list` reads `/mail/peers`, not `GET /bots` (the rail UI stays public).
- If the database already has several Managers (old data): the UI locks promotion; fix manually by leaving only one with `is_manager=1`.

## Quick check

```bash
pytest tests/test_manager.py tests/test_botmail.py -q
# UI: create a Manager, try a 2nd → checkbox disabled / 409; worker without Manager checkbox OK
TOKEN=$(cat data/token)
curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Worker Smoke","is_manager":false}' http://127.0.0.1:8787/api/v1/bots
```
