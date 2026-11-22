# Vue components catalogue

**Status**: in place  
**Key files**: `frontend/src/{App,main,router,store,sync,api,i18n}.js|vue`, `frontend/src/views/*`, `frontend/src/components/**`  
**Last updated**: 2026-11-19 (LLM default thinking select)

## Why this note exists

When the human says « lis le readme dans docs » (or equivalent), the agent **must** open this catalogue (at least skim the tree + the section matching the task) before inventing new UI. Prefer **extending** an existing component over cloning markup. Soft UI primitives live under `components/ui/` — see also [`ui-design-system.md`](./ui-design-system.md).

## Tree (entry → shell → panes)

```
App.vue
├── LoginView.vue          # unauthenticated
└── HubView.vue            # main shell (rail + stage + inspector)
    ├── SettingsMenu.vue
    ├── CreateBotModal.vue / CreateDeskModal.vue / AvatarEditModal.vue
    ├── SetupPanel.vue     # first-run / home when no bot selected
    ├── ChatPane.vue       # tab discussion (+ chat cards, ToolGroup, WorkingOrb…)
    ├── TerminalPane.vue
    ├── ScreenPane.vue
    └── inspector:
        ├── DetailsPane.vue
        ├── LibraryPane.vue   # Files / ~/files
        └── EventsPane.vue
```

Supporting modules (not components, but always nearby): `store.js` (reactive state + SSE apply), `sync.js` (EventSource), `api.js` (HTTP), `router.js` (`/b/:name/:tab`), `composerDrafts.js`, `firstChatPrefs.js`, `i18n.js` + `locales/{en,fr}.json`.

## Shell / views

| Component | Role |
|-----------|------|
| `App.vue` | Root: auth gate → `LoginView` or `HubView`; boots locale + events. Hub toasts sit top-right; click dismisses. |
| `views/LoginView.vue` | Password login / forced password change. |
| `views/HubView.vue` | App chrome: bot rail, search, stage tabs (discussion / terminal / screen), split, inspector panels, mobile master–detail. Keeps `ScreenPane` mounted off-tab so noVNC stays alive. |

## Stage panes (per bot)

| Component | Role | Feature note |
|-----------|------|----------------|
| `ChatPane.vue` | Conversation thread (newest page first, older pages on scroll up), composer, queue « En file » (Envoyer maintenant on the first bubble, Éditer puts the text back, ArrowUp in an empty field recalls the newest queued text), Relancer bar, token pill, markdown, attachments, @mentions. Hosts chat cards. LLM turns always fold into tool groups as Réflexion rows; orb shows phase + elapsed. A notebook save is a centred notebook card (« Added to notebook · … »), not a tool card. | [`pi-agent.md`](./pi-agent.md), [`chat-files.md`](./chat-files.md), [`composer-drafts.md`](./composer-drafts.md), [`token-usage.md`](./token-usage.md), [`notebook.md`](./notebook.md) |
| `TerminalPane.vue` | xterm.js + PTY WebSocket. | [`terminal-pty.md`](./terminal-pty.md) |
| `ScreenPane.vue` | noVNC desktop frame. Sleep stays asleep until **Wake**; control holds the idle clock at zero. Switching bots drops the previous desktop and connects to the selected one. | [`desk-screen.md`](./desk-screen.md) |
| `WorkingOrb.vue` | Thinking-orbs canvas (send button / in-thread wait). Orb label shows phase + elapsed. | [`pi-agent.md`](./pi-agent.md) |
| `ToolGroup.vue` | Grouped tool cards. Folded bar shows **Grounding · N** when the group called `vm_ground`. Open list includes the loop lines, **Réflexion** LLM rows, and mid-run assistant asides (`run_text`) in `created_at` order — not a separate `run_progress` stack (that flashed a full bubble then shrank). Never fold image markdown or `GUARD:CONTINUE`/`STOP` into `run_text` (those stay centred guard cards); while busy with no later item yet, treat other asides as `run_text` to avoid the flash. Absorb a post-bubble llm-only group back into the tools above. User-facing desk captures (`vm_screenshot`): the **bot pastes** share markdown into its assistant bubble (host does not auto-inject). When the tool group is folded, a preview of the latest non-grounding shot may still sit under the summary bar; when the list is open, it is nested under the `vm_screenshot` row. Running-tool row head is a `div` (not a `<button>`) so **Arrêter l’outil** can sit in the same flex row without nested-button layout breakage. Live `vm_terminal_exec` duration shows **elapsed / timeout** (e.g. `26s / 30s`). | [`pi-agent.md`](./pi-agent.md), [`grounding.md`](./grounding.md), [`agent-vm-screenshot.md`](./agent-vm-screenshot.md) |

