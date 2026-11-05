# Emoji reactions

**Status**: in place  
**Key files**: `autonomous/services/reactions.py`, `autonomous/pi_extensions/react.ts`, `autonomous/services/{chat,pi_rpc,agent,botmail}.py`, `frontend/src/components/ChatPane.vue`  
**Last updated**: 2026-11-06 (rare, deliberate reactions)

## User behaviour

- The bot can put **an emoji** on the user message it is replying to (`react`), only when it adds something the reply does not (thanks, a joke, good news). Most turns get none. A plain question does not get a 👍 just because the bot answers it. Same restraint in the reply text.
- The badge is shown under the bubble, on the inner side (to the left of a user bubble).
- A reaction **is not a reply**. The agent can follow up with text, a tool, an action. If the emoji is enough (thanks, acknowledgement), it can stop without a filler sentence.
- No tool card in the thread. Several emojis possible (6 max), no duplicates.
- It only appears on the **next start** of the Pi session (already open process = old prompt, without the tool).

## Implementation

- Pi tool `react({ emoji })` → `POST /api/v1/bots/:name/reactions`.
- Target: explicit `message_id`, otherwise the user message of the current turn (`set_turn_message` at run launch, including queue and resume). A botmail turn clears this target.
- Storage: `messages.meta.reactions` (list). SSE `message.updated`.
- Emoji only: no ASCII letters or digits. Rejected on a message that is not `user`.

## Pitfalls / non-regressions

- Don't make `react` a blocking tool, and don't hide the assistant bubble that follows.
- Don't react on an assistant, system, or tool bubble.
- Don't let a mail turn react on the same bot's old user message.
- Already launched Pi session: it doesn't load `react.ts` until it has restarted.

## Quick check

```bash
pytest tests/test_reactions.py -q
# Then, with the hub running: POST /api/v1/bots/<slug>/reactions {"emoji":"❤️","message_id":"..."}
# The badge appears on the bubble without reloading (SSE).
```
