# Token counter (chat) + Settings history chart

**Status**: in place  
**Key files**:
- `bots.tokens_in` / `tokens_out`, `bots.add_token_usage`, `agent.message_end`, `ChatPane` (badge + per-call llm_turn cards)
- `bot_token_usage_daily`, `token_usage_history.py`, `GET /bots/token-usage`, `TokenUsageChart.vue`
**Last updated**: 2026-11-15 (narrow screens show a table instead of the chart)

## User behaviour

### Chat badge
- Top left chrome row (above the rounded `.chat-surface` card): `↑ sent · ↓ received` (conversation total).
- Source: `usage` field of Pi assistant messages (`input` / `output`) on every LLM turn (including tool calls).
- Reset to **zero** when the bot's chat is cleared.
- Hover → **immediate custom tooltip** (explains ↑ context / ↓ replies + exact totals; no browser `title`).

### Settings → Consumption
- The nav label is **Consumption** / **Consommation**. The route stays `/settings/tokens`.
- Full-height line chart: **one series per living bot**, cumulative tokens (in+out) over time.
- At `max-width: 760px` the chart is replaced by a borderless table and a day bar (previous / date / next, no calendar icon). The bar uses the Soft UI surfaces (white, `--line`, orange arrows), not a one-off blue. The table lists each bot that used tokens on that day, heaviest first. A day with nothing shows an empty line. The wide chart comes back above 760px.
- Y scale = max cumulative among bots; X = days (UTC), always at least the last **30 days** (zeros before first use so a single day still draws a curve).
- Default viewport shows the **last 30 days**; horizontal scroll reveals older history.
- Endpoint dots stay visible; empty usage still shows the chart frame + hint overlay.
- Legend: small avatar + bot name coloured like the line (avatar swatch; Original → accent orange).
- Hover a day → tooltip with cumulative value per bot.
- **Clear chat history** does **not** erase the daily history (badge counters still reset).
- **Delete bot** removes that bot’s daily rows (FK `ON DELETE CASCADE`).

## Implementation

- Migration `010_token_usage.sql` (conversation counters on `bots`).
- Migration `024_token_usage_daily.sql` (`bot_token_usage_daily`).
- `add_token_usage` → updates `bots` + upserts today’s UTC bucket.
- `GET /api/v1/bots/token-usage` → `{ days, series[{bot,label,avatar,avatar_color,daily,cumulative}], max_cumulative }`.
- UI: Settings section `tokens` → `TokenUsageChart.vue` (SVG, no chart library; a table under 760px).

## Pitfalls

- `usage.input` = size of the **prompt** for this turn (full context), not just the user delta — summing turns = actual API consumption.
- Chat badge invisible until a Pi turn has reported usage.
- History only starts when usage is recorded after migration `024` (no backfill from old counters).
- Route `/bots/token-usage` must be registered **before** `/bots/<name>` or Flask treats `token-usage` as a bot slug.

## Quick check

```bash
pytest tests/test_token_usage.py tests/test_token_usage_history.py -q
curl -s -H "$H" localhost:8787/api/v1/bots/token-usage | head
# UI: Settings → Consumption — wide: scroll left for older days; narrow: table of totals. Clear chat; curve stays.
```
