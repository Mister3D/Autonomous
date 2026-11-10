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

**Last updated**: 2026-11-09 (one mail path: bot_tell + attachments + expect_reply)

## User behaviour

- A **Manager** bot is a normal bot + the "Manager (orchestrator)" checkbox (creation or Details).
- **A single Manager** in the household: creating or promoting a second one → 409 `manager_exists`. The UI disables the checkbox if another Manager already exists. In Details, the Manager hint is a custom hover tip on the switch (not a line under the title); when locked the tip is « Un seul manager possible. ».
- To change Manager: disable the current one (Details), then enable / create the other.
- **Rail**: Managers are **featured at the top** (md avatar + name below, centred); the other bots stay in the list below.
- It can **list** the other bots (`bot_list` / `GET /bots/:name/mail/peers`): name, label, status, capability. No persona.
- For a multi-bot task: **one mail tool** — `bot_tell(to, content, attachments?, expect_reply?)`.
  - `expect_reply` (Manager only) wraps the body with the async « Tell @manager … » footer (same text as legacy `bot_delegate`).
  - **Files**: only via `attachments` on that same `bot_tell` / `bot_ask` (staging copy). No second file channel.
- `bot_delegate` remains as **text-only sugar** over tell+expect_reply (no `attachments`). Prefer `bot_tell` when files or a callback matter.
- When the worker does `Tell @manager`, the Manager is relaunched like a regular tell (workers attach result files with `bot_tell` too).
- `bot_ask` (blocking) is **refused** on the tool side if the bot is a Manager.

## Implementation

- Column `is_manager` (bool). Patch → restarts the Pi session (manager prompt).
- `ensure_manager_slot` before INSERT / UPDATE that sets `is_manager=1`.
- Manager system prompt: don't wait / don't poll; `bot_tell` + `expect_reply` + optional `attachments`.
- `POST /mail/tell` accepts `attachments` and Manager-only `expect_reply`. `POST /mail/delegate` stays text-only sugar.
- Non-manager: `bot_tell` / `bot_ask` unchanged (`expect_reply` → 403); `bot_list` / `bot_delegate` / household tools → 403 `manager_required`.
- Household create/delete + default model: [household.md](./household.md).

## Pitfalls / non-regressions

- Don't make the Manager wait (`status=waiting`) for a long delegation.
- Users can still type `Tell @` / `Ask @` (or FR aliases `Dit à` / `Demande à`) in the composer (not reserved to the Manager).
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
