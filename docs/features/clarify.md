# Structured question (clarify)

**Status**: in place  
**Key files**: `autonomous/services/clarifies.py`, `autonomous/api/clarify_routes.py`, `autonomous/migrations/001_schema.sql`, `autonomous/pi_extensions/clarify.ts`, `frontend/src/components/{ClarifyCard,ChatPane}.vue`  
**Last updated**: 2026-11-16 (Stop cancels pending clarify cards; cards still wait indefinitely otherwise)

## User behaviour

- The agent calls **`ask_clarify`** for a blocking **chat card**: clickable choices and/or short text.
- **Choices**: 2 to 8 labels. Click = answer. Without `allow_text`, no free-text field.
- **Text**: if there are no choices (default) or `allow_text=true`, short field (500 chars) + Send.
- The setup language card (Français / English) always shows that field, even when the agent omits `allow_text`. A typed answer is accepted.
- **Blocking**: the bot goes into `waiting`; the tool polls until the answer (like `ask_approval`). There is no elapsed-time expiry: an unanswered card remains pending until the user answers, writes a redirecting chat message, stops the bot, or the process is interrupted.
- While the card is pending, the agent stays blocked on it with no elapsed-time expiry. Composer messages and attachments still go to the FIFO queue; they do not cancel the card and do not resume the agent until the card is answered, declined, or the bot is stopped.
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
- Pi session dies while waiting → `mark_interrupted_after_wait` **auto-resumes** (Resume card only if retry cannot start).
- Do not add a polling deadline to `ask_clarify`: a long human absence is normal, not a tool error. The previous one-hour timeout returned control to the model while the card was still pending, causing misleading “message expired” replies.
- Do not let a composer message cancel a pending card. Queue it instead and keep the agent waiting for the card.
- `POST /bots/:name/stop` cancels every pending clarify for that bot (`cancel_pending_for_bot`) so Stop does not leave an orphan « EN ATTENTE » card.

## Quick check

```bash
pytest tests/test_clarifies.py -q
```

2026-11-16 check: with a clarify card pending, a composer message is queued (`meta.queued`) while the card stays `pending` and the bot remains `waiting`.
