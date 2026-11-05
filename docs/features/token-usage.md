# Token counter (chat)

**Status**: in place  
**Key files**: `bots.tokens_in` / `tokens_out`, `bots.add_token_usage`, `agent.message_end`, `ChatPane` (badge)  
**Last updated**: 2026-10-31 (custom tooltip)

## User behaviour

- Top left of the Conversation area: `↑ sent · ↓ received` (conversation total).
- Source: `usage` field of Pi assistant messages (`input` / `output`) on every LLM turn (including tool calls).
- Reset to **zero** when the bot's chat is cleared.
- Hover → **immediate custom tooltip** (explains ↑ context / ↓ replies + exact totals; no browser `title`).

## Implementation

- Migration `010_token_usage.sql`.
- `add_token_usage` → columns + `bot.updated` (SSE → store).
- UI: `.chat-token-usage` (hidden if 0/0).

## Pitfalls

- `usage.input` = size of the **prompt** for this turn (full context), not just the user delta — summing turns = actual API consumption.
- Invisible until a Pi turn has reported usage.
