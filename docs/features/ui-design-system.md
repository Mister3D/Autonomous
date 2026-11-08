# Soft UI design system

**Status**: in place  
**Key files**:
- `frontend/src/styles/tokens.css` — colour, radius, shadow, type tokens
- `frontend/src/styles/soft-ui.css` — Soft UI surface + primitive styles
- `frontend/src/styles.css` — legacy layout / feature CSS (consumes tokens)
- `frontend/src/components/ui/` — `UiButton`, `UiCard`, `UiIcon`, `UiIconBadge`, `UiToggleRow`
- `frontend/index.html` — Plus Jakarta Sans

**Last updated**: 2026-11-09 (settings delete-all uses action-confirm check)

## User behaviour

- Light Soft UI: soft canvas (`--bg-canvas`), elevated white cards, orange accent, soft shadows.
- Settings sections are card-based with icon badges (Générale, LLM, Grounding, vault, memory, companions).
- Bot inspector rows reuse the same icon-badge pattern: Modèle, Session Pi, Internet, Transfert, Mémoire, Manager, Veille, **MCP (puzzle)**, Bureau.
- Labels: Conversation / Terminal / Écran; inspector Files tab = « Fichiers »; settings nav keys under `settings.tab*`.

## Implementation

1. `main.js` loads `tokens.css` → `styles.css` → `soft-ui.css`.
2. Prefer `components/ui/*` for new chrome (buttons, cards, toggles, icons) instead of duplicating SVG / toggle markup.
3. Existing feature CSS keeps working; Soft UI overrides polish surfaces (shell, settings, composer, bubbles).
4. i18n: `tabs.screen` = « Écran », `tabs.discussion` aligned with Conversation, `settings.tabVault|Memory|Companions` for nav consistency.

## Pitfalls / non-regressions

- Do **not** hardcode hex for brand surfaces in new UI — use tokens.
- `--dev` rebuilds via `vite build --watch` into `autonomous/static/` (not Vite HMR on :5173). Wait for rebuild after CSS/Vue edits.
- Keep UI copy in `locales/{en,fr}.json`; source / docs / prompts stay English.
- Mobile: settings nav becomes a horizontal scroller; chat uses master–detail (`is-mobile-*` on `.app-shell`).

## Quick check

1. `autonomous serve --host 127.0.0.1 --port 8787 --dev`
2. Open `/b/<bot>/discussion` — Soft canvas, orange active tab, « Écran ».
3. Open inspector — icon badges on Internet / memory / manager / sleep.
4. Open `/settings/grounding` — card stack, orange active nav bar, Enregistrer with save icon.
5. Narrow to ~390px — bot list XOR chat; settings nav scrolls horizontally.
