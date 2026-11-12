# Bot creation

**Status**: in place  
**Key files**:
- `frontend/src/components/CreateBotModal.vue`
- `autonomous/services/bots.py` (`slugify_bot_name`, `allocate_slug`, `create_bot`)
- `autonomous/models/schemas.py` (`BotCreateSchema`)
- `frontend/src/api.js` (`formatApiError` for flask-smorest 422)

**Last updated**: 2026-11-13 (create dialog opens on the Settings default model)

## User behaviour

- The rail's **Create** button is a round white bordered button, same size as the settings menu (40px).
- The **Create a bot** modal fits on screen: fields on the left, character and colour on the right (about 820 px). Below 760 px, everything goes back to a single column, and the modal scrolls if needed (`max-height`).
- No **Role** persona: no UI field, no `bots.role` column, no injection into the Pi prompt, no `--role` CLI. `POST` / `PATCH /bots` reject an unknown `role`.
- **Right panel** (Details / Events / Files): open by default on large screens. Chevron at the top right of the panel, **aligned** with the tab bar / the two lists (same height, disc on hover). It collapses the panel; the main area takes the width. To reopen it: round button in that same bar, with a space to its left. `localStorage` preference `autonomous.inspectorCollapsed` (absent = open). Below 1080 px the panel stays a drawer, the chevron closes it without remembering the desktop collapse.
- **Details → Delete bot**: the row stays one line. A second click is a check icon at the end of the row (custom tooltip with the question). Not the old Yes/Cancel card, not `window.prompt`. Then `DELETE /bots/:name` (+ wipe Pi/dir + purge linked inbox/asks/schedules/webhooks). **Settings → Delete all bots** still uses the inline card. Delete all goes back to `/`. A slug that no longer exists doesn't stay in the address bar.
- **Rename**: click on the inspector's `h2` title (next to the avatar) → inline edit → Enter / blur saves (`PATCH /bots/:name` `{label}`); Esc cancels. The technical slug (`bots.name`) **does not change**.
- The entered **name** may contain **capitals and spaces** (e.g. `Debug Bot`), max 64 characters.
- **Case-insensitive uniqueness**: `Test` / `test` / `TEST` → conflict (409). Same on rename (`label`).
- A **technical slug** is derived automatically (`debug-bot`) for URL `/b/<slug>/…`, Docker, SQLite `bots.name`, `@mentions` in Tell/Ask.
- Slug collision **with another label** (e.g. `Debug Bot` then `Debug_Bot`) → suffix `-2`, `-3`, …
- The UI shows the `label` (free-form name); the slug stays visible as a hint at creation and in the `@` autocomplete.

## Implementation

- `POST /bots`: `{ "name": "Debug Bot" }` → `label="Debug Bot"`, `name="debug-bot"`.
- **Shared memory** checkbox (`memory_access`, default on): untick to isolate the bot (see [memory.md](./memory.md)).
- **Manager** checkbox (`is_manager`, default off): orchestrator — lists bots and delegates without waiting (see [manager.md](./manager.md)). **Only one** Manager: if another one already exists, the checkbox is disabled (API → 409 `manager_exists`).
- **Model** is required: the picker has **no** “Aucun modèle / No model” row. It opens on `bots.default_model` from Settings when that ref is set. Create stays disabled until a real model is chosen; Details cannot clear the model. `POST /bots` and `PATCH /bots/:name` reject empty `model` (`model_required`). No silent auto-pick of the first Pi model. Placeholder text may still appear if a legacy bot has an empty model, or if Settings has no default yet.
- Optional: `{ "name": "Mon Assistant", "slug": "asst" }` to force the technical id.
- `label` in the payload is still accepted (legacy) and overrides the display if provided.
- `bots.name` = slug (`^[a-z0-9][a-z0-9_-]{0,31}$`); `bots.label` = free-form name; `bots.id` = stable UUID (mail / events / vault).

## Pitfalls / non-regressions

- Don't reintroduce `window.prompt` for deletion (same reason as "Delete all bots" / file mkdir).
- In i18n strings, a literal `@` is written `{'@'}` (vue-i18n). `@manager` in the Manager help crashes the rendering of the Create modal (console error `INVALID_LINKED_FORMAT`).
- Don't store spaces in `bots.name` (breaks Docker / paths / botmail regex `@([a-zA-Z0-9_-]+)`).
- Uniqueness comparison: `casefold` on `label` **and** `name` (`display_name_taken`).
- A symbols-only name (`!!!`) produces no slug → 400/422.
- API clients that were already sending a slug (`"name": "demo"`) keep working (`label` = same string).

## Quick check

```bash
pytest tests/test_bots.py -q
# UI: Create → "Debug Bot" → rail shows Debug Bot, URL /b/debug-bot/discussion
# UI: click inspector title → rename → rail + header updated, URL unchanged
TOKEN=$(cat data/token)
curl -s -X PATCH -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"label":"Nouveau Nom"}' http://127.0.0.1:8787/api/v1/bots/debug-bot
```
