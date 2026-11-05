# Tab routing (Conversation / Terminal / Screen)

**Status**: in place  
**Key files**:
- `frontend/src/router.js` (`TABS`, `normalizeTab`, `botPath`)
- `frontend/src/views/HubView.vue` (`selectTab`, `applyRoute`, `goBot`)
- `frontend/src/store.js` (`state.tab`)

**Last updated**: 2026-11-02 (time zone in the Agent tab)

## User behaviour

The URL reflects the active tab:

| UI | Canonical URL |
|----|----------------|
| Conversation | `/b/<bot>/discussion` |
| Terminal | `/b/<bot>/terminal` |
| Screen | `/b/<bot>/screen` |

- Switching tab → `router.replace` to the path above.
- Opening / refreshing a tab URL → selects the right tab.
- Aliases accepted on entry then canonicalised: `messages`→`discussion`, `ecran`/`écran`→`screen`.
- `/b/<bot>` without tab → redirect to `/b/<bot>/discussion`.
- Switching bot from the rail: without split view → Conversation. With split view → the left pane saved for that bot.
- **Two-pane** view: not an extra tab. The URL stays that of the **left** pane. The right pane is a local preference. See [desk-screen.md](./desk-screen.md).
- Bot missing from the list (deleted, or "Delete all bots"): the `/b/<slug>/…` URL goes back to `/`, or to the first remaining bot. No loading of the old slug's messages (otherwise 404 in the console).
- **Settings**: page `/settings/:section` (not a modal). Tabs on the left, in this order: `agent` (Pi, time zone, models, guard-rails), `vault`, `memory`, `companions`. `/settings/general` goes back to `agent`. Return to the current bot.
- **Setup**: `/` and `/setup` share the hub. Checklist until required items are ready; first-conversation button at the bottom (see [setup.md](./setup.md)).

## Implementation

- Vue route: `/b/:name/:tab?`.
- `beforeEach`: if `tab` missing or alias → `replace` to canonical tab.
- `HubView`: `applyingRoute` guard to avoid route ↔ `state.tab` watch loops.
- If the URL asks for terminal/screen without capability **and** the two-pane view is off → opens `CreateDeskModal` and falls back to discussion. In two-pane mode, the chosen side stays (the panel itself offers to create the desktop).

## Pitfalls / non-regressions

- Any mutation of `state.tab` (e.g. ManageMenu) must end with a consistent URL (dedicated watch).
- Don't navigate only with `state.tab = …` without `goBot` / watch.
- Don't leave `state.currentBot` on a slug missing from `state.bots`: `applyRoute` redirects, and `loadMessages` is not fired.

## Quick check

Clicks Conversation → Terminal → Screen: the address bar follows. Reloading on `/b/x/terminal` reopens the terminal.
