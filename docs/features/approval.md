# User approval (Accept / Decline)

**Status**: in place  
**Key files**: `autonomous/services/approvals.py`, `autonomous/api/approval_routes.py`, `autonomous/migrations/001_schema.sql`, `autonomous/pi_extensions/approval.ts`, `frontend/src/components/{ApprovalCard,ChatPane}.vue`  
**Last updated**: 2026-10-31

## User behaviour

- The agent can call **`ask_approval`** to display a **chat card** with **Accept** / **Decline**.
- **Blocking**: the bot goes into `waiting`; the tool polls until the answer (like the vault).
- Use case: before a risky command / action, especially if a **core memory** rule says to ask for consent.
- Chat message during `waiting`: cancels the request (`cancelled` + `human_redirect`) — this is **not** a hard refusal; the agent follows the message.
- The tool call is **hidden** from the thread (no 🔧 dump) — only the card remains.

## API

| Method | Path | Role |
|---------|--------|------|
| POST | `/api/v1/approvals/requests` | `{bot, prompt, title?}` |
| GET | `/api/v1/approvals/requests/:id` | Poll state |
| POST | `/api/v1/approvals/requests/:id/resolve` | `{action: approve\|deny}` |

## Pitfalls

- Distinct from **clarify** (`ask_clarify` = structured question, not a yes/no), from **memory** (`memory_propose` = non-blocking) and from the **vault** (secret forms).
- Pi session dies while waiting → `mark_interrupted_after_wait` **auto-resumes** (Resume card only if retry cannot start).