## Inspector panes

| Component | Role | Feature note |
|-----------|------|----------------|
| `DetailsPane.vue` | Bot details: model, capability, memory, thinking level select (Pi off→max), notebook (eye opens a read-only dialog), manager, companion, MCP, package size, manage actions. | [`bots-create.md`](./bots-create.md), [`bot-package.md`](./bot-package.md), [`manager.md`](./manager.md), [`companion.md`](./companion.md), [`notebook.md`](./notebook.md), [`pi-agent.md`](./pi-agent.md) |
| `LibraryPane.vue` | Files / `~/files` (private per bot): list, sizes, DnD upload/move, click=download, delete arm→check. | [`files-shared.md`](./files-shared.md) |
| `EventsPane.vue` | Schedules + webhooks list (pause / copy curl / delete confirm). | [`events.md`](./events.md) |
| `EventInstructionModal.vue` | Large modal: standing instruction, plus the webhook POST body when opened from a chat bubble. | [`events.md`](./events.md) |
| `ManageMenu.vue` | Details manage list: clear chat, export PDF, desk restart/reset/remove, delete bot (arm → check). | [`chat-export-pdf.md`](./chat-export-pdf.md), [`bots-create.md`](./bots-create.md) |
| `BotCompanion.vue` | Companion transfer toggle + device status. | [`companion.md`](./companion.md) |
| `BotMcpGrants.vue` | Per-bot MCP grant checkboxes. | [`companion.md`](./companion.md) |

## Chat cards (inline in `ChatPane` thread)

| Component | Role | Feature note |
|-----------|------|----------------|
| `VaultRequestCard.vue` | Vault credential / access form. | [`vault.md`](./vault.md) |
| `ApprovalCard.vue` | Accept / Decline (`ask_approval`). | [`approval.md`](./approval.md) |
| `ClarifyCard.vue` | Structured question (`ask_clarify`). | [`clarify.md`](./clarify.md) |
| `MemoryProposalCard.vue` | Non-blocking memory proposal. | [`memory.md`](./memory.md) |
| `DeskRequestCard.vue` | Agent asked for a desktop (Allow / Decline). | [`desk-screen.md`](./desk-screen.md) |
| `AgentResumeCard.vue` | Manual Resume fallback after interrupt (rare; server auto-resumes first). | [`pi-agent.md`](./pi-agent.md) |
| `BotDeleteCard.vue` | Manager household delete checkboxes. | [`household.md`](./household.md) |

The guard-rail line and the Pi compaction line are not separate components. `ChatPane` renders both as centred cards (`meta.kind` `guard` or `compaction`). Compaction detail may show reason, optional « N passes » when chunked, and token counts. LLM turns are always rows inside `ToolGroup`. See [`pi-agent.md`](./pi-agent.md).

## Modals / overlays

| Component | Role | Feature note |
|-----------|------|----------------|
| `CreateBotModal.vue` | Create bot (label → slug, model). | [`bots-create.md`](./bots-create.md) |
| `CreateDeskModal.vue` | Manual desk create / replace job progress. | [`desk-screen.md`](./desk-screen.md) |
| `AvatarEditModal.vue` | Pick companion animal + colour. | [`avatars.md`](./avatars.md) |
| `SettingsModal.vue` | Full settings page (Générale, LLM, Grounding, Consumption, vault, memory, companions…). | [`llm-settings.md`](./llm-settings.md), [`auth-secrets.md`](./auth-secrets.md) |
| `SettingsMenu.vue` | Rail orb: open settings / logout. | [`ui-design-system.md`](./ui-design-system.md) |

## Settings / setup pieces

