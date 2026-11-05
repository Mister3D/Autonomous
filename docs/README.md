# Autonomous — read this first

You are a Cursor agent working on the **Autonomous** repo.  
The user has (probably) told you to read this file and then get to work: **do exactly that**.

## 1. Mindset (important)

- This `docs/` folder is your **durable memory**. The chat may be fresh; the feature notes are not.
- If the user has **already given you tasks** before or alongside "read the readme":
  - assume you have a **documentation backlog** until proven otherwise;
  - before chaining code "by feel", **catch up**: go through the `features/` notes related to the topic, then the code;
  - if you discover that a behaviour in prod/code is **not** (or no longer) in `features/`, **document it first or right after the fix**; don't let the backlog grow.
- Don't assume you "remember" another conversation. Re-read the notes.

## 2. What you must do now

1. Read [`AGENT.md`](./AGENT.md) (short rules: read / document / **test** / don't break things).
2. Go through the index of notes below and **open the ones relevant** to the current request.
3. Only then: answer / code according to the user's request.
4. After any behaviour change (even a UX detail): **update** the relevant `features/` note (date + pitfalls). New topic → new note + a line in this README.
5. **Test** on the local env (`serve --dev`, pytest, curl/UI) — this is not prod; don't ship by feel (details in `AGENT.md`).


## 3. `features/` catalogue (actual implementation)

| Note | Topic |
|-------|--------|
| [features/desk-screen.md](./features/desk-screen.md) | Docker desktop, noVNC, take control, 1920×1200, frame |
| [features/terminal-pty.md](./features/terminal-pty.md) | xterm.js terminal + PTY WebSocket `/ws/terminal/<bot>` |
| [features/files-shared.md](./features/files-shared.md) | Files panel, `~/shared`, upload / mkdir / download |
| [features/agent-files.md](./features/agent-files.md) | Pi agent → `files_*` on `~/shared` (no host shell) |
| [features/routing-tabs.md](./features/routing-tabs.md) | URLs `/b/:name/:tab` |
| [features/serve-dev.md](./features/serve-dev.md) | `serve` / `serve stop` / `--dev`, MuxServer |
| [features/chrome-desktop-image.md](./features/chrome-desktop-image.md) | `autonomous-desktop:latest` image, Chrome flags |
| [features/pi-agent.md](./features/pi-agent.md) | Host-side Pi agent, sessions, chat streaming, local LLM |
| [features/token-usage.md](./features/token-usage.md) | ↑↓ token counter at the top of the chat |
| [features/vault.md](./features/vault.md) | Global encrypted vault, bot grants, chat forms (secrets kept out of the LLM) |
| [features/memory.md](./features/memory.md) | Memory shared by bots: core (1×/conversation) vs browse, opt-out, non-blocking proposals |
| [features/approval.md](./features/approval.md) | Accept / Decline card (`ask_approval`, blocking) |
| [features/clarify.md](./features/clarify.md) | Structured question card (`ask_clarify`, blocking) |
| [features/agent-vm-terminal.md](./features/agent-vm-terminal.md) | Pi agent → VM `docker exec` (no UI) |
| [features/agent-vm-screenshot.md](./features/agent-vm-screenshot.md) | Pi agent → VM screenshot (chat + tools) |
| [features/grounding.md](./features/grounding.md) | UI-TARS + judge: locate an element (pixels, no click) |
| [features/browser-nav.md](./features/browser-nav.md) | Generic web nav: CDP + iframes (`frames_snapshot`) + VNC drag + Pi tools |
| [features/botmail.md](./features/botmail.md) | Tell / Ask @bot, queue if busy, follow-up on reply |
| [features/bots-create.md](./features/bots-create.md) | Free-form name + auto technical slug |
| [features/chat-files.md](./features/chat-files.md) | Chat attachments → ~/shared/upload |
| [features/events.md](./features/events.md) | UTC cron + tokenized webhooks, Events tab |
| [features/chat-search.md](./features/chat-search.md) | Message search (FTS + NL) + `?msg=` deep-link |
| [features/chat-export-pdf.md](./features/chat-export-pdf.md) | Export discussion PDF (tools named, no details) |
| [features/reactions.md](./features/reactions.md) | Bot emoji on the user's bubble (`react`), without replacing the reply |
| [features/avatars.md](./features/avatars.md) | SVG companion badges (work / notify / await / idle) |
| [features/manager.md](./features/manager.md) | Manager bot: peer list + async delegation (Tell follow-up) |
| [features/companion.md](./features/companion.md) | PC companion: pairing, VM Internet, local MCPs |
| [features/setup.md](./features/setup.md) | First-run checklist + first conversation CTA |
| [features/updates.md](./features/updates.md) | Self-update: channel main/dev, 24h check, apply + systemd restart |
| [features/auth-secrets.md](./features/auth-secrets.md) | Session secret ≠ API Bearer, XFF trust, companion 101, grounder keys |

Local index: [features/README.md](./features/README.md).

## 4. Spec / reference (less "chatty")

| File | Role |
|---------|------|
| [AGENT.md](./AGENT.md) | Agent obligations |
| [API.md](./API.md) | HTTP map (+ live OpenAPI) |
| [CLI.md](./CLI.md) | CLI |
| [DATA_MODEL.md](./DATA_MODEL.md) | SQLite |

## 5. Typical user phrase

> Read the readme in docs and then we'll get to work.

Expected answer from you (in spirit):  
"OK — I've read `docs/README.md` + the relevant notes. If tasks had already been given, I'm handling the doc backlog. We can carry on."

Language: **French**. Apply code without asking; ask before `apt`/`pip`/package managers.
