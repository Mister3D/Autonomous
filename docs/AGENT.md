# Agent rules (details)

Complement to [`README.md`](./README.md) (the README remains the **first** file to open).

## Obligations

1. **Read** `docs/README.md` then the `features/` notes for the topic.
2. **Document** every behaviour change in `docs/features/` (even a "small" one).
3. HTTP API changed → also `docs/API.md` (summary); runtime truth = `/api/openapi.json`.
4. Doc backlog: if tasks had already been given → catch up on the notes before piling on new vague work.

## `features/*.md` note format

```markdown
# Title

**Status**: in place | partial | obsolete  
**Key files**: …  
**Last updated**: YYYY-MM-DD

## User behaviour
## Implementation
## Pitfalls / non-regressions
## Quick check
```

## Product reminders

- French.
- No package installs (`apt`/`pip`/global npm…) without agreement.
- No PowerShell without permission.

## Testing (mandatory — this is not prod)

This repo runs in **local dev**. After every behaviour change (API, service, UI):

1. **Run the modified program** (not a separate throwaway script): targeted `pytest` if it exists, otherwise `curl` / UI on `serve --dev`.
2. Reproduce the relevant **user path** (e.g. create a bot, tick Manager, patch Details).
3. If it breaks: fix it **before** saying it's fine. Don't settle for "it compiles".
4. Record the check in the `features/` note ("Quick check" section).

Skip a test only if it is truly impossible (no binary, external dependency down) — and tell the user explicitly.

## Forbidden

- Reinventing an already documented flow without reading the note.
- UX fix only in the chat, with no trace in `docs/features/`.
- Confusing the `docker/desktop/` sources with the binary **inside** the container (often stale).
- Writing secrets at the repo root (`TOKEN`, `.env` with keys, copies of `data/token`). Every secret → `$AUTONOMOUS_HOME` (see `SECURITY.md`).
- Shipping a feature / fix **without having exercised it** (API or UI) while `serve --dev` is running.
