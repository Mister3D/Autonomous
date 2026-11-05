# Host shell (Pi bash permission)

**Status**: in place  
**Key files**: `allow_host_shell`, `pi_extensions/host.ts`, `terminal.request_shell_*`, `ShellRequestCard.vue`, `DetailsPane`  
**Last updated**: 2026-11-01 (resume after approve, no more orphan busy)

## User behaviour

- By default, Pi's **bash** tool on the **host machine** is disabled (`--exclude-tools bash`).
- The agent asks via **`host_request_shell`** → "Host shell authorisation" chat card.
- Or the **Details → Host shell** toggle — revocable at any time.
- After approve: the Pi session is stopped then relaunched **with** bash, and the task resumes (the `host_request_shell` tool does not stay "in progress", the bot does not stay `busy` without a process). After revoke: session relaunched **without** bash, status `idle`.
- The **VM** terminal (`vm_terminal_exec`) is **not** affected — always usable as soon as there is a desk.
- `date`, `curl`, `ping` and other commands go through `vm_terminal_exec` (VM request if there is no desktop). `host_request_shell` remains for a command that really must run on the host.
- Bot files (`files_list` / `files_read` / `files_write`…) **do not need** this permission — see [`agent-files.md`](./agent-files.md).

## Implementation

- Column `bots.allow_host_shell` (schema (`001_schema.sql`)).
- API: `GET/POST …/shell`, `…/shell/request`, `…/shell/request/resolve`.
- Card `meta.kind=host_shell_request`.

## Pitfalls

- Don't re-gate VM `terminal/exec` with this permission.
- After toggling, the next message relaunches Pi (RPC stop).
