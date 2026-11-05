# Shared memory (common to bots)

**Status**: in place  
**Key files**: `autonomous/services/memory.py`, `autonomous/api/memory_routes.py`, `autonomous/migrations/001_schema.sql`, `autonomous/pi_extensions/memory.ts`, `autonomous/services/{agent,pi_rpc,bots}.py`, `frontend/src/components/{MemoryProposalCard,SettingsModal,CreateBotModal,DetailsPane,ChatPane}.vue`  
**Last updated**: 2026-11-03 (setup auto-approve via first_chat_onboarding)

## User behaviour

- A **global memory** shared by all authorised bots (not a per-bot memory), distinct from the vault (no secrets).
- Two levels:
  - **Always read (`core`)** — facts / rules that are **always important**: identity (first name), lasting instructions ("always ask for my OK before a command"). Loaded **once** into the system prompt when a conversation opens.
  - **On demand (`browse`)** — **situational** details: tastes, raclette, address, hobbies… via `memory_list` / `get` / `search`. When in doubt → browse.
- **Per-bot opt-out**: checkbox at creation + toggle in Details (`bots.memory_access`, default on). Without access: no core block, tools refused (`memory_denied`).
- The agent **does not write** directly: `memory_propose` creates a **green chat card** (same template/width as vault & tools, distinct from a tool) with **Confirm / Decline**. **Non-blocking** — the bot stays `busy` / carries on (no `waiting`, unlike the vault).
- **Exception — first-chat setup**: while `settings.first_chat_onboarding` is true, `memory_propose` writes immediately (state `approved`, **no card**) so the init clarify sequence stays fluid.
- `memory_*` calls are **fully hidden** from the thread (no `🔧 memory_propose` bubble, no tool line) — agent side (`_HIDDEN_TOOL_CARDS`) + frontend (`isHiddenTool`). Only the `memory_proposal` card remains.
- In **Settings**: list of entries and deletion. No add form — the bot proposes a fact (`memory_propose`), the user confirms in the chat.

## Agent flow

1. User: "call me Alex".
2. Bot → `memory_propose({ action: "set", key: "preferred_name", value: "Alex", tier: "core" })`.
3. Card in the chat; the tool immediately answers "carry on, don't poll".
4. The user confirms → entry saved. If `core`: visible in the system prompt from the **next** conversation. If `browse`: tools right away.
5. The agent proposes `core` for identity + lasting behaviour rules; `browse` for the rest (tastes, trivia).

## API

| Method | Path | Role |
|---------|--------|------|
| GET/POST | `/api/v1/memory/entries` | List / upsert (admin). `?bot=` forces the access check |
| GET/DELETE | `/api/v1/memory/entries/<key>` | Read / delete |
| GET | `/api/v1/memory/search?q=` | Search |
| POST | `/api/v1/memory/proposals` | Agent proposal |
| POST | `/api/v1/memory/proposals/<id>/resolve` | `approve` \| `deny` |

Bot creation: `memory_access` (bool, default true). Same for bot patch.

## Pitfalls

- A `core` fact approved **mid-conversation** only enters the system prompt at the **next** conversation (Clear history / new `pi_session_id`). The `memory_*` tools see it right away.
- **Don't** re-inject the core block on every `session.prompt` — only at `PiRpcSession.start()` via `--append-system-prompt`.
- Keys: `^[a-z][a-z0-9_]{0,63}$`.
- Proposals stored with `bots.id` (UUID); chat messages stay on the slug.
- Don't confuse with the **vault** (secrets + `waiting`) or with **Pi compaction** (local session context).
- No add form in Settings. The entry comes through the chat card (`memory_propose`). The list and the bin remain. `POST /memory/entries` remains for card approval.
- Don’t show Confirm cards during setup onboarding (`first_chat_onboarding`).