| Component | Role | Feature note |
|-----------|------|----------------|
| `LlmSettings.vue` | Settings → LLM: four cards (default model, providers, models, other models). Model cards include default thinking + per-model parallel / large-request concurrency. | [`llm-settings.md`](./llm-settings.md) |
| `GroundingSettings.vue` | Settings → grounding / UI-TARS keys. | [`grounding.md`](./grounding.md) |
| `TokenUsageChart.vue` | Settings → Consumption. Chart on a wide screen; under 760px a day bar and a table of that day’s totals. | [`token-usage.md`](./token-usage.md) |
| `SetupPanel.vue` | First-run checklist + updates + first chat CTA (home). | [`setup.md`](./setup.md), [`updates.md`](./updates.md) |
| `SetupItem.vue` / `SetupField.vue` | Checklist row / grounding field helpers. | [`setup.md`](./setup.md) |
| `SecretInput.vue` | Password-style field with show/hide. | — |
| `LocalePicker.vue` / `LocaleFlag.vue` | Language switcher + flag glyphs. | — |

## Avatars / pickers

| Component | Role | Feature note |
|-----------|------|----------------|
| `BotAvatar.vue` | Rail / details companion badge (states + custom tip on `lg`). | [`avatars.md`](./avatars.md) |
| `ModelPicker.vue` | Bot model dropdown (wraps `MenuSelect`). | [`llm-settings.md`](./llm-settings.md) |
| `ModelCombo.vue` | Free-text combobox + suggestions (Settings timezone; reusable for model ids). | [`llm-settings.md`](./llm-settings.md) |
| `MenuSelect.vue` | Shared custom select (no native `<select>`). | [`ui-design-system.md`](./ui-design-system.md) |

## Soft UI primitives (`components/ui/`)

Prefer these for new chrome. Re-exported from `components/ui/index.js`.

| Component | Role |
|-----------|------|
| `UiButton.vue` | Soft button variants (`variant`, `to` / `href` for links) — prefer over raw `.btn` everywhere. |
| `UiOrb.vue` | 28px round inspector button (MCP add, notebook eye). |
| `UiCard.vue` | Settings / section card with optional icon slot. |
| `UiIcon.vue` | Named SVG icons (`spark`, `memory`, `puzzle`, `eye`, `trash`, …). |
| `UiIconBadge.vue` | Icon in soft badge (inspector rows, settings nav). |
| `UiIconButton.vue` | Icon-only soft button (`default` / `file` / `compact` / `chrome`) — vault, Events, Hub chrome, Files. |
| `UiToggleRow.vue` | Title + hint + switch; **custom tooltip** on the switch (`tip` / `disabledReason`) — never browser `title` for that tip. |
| `UiSwitch.vue` | Switch alone (optional `compact`) — Events rows, inline companion notify. |
| `UiActionConfirm.vue` | Arm→check confirm control (check icon + tip) — ManageMenu, Files, Settings delete-all / vault. |
| `UiModal.vue` | Teleport + backdrop + panel (`as="form"` supported, Escape / backdrop close) — Create*/Avatar/Event/MCP/notebook. |

Shared patterns: chat request cards share `.chat-request-card` (+ head / state / actions); Soft checkboxes use `.ui-check` (BotDeleteCard); **custom tips** (`.bot-avatar-tip`, `.chat-token-tip`, `.file-row-tip`, `.ui-toggle-tip`). `MenuSelect` `compact` = Hub split pane pickers.

## Pitfalls / non-regressions

- Do **not** add a parallel Files/Chat/Settings implementation — extend the components above.
- UI strings → `frontend/src/locales/{en,fr}.json` only.
- After Vue/CSS edits with `serve --dev`, wait for `vite build --watch` → `autonomous/static/`.
- New reusable chrome → `components/ui/*` + a line in this catalogue **and** [`ui-design-system.md`](./ui-design-system.md) when the design system changes.
- Chat cards stay centred/thread-scoped; don't turn them into inspector panes without a product reason.

## Quick check

```bash
ls frontend/src/components/*.vue frontend/src/components/ui/*.vue frontend/src/views/*.vue
# After UI work: serve --dev, hard-refresh, exercise the touched pane.
# 2026-11-19 Soft factor: create-bot modal, Hub split MenuSelect compact, npm run build OK.
```
