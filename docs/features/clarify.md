# Structured question (clarify)

**Status**: in place  
**Key files**: `autonomous/services/clarifies.py`, `autonomous/api/clarify_routes.py`, `autonomous/migrations/001_schema.sql`, `autonomous/pi_extensions/clarify.ts`, `frontend/src/components/{ClarifyCard,ChatPane}.vue`  
**Last updated**: 2026-11-09 (language card always offers free text)

## User behaviour

- The agent calls **`ask_clarify`** for a blocking **chat card**: clickable choices and/or short text.
- **Choices**: 2 to 8 labels. Click = answer. Without `allow_text`, no free-text field.
- **Text**: if there are no choices (default) or `allow_text=true`, short field (500 chars) + Send.
- The setup language card (Français / English) always shows that field, even when the agent omits `allow_text`. A typed answer is accepted.
- **Blocking**: the bot goes into `waiting`; the tool polls until the answer (like `ask_approval`).
- Chat message during `waiting`: cancels the card (`cancelled` + `human_redirect`) — the agent follows the message.
- The tool call is **hidden** from the thread — only the card remains.
- Choice buttons are full-width white chips (visible border + background). They use `btn clarify-choice`, not `btn ghost` (ghost made them look like plain text on the card).
- Yes/no consent on a risky action: **`ask_approval`**, not clarify.

## API

| Method | Path | Role |
|---------|--------|------|
| POST | `/api/v1/clarifies/requests` | `{bot, prompt, title?, choices?, allow_text?}` |
| GET | `/api/v1/clarifies/requests/:id` | Poll state |
| POST | `/api/v1/clarifies/requests/:id/resolve` | `{choice?}` or `{text?}` |

## Pitfalls

- Distinct from **`ask_approval`** (Accept / Decline) and from **memory** (non-blocking).
- Only one of the two: `choice` **or** `text`. Both together → 400.
- `allow_text` omitted: true if there are no choices, false if there are.
- Pi session dies while waiting → "Resume" card (`mark_interrupted_after_wait`).

## Quick check

```bash
pytest tests/test_clarifies.py -q
```
