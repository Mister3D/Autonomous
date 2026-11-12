# First-run setup

**Status**: in place  
**Key files**: `autonomous/services/setup.py`, `autonomous/api/setup_routes.py`, `frontend/src/components/SetupPanel.vue`, `frontend/src/components/SetupItem.vue`, `frontend/src/store.js` (`setupReady`, `refreshSetup`)  
**Last updated**: 2026-11-13 (home update row stays put and its refresh icon spins)

## User behaviour

- After login, the home page (`/` or `/setup`) lists what is left to install or configure.
- **Required**: Pi agent, language model (vision), Docker, desktop image. Creating a bot stays locked until these are OK (`setup.ready`).
- **Optional**: grounding (UI-TARS), companion app binary, **web search** (`pi install npm:pi-web-access` → tools `web_search` / `fetch_content`).
- Each row has Configure / Install / Build as needed; jobs stream a live log (same dark CLI panel as updates). Companion builds started in the background by `serve` also stream via `GET /companion/build` → `log`.
- Checklist toolbar (**Recheck** / **Back to home**) is centered under the intro.
- At the **bottom** of the checklist: **Start the setup conversation** / **Lancer la conversation d’initialisation** (centered with its hint). Greyed out until every required item is ready; then primary and clickable.
- The CTA is hidden while the memory check is in flight, and stays hidden when shared memory has **at least one entry** or a memory proposal is still **pending**. It shows only when both are empty. `first_chat_done` / `first_chat_prefs_pending` are cleared only in that empty case.
- When the last required item flips to OK, the checklist stays open (so the button remains visible if still relevant).
- Clicking the button: creates/opens **Assistant**, navigates immediately, sends a short bubble + language-only prompt (`ask_clarify` Français | English). The free-text field is always shown on that card, even if the agent omits `allow_text`. Sets `first_chat_prefs_pending`. After the user picks a language, the UI **sends a second message** (prefs script in that language — FR/EN templates, or a translate-into-{lang} script for others like German) and sets `first_chat_done`. First bot is always **Manager**, avatar **renard**, colour swatch **0**. If another Manager already exists, it is demoted.
- On `/`, the welcome home is shown immediately, including while the setup status request is still in flight. The checklist appears only once that status says something required is missing, or on `/setup`.
- On the ready home (tagline "Your bots. Your desktop."), a welcome line, the same button (pill, chat icon) and the fox illustration sit above a status card. When the button is hidden, a short greeting replaces it (`home.greeting`). The card title is the setup link. The checklist at `/setup` stays the plain list. Arriving on `/` never auto-opens a bot from the rail — see [routing-tabs.md](./routing-tabs.md).
- The card’s first row is `Autonomous - {branch} - {version}`. On the right: a refresh icon, then a green **Up to date** pill. A refresh forces `POST /setup/update/check`. That row stays on screen for the whole check (last channel, version, and pill); the refresh icon spins. The button is not `disabled` during the check — a disabled control does not animate — repeat clicks are ignored in the handler. When the branch is behind and the remote `__version__` differs, the row appends `→ {latest}` (same arrow as a module jump) and the pill is replaced by **Update**. A dirty or diverged tree shows **Force** on that row. Dirty tree, fetch failure, and the apply log stay under that row.
- Under it, each Pi install and each `npm:` plugin in `~/.pi/agent/settings.json` is the same kind of row: `{name} - {version}`, refresh, green pill. A newer release appends `→ {latest}` and puts **Update** on that row only (`pi update --self` or `pi update <source>`). Refresh rechecks the whole Pi list (cached 6 hours unless forced).
- While the checklist is open, the update card stays at the bottom so an update can be applied before setup is finished.

## Implementation

- Gate: `setupReady()` → `state.setup.ready` or `gate === false`.
- Phase 1: `setup.firstChatVisible` + `setup.firstChatLanguageScript` via `prompt`; sets `first_chat_prefs_pending` = bot slug only. Scripts are read with `rawMessage()` (not `t()`), because vue-i18n treats `|` as plural separators and would send only one choice fragment to the agent.
- Phase 2: `ClarifyCard` → `maybeContinueFirstChatPrefs` accepts any language answer (FR/EN templates, or `setup.firstChatScriptOther` with `{lang}`). Clears pending, sets `first_chat_done` + UI `locale` (fr/en only), sends the prefs message (also via `rawMessage`).
- Stuck recovery: if memory has entries and `first_chat_prefs_pending` with `preferred_language`, `resumeFirstChatPrefsIfStuck` sends phase 2 automatically.
- Gate refresh: saved entries **or** `GET /memory/proposals/count` > 0 hide the CTA. The line stays off until that check returns. Empty memory and zero pending proposals clear `first_chat_done` + `first_chat_prefs_pending`.
- Prefs script: product tour then fixed `ask_clarify` (name, control, notifications, done) with `memory_propose` after each answer. During setup (`first_chat_onboarding=true`), `memory_propose` **saves immediately** with no Confirm card so the flow stays fluid; the flag clears once `preferred_name` and `work_style`/`notify_preference` exist (or memory is emptied).
- Optimistic local message + navigate before HTTP; merge-safe `loadMessages` so a concurrent fetch cannot wipe the bubble.

## Installer (`install.sh`)

- Does **not** build the desk image (no prompt). Final message leads with the LAN URL when a non-loopback IPv4 is detected (default route src → global `ip addr` skipping docker0 → `hostname -I`). Example: `http://192.168.0.127:8787/`. Fallback only: `http://127.0.0.1:$PORT/`. With a LAN IP the systemd unit binds `0.0.0.0` and sets `AUTONOMOUS_BIND_PUBLIC=1`. Installer logs `LAN address detected: …` when it works.
- Desk image: on `autonomous serve` startup, `desk_image_build.start_background` builds `autonomous-desktop:latest` if missing or if `docker/desktop/` source hash changed (~10 min). Log `$AUTONOMOUS_HOME/desk-image/build.log`. Disable with `AUTONOMOUS_DESK_IMAGE_BUILD=0`. Setup UI can still force a rebuild via the `desk_image` job.

## Pitfalls / non-regressions

- Don’t enable the button on optional-only gaps: only `setup.ready` (required).
- Don’t hide or replace the home update row while a check is in flight, and don’t put `disabled` on its refresh button — the icon must keep spinning on the same line.
- Don’t prompt for a desk image build in `install.sh` — serve owns that.
- Don’t hide the CTA for any reason other than « memory has ≥ 1 entry » or « a memory proposal is still pending ». Don’t show it before that check returns.
- Don’t skip `memory_access` on the auto-created Assistant bot.
- First bot profile: `is_manager=true`, `avatar=renard`, `avatar_color=0` (Original). Don’t pick a random unused character.
- Don’t leave the agent silent after a non-FR/EN language: phase 2 must still fire (any non-empty language answer while pending).
- Don’t load onboarding scripts through `t()` when they contain `|` (clarify choices) — use `rawMessage` / `getLocaleMessage`.
- A literal `@` in i18n must be written `{'@'}`.

## Quick check

Empty memory and no pending proposal → CTA visible. Any saved entry or pending proposal → CTA hidden. Stale `first_chat_done` with 0 memories and 0 pending proposals is cleared on refresh.
