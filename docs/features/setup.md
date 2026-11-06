# First-run setup

**Status**: in place  
**Key files**: `autonomous/services/setup.py`, `autonomous/api/setup_routes.py`, `frontend/src/components/SetupPanel.vue`, `frontend/src/components/SetupItem.vue`, `frontend/src/store.js` (`setupReady`, `refreshSetup`)  
**Last updated**: 2026-11-06 (desk image builds on serve start, not during install.sh)

## User behaviour

- After login, the home page (`/` or `/setup`) lists what is left to install or configure.
- **Required**: Pi agent, language model (vision), Docker, desktop image. Creating a bot stays locked until these are OK (`setup.ready`).
- **Optional**: grounding (UI-TARS), companion app binary.
- Each row has Configure / Install / Build as needed; jobs stream a live log.
- At the **bottom** of the checklist: **Start the setup conversation** / **Lancer la conversation d’initialisation**. Greyed out until every required item is ready; then primary and clickable.
- The CTA is visible **if and only if** shared memory has **0 entries**. No other flag hides it (`first_chat_done` / `first_chat_prefs_pending` are cleared when memory is empty).
- When the last required item flips to OK, the checklist stays open (so the button remains visible if still relevant).
- Clicking the button: creates/opens **Assistant**, navigates immediately, sends a short bubble + language-only prompt (`ask_clarify` Français | English, plus free text for other languages), sets `first_chat_prefs_pending`. After the user picks a language, the UI **sends a second message** (prefs script in that language — FR/EN templates, or a translate-into-{lang} script for others like German) and sets `first_chat_done`. First bot is always **Manager**, avatar **renard**, colour swatch **0**. If another Manager already exists, it is demoted.
- On the ready home (tagline "Your bots. Your desktop."), the same button is shown as a CTA above the setup link (same hide rules). Arriving on `/` never auto-opens a bot from the rail — see [routing-tabs.md](./routing-tabs.md).

## Implementation

- Gate: `setupReady()` → `state.setup.ready` or `gate === false`.
- Phase 1: `setup.firstChatVisible` + `setup.firstChatLanguageScript` via `prompt`; sets `first_chat_prefs_pending` = bot slug only. Scripts are read with `rawMessage()` (not `t()`), because vue-i18n treats `|` as plural separators and would send only one choice fragment to the agent.
- Phase 2: `ClarifyCard` → `maybeContinueFirstChatPrefs` accepts any language answer (FR/EN templates, or `setup.firstChatScriptOther` with `{lang}`). Clears pending, sets `first_chat_done` + UI `locale` (fr/en only), sends the prefs message (also via `rawMessage`).
- Stuck recovery: if memory has entries and `first_chat_prefs_pending` with `preferred_language`, `resumeFirstChatPrefsIfStuck` sends phase 2 automatically.
- Gate refresh: memory length drives the CTA; empty memory clears `first_chat_done` + `first_chat_prefs_pending`.
- Prefs script: product tour then fixed `ask_clarify` (name, control, notifications, done) with `memory_propose` after each answer. During setup (`first_chat_onboarding=true`), `memory_propose` **saves immediately** with no Confirm card so the flow stays fluid; the flag clears once `preferred_name` and `work_style`/`notify_preference` exist (or memory is emptied).
- Optimistic local message + navigate before HTTP; merge-safe `loadMessages` so a concurrent fetch cannot wipe the bubble.

## Installer (`install.sh`)

- Does **not** build the desk image (no prompt). Final message leads with the LAN URL when a non-loopback IPv4 is detected (e.g. `http://192.168.0.127:8787/`), otherwise `http://127.0.0.1:$PORT/`. With a LAN IP the systemd unit binds `0.0.0.0` and sets `AUTONOMOUS_BIND_PUBLIC=1`.
- Desk image: on `autonomous serve` startup, `desk_image_build.start_background` builds `autonomous-desktop:latest` if missing or if `docker/desktop/` source hash changed (~10 min). Log `$AUTONOMOUS_HOME/desk-image/build.log`. Disable with `AUTONOMOUS_DESK_IMAGE_BUILD=0`. Setup UI can still force a rebuild via the `desk_image` job.

## Pitfalls / non-regressions

- Don’t enable the button on optional-only gaps: only `setup.ready` (required).
- Don’t prompt for a desk image build in `install.sh` — serve owns that.
- Don’t hide the CTA for any reason other than « memory has ≥ 1 entry ».
- Don’t skip `memory_access` on the auto-created Assistant bot.
- First bot profile: `is_manager=true`, `avatar=renard`, `avatar_color=0` (Original). Don’t pick a random unused character.
- Don’t leave the agent silent after a non-FR/EN language: phase 2 must still fire (any non-empty language answer while pending).
- Don’t load onboarding scripts through `t()` when they contain `|` (clarify choices) — use `rawMessage` / `getLocaleMessage`.
- A literal `@` in i18n must be written `{'@'}`.

## Quick check

Empty memory → CTA visible. Any memory entry → CTA hidden. Stale pending with 0 memories is cleared on refresh.
