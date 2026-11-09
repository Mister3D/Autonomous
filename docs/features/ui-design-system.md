# Soft UI design system

**Status**: in place  
**Key files**:
- `frontend/src/styles/tokens.css` — colour, radius, shadow, type tokens
- `frontend/src/styles/soft-ui.css` — Soft UI surface + primitive styles
- `frontend/src/styles.css` — legacy layout / feature CSS (consumes tokens)
- `frontend/src/components/ui/` — `UiButton`, `UiCard`, `UiIcon`, `UiIconBadge`, `UiToggleRow`
- `frontend/index.html` — Plus Jakarta Sans

**Last updated**: 2026-11-09 (chat `.messages` scrollbar auto-hide 2 s)

## User behaviour

- Light Soft UI: soft canvas (`--bg-canvas`), elevated white cards, orange accent, soft shadows.
- Settings sections are card-based with icon badges (Générale, LLM, Grounding, Tokens, vault, memory, companions). Tokens is a flush full-height chart (no cards). LLM card (`.llm-settings`) stacks sections with one flex gap + shared subhead rule (no mixed per-block margins).
- `UiIcon` `memory` = [SVG Repo brain](https://www.svgrepo.com/svg/521533/brain) (filled `currentColor`) — settings nav Mémoire + inspector Mémoire.
- Bot inspector rows reuse the same icon-badge pattern: Modèle (database icon + picker only), Internet, Transfert, Mémoire, Manager, Veille, **MCP (puzzle)**. Manager uses `UiToggleRow` `tip` (custom bubble on the switch) instead of the `<small>` hint; when locked, the tip shows the “already a Manager” reason.
- Rail settings pop: Réglages / Déconnexion (`settings`, `logout`). Delete-all bots lives under Settings → Générale (arm → check; tooltip = « Confirmer ? »).
- Top chrome (rail logo + search/create orbs, chat token pill, split + stage tabs, inspector collapse) shares one vertical band (`--chrome-top` + `--control-h-sm`).
- Shell is one continuous `--bg-sidebar` plane (no rail/stage/inspector dividers); conversation sits in a detached elevated card (`.chat-surface`) on that plane.
- Settings: `.settings-main` has no left padding (nav already pads); top/right/bottom stay.
- Labels: Conversation / Terminal / Écran; inspector Files tab = « Fichiers »; settings nav keys under `settings.tab*`.

## Implementation

1. `main.js` loads `tokens.css` → `styles.css` → `soft-ui.css`.
2. Prefer `components/ui/*` for new chrome (buttons, cards, toggles, icons) instead of duplicating SVG / toggle markup.
3. Existing feature CSS keeps working; Soft UI overrides polish surfaces (shell, settings, composer, bubbles).
4. i18n: `tabs.screen` = « Écran », `tabs.discussion` aligned with Conversation, `settings.tabVault|Memory|Companions` for nav consistency.
5. Top chrome sizes: `--chrome-top` / `--control-h-sm` in `tokens.css`; rail bottom settings orb stays `--control-h`.
6. Chat card: `ChatPane` wraps messages + composer in `.chat-surface`; stage panes reuse the same radius/shadow on canvas.

## Pitfalls / non-regressions

- Do **not** hardcode hex for brand surfaces in new UI — use tokens.
- `--dev` rebuilds via `vite build --watch` into `autonomous/static/` (not Vite HMR on :5173). Wait for rebuild after CSS/Vue edits.
- Keep UI copy in `locales/{en,fr}.json`; source / docs / prompts stay English.
- Mobile: settings nav becomes a horizontal scroller; chat uses master–detail (`is-mobile-*` on `.app-shell`).

## Quick check

1. `autonomous serve --host 127.0.0.1 --port 8787 --dev`
2. Open `/b/<bot>/discussion` — Soft canvas, orange active tab, « Écran ».
3. Open inspector — icon badges on Internet / memory / manager / sleep.
4. Open `/settings/grounding` — card stack; model picker height matches other fields (`--control-h`); full-width Enregistrer under the cards.
5. Narrow to ~390px — bot list XOR chat; settings nav scrolls horizontally.
