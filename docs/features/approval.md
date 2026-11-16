# User approval (Accept / Decline)

**Status**: in place  
**Key files**: `autonomous/services/approvals.py`, `autonomous/api/approval_routes.py`, `autonomous/migrations/001_schema.sql`, `autonomous/pi_extensions/approval.ts`, `frontend/src/components/{ApprovalCard,ChatPane}.vue`  
**Last updated**: 2026-11-16 (indefinite blocking wait; composer queues without cancelling)

## User behaviour

- The agent can call **`ask_approval`** to display a **chat card** with **Accept** / **Decline**.
- **Blocking**: the bot goes into `waiting`; the tool polls without a deadline until the answer (like the vault).
- Use case: before a risky command / action, especially if a **core memory** rule says to ask for consent.
- While the card is pending, the agent stays blocked with no elapsed-time expiry. Composer messages and attachments still go to the FIFO queue; they do not cancel the card. Only Accept, Decline, or stopping the bot ends the wait.
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
- Never add a human-response timeout or let a chat message cancel the pending card.
