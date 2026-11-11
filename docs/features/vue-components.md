# Vue components catalogue

**Status**: in place  
**Key files**: `frontend/src/{App,main,router,store,sync,api,i18n}.js|vue`, `frontend/src/views/*`, `frontend/src/components/**`  
**Last updated**: 2026-11-11 (event modal also shows the webhook body)

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
        ├── LibraryPane.vue   # Files / ~/shared
        └── EventsPane.vue
```

Supporting modules (not components, but always nearby): `store.js` (reactive state + SSE apply), `sync.js` (EventSource), `api.js` (HTTP), `router.js` (`/b/:name/:tab`), `composerDrafts.js`, `firstChatPrefs.js`, `i18n.js` + `locales/{en,fr}.json`.

## Shell / views

| Component | Role |
|-----------|------|
| `App.vue` | Root: auth gate → `LoginView` or `HubView`; boots locale + events. |
| `views/LoginView.vue` | Password login / forced password change. |
| `views/HubView.vue` | App chrome: bot rail, search, stage tabs (discussion / terminal / screen), split, inspector panels, mobile master–detail. Keeps `ScreenPane` mounted off-tab so noVNC stays alive. |

## Stage panes (per bot)

| Component | Role | Feature note |
|-----------|------|----------------|
| `ChatPane.vue` | Conversation thread, composer, queue « En file » (Envoyer maintenant on the first bubble, Éditer puts the text back), Relancer bar, token pill, markdown, attachments, @mentions. Hosts chat cards. | [`pi-agent.md`](./pi-agent.md), [`chat-files.md`](./chat-files.md), [`composer-drafts.md`](./composer-drafts.md), [`token-usage.md`](./token-usage.md) |
| `TerminalPane.vue` | xterm.js + PTY WebSocket. | [`terminal-pty.md`](./terminal-pty.md) |
| `ScreenPane.vue` | noVNC desktop frame, wake/create desk. | [`desk-screen.md`](./desk-screen.md) |
| `WorkingOrb.vue` | Thinking-orbs canvas (send button / in-thread wait). | [`pi-agent.md`](./pi-agent.md) |
| `ToolGroup.vue` | Grouped tool cards (compact live line, live elapsed time, stop-tool button, expandable history). | [`pi-agent.md`](./pi-agent.md) |

## Inspector panes

| Component | Role | Feature note |
|-----------|------|----------------|
| `DetailsPane.vue` | Bot details: model, capability, memory, manager, companion, MCP, package size, manage actions. | [`bots-create.md`](./bots-create.md), [`bot-package.md`](./bot-package.md), [`manager.md`](./manager.md), [`companion.md`](./companion.md) |
| `LibraryPane.vue` | Files / `~/shared`: list, sizes, DnD upload/move, click=download, delete arm→check. | [`files-shared.md`](./files-shared.md) |
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

## Modals / overlays

| Component | Role | Feature note |
|-----------|------|----------------|
| `CreateBotModal.vue` | Create bot (label → slug, model). | [`bots-create.md`](./bots-create.md) |
| `CreateDeskModal.vue` | Manual desk create / replace job progress. | [`desk-screen.md`](./desk-screen.md) |
| `AvatarEditModal.vue` | Pick companion animal + colour. | [`avatars.md`](./avatars.md) |
| `SettingsModal.vue` | Full settings page (Générale, LLM, Grounding, Tokens, vault, memory, companions…). | [`llm-settings.md`](./llm-settings.md), [`auth-secrets.md`](./auth-secrets.md) |
| `SettingsMenu.vue` | Rail orb: open settings / logout. | [`ui-design-system.md`](./ui-design-system.md) |

## Settings / setup pieces

| Component | Role | Feature note |
|-----------|------|----------------|
| `LlmSettings.vue` | Settings → LLM providers & models. | [`llm-settings.md`](./llm-settings.md) |
| `GroundingSettings.vue` | Settings → grounding / UI-TARS keys. | [`grounding.md`](./grounding.md) |
| `TokenUsageChart.vue` | Settings → Tokens history chart. | [`token-usage.md`](./token-usage.md) |
| `SetupPanel.vue` | First-run checklist + updates + first chat CTA (home). | [`setup.md`](./setup.md), [`updates.md`](./updates.md) |
| `SetupItem.vue` / `SetupField.vue` | Checklist row / grounding field helpers. | [`setup.md`](./setup.md) |
| `SecretInput.vue` | Password-style field with show/hide. | — |
| `LocalePicker.vue` / `LocaleFlag.vue` | Language switcher + flag glyphs. | — |

## Avatars / pickers

| Component | Role | Feature note |
|-----------|------|----------------|
| `BotAvatar.vue` | Rail / details companion badge (states + custom tip on `lg`). | [`avatars.md`](./avatars.md) |
| `ModelPicker.vue` | Bot model dropdown (wraps `MenuSelect`). | [`llm-settings.md`](./llm-settings.md) |
| `ModelCombo.vue` | Free-text + suggestions model field (settings). | [`llm-settings.md`](./llm-settings.md) |
| `MenuSelect.vue` | Shared custom select (no native `<select>`). | [`ui-design-system.md`](./ui-design-system.md) |

## Soft UI primitives (`components/ui/`)

Prefer these for new chrome. Re-exported from `components/ui/index.js`.

| Component | Role |
|-----------|------|
| `UiButton.vue` | Soft button variants. |
| `UiCard.vue` | Settings / section card with optional icon slot. |
| `UiIcon.vue` | Named SVG icons (`spark`, `memory`, `puzzle`, …). |
| `UiIconBadge.vue` | Icon in soft badge (inspector rows, settings nav). |
| `UiToggleRow.vue` | Title + hint + switch; **custom tooltip** on the switch (`tip` / `disabledReason`) — never browser `title` for that tip. |

Shared patterns (not separate files): **arm → check** confirm (`.action-confirm` + `.action-confirm-tip`) in `ManageMenu`, Settings delete-all, Files delete; **custom tips** (`.bot-avatar-tip`, `.chat-token-tip`, `.file-row-tip`, `.ui-toggle-tip`).

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
```
