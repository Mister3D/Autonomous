# Features — implementation details

Short notes for an agent picking things up cold. Parent index: [`../README.md`](../README.md).

| Note | Content |
|-------|---------|
| [desk-screen.md](./desk-screen.md) | noVNC, frame, control, geometry |
| [terminal-pty.md](./terminal-pty.md) | xterm + `/ws/terminal/<bot>` |
| [files-shared.md](./files-shared.md) | Files panel / `~/shared` |
| [agent-files.md](./agent-files.md) | Agent `files_*` without host shell |
| [routing-tabs.md](./routing-tabs.md) | Tab URLs |
| [serve-dev.md](./serve-dev.md) | serve / stop / --dev / Mux |
| [chrome-desktop-image.md](./chrome-desktop-image.md) | Docker image + Chrome flags |
| [pi-agent.md](./pi-agent.md) | Host-side Pi agent, sessions, chat streaming |
| [token-usage.md](./token-usage.md) | ↑↓ conversation token counter |
| [vault.md](./vault.md) | Global vault, grants, chat forms (kept out of the LLM) |
| [memory.md](./memory.md) | Shared memory: core 1×/conversation, browse, opt-out |
| [approval.md](./approval.md) | User approval Accept / Decline (`ask_approval`) |
| [clarify.md](./clarify.md) | Structured question (`ask_clarify`, choices or short text) |
| [agent-vm-terminal.md](./agent-vm-terminal.md) | Pi agent → server VM terminal |
| [agent-vm-screenshot.md](./agent-vm-screenshot.md) | Pi agent → VM desktop screenshot |
| [grounding.md](./grounding.md) | UI-TARS + multimodal judge (geometry only) |
| [browser-nav.md](./browser-nav.md) | CDP web nav + VNC scroll (generic) |
| [botmail.md](./botmail.md) | Tell / Ask @bot, queue, follow-up |
| [bots-create.md](./bots-create.md) | Slug identifier, 422, CreateBotModal |
| [bot-package.md](./bot-package.md) | Package size in Details (VM + files + chat) |
| [chat-files.md](./chat-files.md) | Attach files (picker + drop → ~/shared/upload) |
| [composer-drafts.md](./composer-drafts.md) | Per-bot composer drafts (sessionStorage, per tab) |
| [events.md](./events.md) | UTC cron + webhooks, Events inspector |
| [chat-search.md](./chat-search.md) | FTS + NL message search, `?msg=` deep-link |
| [chat-export-pdf.md](./chat-export-pdf.md) | Export discussion PDF (tool names, no details) |
| [reactions.md](./reactions.md) | Bot emoji on the user's bubble (`react`) |
| [avatars.md](./avatars.md) | SVG companion badges (states + Vue package) |
| [manager.md](./manager.md) | Orchestrator Manager (peers + bot_delegate) |
| [household.md](./household.md) | Manager create/delete bots + default LLM |
| [companion.md](./companion.md) | PC companion: pairing, Internet, MCP |
| [setup.md](./setup.md) | First-run checklist + first conversation CTA |
| [updates.md](./updates.md) | Self-update channel + home Check/Update + restart |
| [auth-secrets.md](./auth-secrets.md) | Session secret ≠ Bearer, TRUST_PROXY, companion pre-101 |
| [ui-design-system.md](./ui-design-system.md) | Soft UI design system, reusable UI primitives, settings cards |
| [vue-components.md](./vue-components.md) | Full Vue catalogue (HubView, panes, chat cards, modals, `ui/*`) |
