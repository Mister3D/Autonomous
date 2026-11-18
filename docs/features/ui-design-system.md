# Soft UI design system

**Status**: in place  
**Key files**:
- `frontend/src/styles/tokens.css` — colour, radius, shadow, type tokens
- `frontend/src/styles/soft-ui.css` — Soft UI surface + primitive styles
- `frontend/src/styles.css` — legacy layout / feature CSS (consumes tokens)
- `frontend/src/components/ui/` — `UiButton`, `UiCard`, `UiIcon`, `UiIconBadge`, `UiToggleRow`, `UiSwitch`, `UiActionConfirm`
- `frontend/index.html` — Plus Jakarta Sans
- Full component map (panes, cards, modals): [`vue-components.md`](./vue-components.md)

**Last updated**: 2026-11-19 (UiActionConfirm, UiSwitch, shared chat-request-card chrome)

## User behaviour

- Light Soft UI: soft canvas (`--bg-canvas`), elevated white cards, orange accent, soft shadows. Every orange icon badge (`.ui-icon-badge` / `.is-accent`, setup update ico, user bubbles) uses solid `--accent-badge: #f9ebdb` — not a transparent rgba that shifts with the parent surface. Muted / ok / danger badges stay on their own tones. Chat markdown links use `--accent-ink` (same brown as accent icon glyphs).
- Settings sections are card-based with icon badges (Générale, LLM, Grounding, Consumption, vault, memory, companions). Consumption is a flush full-height chart on a wide screen, and a day bar plus a table under 760px (no cards). General stays a single full-width column. The language switch is centered. The default-model picker spans its card. **Add a provider** and **Add a model** are centered under their lists. The grounding attempt field and **Test notification** sit on the right of their row. LLM settings (`.llm-settings`) is four cards — default model, providers, models, other models — each body a flex column with one gap.
- `UiIcon` `memory` = [SVG Repo brain](https://www.svgrepo.com/svg/521533/brain) (filled `currentColor`) — settings nav Mémoire + inspector Mémoire.
- Bot inspector rows reuse the same icon-badge pattern: Modèle (database icon + picker only), Internet, Transfert, Mémoire, Réflexion / Thinking (`MenuSelect` of Pi levels), Manager, Veille, **MCP (puzzle)**. Manager uses `UiToggleRow` `tip` (custom bubble on the switch) instead of the `<small>` hint; when locked, the tip shows the “already a Manager” reason.
- Rail settings pop: Réglages / Déconnexion (`settings`, `logout`). Delete-all bots lives under Settings → Générale (`UiActionConfirm` arm → check; tooltip = « Confirmer ? »). Chat request cards share `.chat-request-card` chrome; Events uses compact `UiSwitch`.
- Top chrome (rail logo + search/create orbs, chat token pill, split + stage tabs, inspector collapse) shares one vertical band (`--chrome-top` + `--control-h-sm`).
- Stage tabs / split toolbar (`right: 0.35rem`) share the chat card’s right edge (same as `.stage-body` horizontal padding) — not a deeper inset.
- Mobile chat (`≤720px`): stage tabs stay a compact pill (`flex: none` + `margin-left: auto`) before the inspector toggle — never stretch full-width between Back and the panel button.
- Shell is one continuous `--bg-sidebar` plane (no rail/stage/inspector dividers); conversation sits in a detached elevated card (`.chat-surface`) on that plane. The home / setup empty state (`.brand-empty` + `SetupPanel`) uses the same inset rounded window (gradient + art stay inside the card) so a rail hover is not cut by a full-bleed home fill. Split resize handle stays on that plane at rest (no grey rule); screen/terminal cards keep a full bottom radius in split (height accounts for chrome `margin-top`).
- The bot list does not reserve a scrollbar column (rows reach the rail edge). A 6 px thumb overlays that edge on hover or while scrolling, then fades. The conversation uses the same `0.45rem` inset on the right as on the left, so its thumb is not parked in a wide blank margin.
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
- Mobile: settings nav becomes a horizontal scroller that stays inside the screen width; chat uses master–detail (`is-mobile-*` on `.app-shell`).

## Quick check

1. `autonomous serve --host 127.0.0.1 --port 8787 --dev`
2. Open `/b/<bot>/discussion` — Soft canvas, orange active tab, « Écran ».
3. Open inspector — icon badges on Internet / memory / manager / sleep.
4. Open `/settings/grounding` — card stack; model picker height matches other fields (`--control-h`); full-width Enregistrer under the cards.
5. Narrow to ~390px — bot list XOR chat; settings nav scrolls horizontally.
