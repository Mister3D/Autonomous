# Inter-bot messaging (Tell / Ask)

**Status**: in place  
**Key files**: `autonomous/services/botmail.py`, `autonomous/migrations/001_schema.sql`, `autonomous/api/bots.py` (`/mail/*` routes), `autonomous/pi_extensions/botmail.ts`, `autonomous/services/{chat,agent,pi_rpc}.py`, `frontend/src/{mentions.js,components/ChatPane.vue}`  
**Last updated**: 2026-11-02 (received card: text only, without "m'a envoyé un message")

## User behaviour

In a bot's input area:

- **`Dit à @autre …`** (also `Dis` / `Dites`) — sends the message to `@autre` without waiting for a reply. System acknowledgement on the current bot. The local agent **does not start** on this line.
- **`Demande à @autre …`** — sends a question; when `@autre` has replied, the asking bot receives the reply and **its agent is relaunched** with that content.
- If the recipient is **busy** or **waiting**, the message is **queued** and processed as soon as it goes back to idle.
- `@nom` resolves the bot's `name` (case-insensitive) or its `label`.
- In the input: typing `@` opens autocomplete of the other bots (↑↓, Enter/Tab). After validation, `@nom` is shown in the bot's **avatar colour**.
- In bubbles, `@nom` is coloured and **clickable**: opens the bot and scrolls to the linked message (`?msg=<id>`, highlight).
- In the thread: **inter-bot exchanges** are a centred card (same width as tool groups), light blue background, dotted outline.
  - **Received**: mailbox icon + "Reçu de @x", then the text only. No "@x m'a envoyé un message" sentence.
  - **Sent**: the reply bubble that was sent back to the other bot (not all replies), plane icon + "Envoyé à @x".
- No separate "J'ai envoyé…" acknowledgement, no tool card. The "Dit / Demande à @…" line stays a user bubble. The asking agent is relaunched behind the scenes on reply.

Pi agent side: tools `bot_tell`, `bot_ask` (all); `bot_list` + `bot_delegate` (**Manager** only — see [manager.md](./manager.md)). Invisible in the thread. `bot_ask` waits for the reply (`status=waiting`) — Managers must not use it to orchestrate.

## Implementation

- Tables `bot_inbox` (queue) + `bot_asks` (request → reply correlation).
- Columns `bot` / `from_bot` / `to_bot` store the **`bots.id` (UUID)**, not the slug. The API / chat still expose the slug (`@horloge`) via resolution on read.
- `chat.send_message`: if the text matches Tell/Ask → `botmail.maybe_route_from_composer` and **no** local `start_run`.
- Delivery: `user` message at the recipient with `meta.kind=botmail` (`tell` | `ask` | `reply`) + `start_run`.
- End of run (`agent.PiAgent` `finally` → idle): `botmail.on_run_finished` — if the run was answering an `ask`, marks it `answered`, enqueues a `reply` at the asker, then drains one item from the local queue.
- API: `POST /bots/:name/mail/tell`, `POST /bots/:name/mail/ask`, `GET /bots/:name/mail/asks/:id`.

## Pitfalls / non-regressions

- In UI locales, escape **every** `@` as `{'@'}` (otherwise vue-i18n → `SyntaxError` and ChatPane disappears) — including `newlineHint`.
- Don't start the local agent on a purely routed line (otherwise double work + confusion).
- Drain **only** when `status` ∉ {busy, waiting} — don't interrupt a vault/OTP wait.
- Deliver the `reply` **outside** the replying bot's lock (avoids A↔B deadlock).
- `bot_ask` (tool): polling `GET .../asks/:id` puts the asker in `waiting` while the ask is `open`, then `busy` on reply (UI "waiting for the user").
- `null` backend (tests): no `start_run`; call `on_run_finished` to simulate the end of the reply.
- Agent pitfall: capture `state["content"]` **before** `close_assistant()` (which empties it) otherwise the inter-bot reply goes out empty.
- Message cross-ref: `meta.link_bot` + `meta.link_message_id` (set on delivery / reply) for the deep-link.
- `bot_list` / `bot_tell` / `bot_ask`: excluded from tool cards (`agent._HIDDEN_TOOL_CARDS` + UI filter).
- The "Sent" card only marks the assistant bubble that served as the reply (`mail_kind=outgoing`). Don't set `ask_sent` on the asker, and don't style every bubble containing an `@`.
- The received bubble stores the text only. The "@x m'a envoyé un message :" preamble is stripped on display and on re-read (old messages). The agent prompt, however, still names the sender.
- **Identity**: queue and asks reference `bots.id`. Recreating `@test` after deletion does **not** see the old queue (new UUID).
- **Bot deletion**: `bots.delete_bot` calls `botmail.purge_for_bot` (by UUID) and cleans up schedules / webhooks / vault grants & requests.
- **Ghost sender**: on delivery / drain, if the sender UUID no longer exists → `state=cancelled` (no chat bubble, move on to the next item).

## Quick check

```bash
pytest tests/test_botmail.py -q
# UI: horloge "@robert, il est 16h30" = centred blue card, Sent icon
# UI: robert "@horloge m'a envoyé…" = same card, Received icon
```
