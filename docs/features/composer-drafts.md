# Composer drafts (per bot, per tab)

**Status**: in place  
**Key files**: `frontend/src/composerDrafts.js`, `frontend/src/components/ChatPane.vue`  
**Last updated**: 2026-11-07

## User behaviour

- Typing in the composer then switching to another bot **keeps the draft** for the first bot.
- Coming back to that bot restores the text (and in-session pending attachments).
- Reloading the same tab restores **text** drafts (`sessionStorage`).
- The **same bot open in two tabs/windows** has **independent** drafts (sessionStorage is per tab).
- Sending a message clears that bot’s draft in the current tab.

## Implementation

- Text → `sessionStorage` key `autonomous.composerDrafts.v1` (`{ [botName]: string }`).
- Pending attachments → in-memory `Map` for the SPA lifetime only (not across full reload).
- `ChatPane` stays mounted across bot switches: on `bot.name` change, save previous draft / load next.

## Pitfalls / non-regressions

- Do **not** use `localStorage` for drafts (would sync across tabs and fight the “two places” rule).
- On unmount, stash pending without `URL.revokeObjectURL` so a later restore still has previews.
- `composerRestore` (vault secret scrub) must also write into the draft store for the current bot.

## Quick check

```bash
# UI: type in @alice, switch to @bob, type something else, return to @alice → first draft back
# UI: same bot in two tabs → different drafts
```
