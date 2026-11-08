# Companion avatars

**Status**: in place  
**Key files**:
- `avatar/characters/<id>/` — web SVG + `.vectorcraft` (ready) + `meta.json`
- `avatar/pending/` — Vectorcraft sources not yet ready for the animated catalog
- `avatar/vue/` — Vue package `@autonomous/companion-avatar` (`CompanionAvatar`, `CompanionAvatarPicker`)
- `frontend/src/components/BotAvatar.vue` — rail badges (40px) + inspector (96px)
- `frontend/src/components/AvatarEditModal.vue` — inspector avatar click
- `frontend/src/components/CreateBotModal.vue` — choice at creation
- `autonomous/avatars.py` — ready catalogue
- `autonomous/migrations/001_schema.sql` — columns `avatar`, `avatar_color`

**Last updated**: 2026-11-08 (Firefox Android: no CSS scale on the root SVG, explicit px size)

## User behaviour

- Badge **without background or circle**; sizes `sm` 40 / `md` 64 (Manager rail) / `lg` 96.
- **work** (`status=busy`): Work animation.
- **await** (`status=waiting`): jumps — authorisation, credentials, etc.
- **notify**: unread assistant messages (bot not selected).
- **red dot** `.avatar-pip.unread` (rail sm): unread **or** `status=waiting`.
- **idle**: still; on hover, the eyes follow the mouse.
- **lg avatar (inspector)**: hover → **immediate custom tooltip** (no browser `title`) with the agent state; no more "State" line in Details.
- **Creation**: character grid + 18 colour swatches in 3 rows of 6 (22 px), centred. Avatar editing (inspector) keeps the wide grid.
- **Inspector**: click on the lg avatar → same picker → `PATCH` `avatar` / `avatar_color`.

## Reusable package

```js
import { CompanionAvatar, CompanionAvatarPicker } from "@companion-avatar";
```

Regenerate characters + `vue/catalog.js`: `python3 avatar/tools/sync_characters.py`.

## Pitfalls

- `await` (Vue API) and `wait` (old CSS): both work.
- Not-ready characters: SVG + `meta.json` under `characters/`; Vectorcraft stays in `pending/` until animated.
- No `border-radius: 50%` / background on `.bot-avatar` (the character is not in a disc).
- **Original** swatch: badge split in two (medium grey | orange).
- **Firefox Android**: inline SVG inside a `<button>` (the bot rail) disappears when the root `<svg>` has a CSS `transform` (`scale`) or only a percentage size. Keep an explicit px width/height on `.bot-avatar.is-*` and on `svg.avatar-svg`. Zoom by tightening `fitViewBox` (`fill` 0.94), not with CSS. If `getBBox()` is still 0×0 on the first frame, leave the authored `viewBox` and retry next frame — never write `viewBox="0 0 0 0"`.

## Quick check

```bash
# UI: Create → choose animal/colour; click inspector avatar → change
curl -s -X PATCH -H "$H" -H 'Content-Type: application/json' \
  -d '{"avatar":"chat","avatar_color":3}' localhost:8787/api/v1/bots/<slug>
```
