# Inter-bot messaging (Tell / Ask)

**Status**: in place  
**Key files**: `autonomous/services/botmail.py`, `autonomous/migrations/001_schema.sql`, `autonomous/api/bots.py` (`/mail/*` routes), `autonomous/pi_extensions/botmail.ts`, `autonomous/services/{chat,agent,pi_rpc}.py`, `frontend/src/{mentions.js,components/ChatPane.vue}`  
**Last updated**: 2026-11-09 (collapsible botmail cards in chat)

## User behaviour

**Mention ≠ send.** Writing `@name` (or naming a bot) in a private chat only cites them. Delivery requires an explicit instruction (action verb + bot + precise ask), e.g. « Ask @X to do Y, with context Z, and bring the result back here », or a standing rule the bot already has (« when a purchase email arrives, give it to @orders »).

In a bot's input area:

- **`Tell @other …`** (FR aliases: `Dit` / `Dis` / `Dites à @…`) — marks a **route_intent** and **starts the local agent**. The agent must call `bot_tell` with a self-contained brief for the peer. No automatic forward of the raw line.
- **`Ask @other …`** (FR aliases: `Demande` / `Demandez à @…`) — same, with `bot_ask` when the user wants the reply brought back here.
- **Natural chat** (« I think @lol rides horses — do you like that too? ») — the bot answers **you**. It contacts `@lol` only if clearly asked; then it sends a short autonomous question, never your whole sentence.
- **Peer-facing content** is always authored by the sending bot: objective, relevant facts, constraints, expected result. The peer does **not** see this chat. Address them as « you »; never a raw relative clause (« if she… »).
- Exchanges are **async**. Confirming transmission ≠ task finished. Prefer Ask (or follow-up) when the user said « bring it back here »; Tell when they continue in the peer’s chat.
- Inter-bot mail does **not** grant new rights and does not replace vault / approval / external-send consent.
- If the recipient is **waiting** (vault / approval / …), the message stays **queued** until idle. If they are **busy** mid-run, delivery tries a **mid-run steer** so they can answer then continue; otherwise it queues.
- `@name` resolves `name` (case-insensitive) or `label`. Composer `@` autocomplete: ↑/↓ move the highlight; Enter/Tab inserts.
- In the thread: centred blue cards for inter-bot mail. UI copy comes from frontend locales (en/fr).
  - **Sent** (sender): when `bot_tell` / `bot_ask` / API mail succeeds, a card shows the **peer-facing body** (« Sent to @x »). Ask *replies* still stamp the assistant bubble as outgoing.
  - **Received** (peer): « Received from @x » with the same body (or the ask answer).
  - Long bodies are **collapsed** to the first sentence; a click on the card expands/collapses (links stay clickable without toggling).

Pi tools: `bot_tell`, `bot_ask` (all); `bot_list` + `bot_delegate` (**Manager** only — see [manager.md](./manager.md)). Invisible in the thread. `bot_ask` waits (`status=waiting`) — Managers must not use it to orchestrate.

## Implementation

- Tables `bot_inbox` + `bot_asks` (identity = `bots.id` UUID).
- `chat.send_message` → `botmail.maybe_route_from_composer`: on Tell/Ask, sets `meta.mail_kind=route_intent` + enriched `agent_prompt`, then **starts the local agent** (no tell/ask enqueue). Unknown target → error system bubble, no agent.
- Delivery still via `tell` / `ask` / API / tools. If `origin_message_id` is omitted, `tell`/`ask` attach the latest `route_intent` user bubble for deep-links. Each successful `tell`/`ask` also inserts an `outgoing` system card on the sender (`meta.outgoing_message_id` on the inbox row); delivery deep-links that card to the peer’s received bubble.
- End of run → `on_run_finished`: ask reply correlation + queue drain. **`maybe_rescue_mentions` is a no-op** (must not invent mail from `@` + user text). Orphan Tell relay (peer answered a Tell while asker promised to forward) remains.
- System / tool prompts: mention ≠ send; content = self-contained brief; async; where to report results.
- Recipient agent prompt: treat the body alone under own instructions (no emitter thread).

## Pitfalls / non-regressions

- Do **not** restore composer bypass that regex-forwards fragments without the local agent.
- Do **not** re-enable rescue that builds the peer body from the user message.
- Composer `@keyup` calls `syncMentionQuery` — only reset `mentionIndex` when the filter (`start`/`query`) changes, otherwise ArrowDown/Up snap back to the first row.
- Source code, tests, and agent prompts stay **English**. UI strings → `frontend/src/locales/{en,fr}.json`. Keep FR `Dit`/`Demande` only as composer parse aliases.
- The **mail body** and the **reply to the user** stay in the conversation language (one language). Prompts say so explicitly (`_LANG_RULE` / `_INBOUND_LANG_RULE`) so the model does not mix French and English just because the instructions are English.
- Drain only when `status` ∉ {busy, waiting}. Deliver reply outside the replying bot’s lock.
- `null` backend (tests): route_intent is set, peer stays empty until an explicit `tell`/`ask`.
- Capture `state["content"]` before `close_assistant()` for ask replies.
- UI locales: escape every `@` as `{'@'}`.
- Botmail collapse: sentence break requires `.!?…` followed by whitespace/end (so `Vue.js` does not cut early). Expand state is UI-only (per message id, not persisted).
- Bot deletion → `botmail.purge_for_bot`; ghost sender → `cancelled`.

## Quick check

```bash
pytest tests/test_botmail.py tests/test_events.py -q
# Composer « Ask @lol … » → route_intent on asker, no card on lol until bot_ask
# Mixed « I think @lol… do you too » → no auto-mail
# Webhook with JSON → meta.agent_prompt contains Payload
```
