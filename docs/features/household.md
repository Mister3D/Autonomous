# Manager household (create / delete bots)

**Status**: in place  
**Key files**:
- `autonomous/services/household.py`
- `autonomous/migrations/025_bot_delete_requests.sql`
- `autonomous/api/bots.py` — `/bots/:name/household/…`
- `autonomous/pi_extensions/botmail.ts` — `bot_models` / `bot_create` / `bot_delete`
- `frontend/src/components/{BotDeleteCard,LlmSettings}.vue`
- settings key `bots.default_model`

**Last updated**: 2026-11-09

## User behaviour

- Settings → **LLM → Default model**: Pi model used when the Manager creates a bot without naming one.
- The **Manager** (e.g. Assistant) can create bots from chat: `bot_create({ bots:[{name, model?},…] })`.
  - Omit `model` → Settings default.
  - Pass a ref (`openai/gpt-4o`) or a clear hint; `bot_models` lists available refs.
- To delete bots: `bot_delete({ bots:[…], prompt? })` shows a **checkbox card** (all checked by default). The user may uncheck some, then **Delete** or **Cancel**. The tool blocks until then.
- The Manager cannot delete itself via this card.
- Clearing chat history does not affect this flow. Typing in chat while the card is pending cancels it (same idea as `ask_approval`).

## Implementation

- `bots.default_model` in the settings KV store (also on `SettingsSchema`).
- Manager-only routes under `/api/v1/bots/:name/household/…` so the bot `abt_…` token can call them.
- Delete requests: table `bot_delete_requests` + chat event `meta.kind=bot_delete_request` → `BotDeleteCard`.
- Hidden tool cards: `bot_models`, `bot_create`, `bot_delete` (like other botmail tools).

## Pitfalls / non-regressions

- Do not open `POST /bots` to bot tokens; keep household routes under the Manager slug.
- Created bots are never Managers (`is_manager=false`).
- Resolve body: `{ action: "confirm"|"deny", bots?: string[] }` — UI sends the checked slugs.

## Quick check

```bash
pytest tests/test_household.py -q
# UI: Settings → LLM → pick a default model
# Chat (Manager): ask to create A/B with a named model; ask to delete them → checkbox card
```
