# Pi agent (pi.dev)

**Status**: in place (chat streaming + vault + VM terminal)  
**Key files**: `autonomous/services/{agent,pi_rpc,pi_status,chat,bots,terminal}.py`, `autonomous/pi_extensions/{vault,vm}.ts`, `frontend/src/components/{SettingsMenu,SettingsModal,ChatPane}.vue`  
**Last updated**: 2026-11-11 (silent-busy recovery on server scheduler only)

## User behaviour

- Bottom left: **round settings button** (no more flag). Menu = open settings, log out. **Delete all bots** is under Settings → Générale, same arm → check (`.action-confirm`) pattern as the bot Details manage list — tooltip says Confirm? only. Each bot: same `DELETE` (Pi session + desktop + dir wipe).
- Home page (Autonomous brand): banner if Pi is not ready → link to model/provider config docs.
- Each bot = one **Pi session** on the **host** machine (`data/bots/<name>/pi/`). Pi id = `autonomous-<uuid>`; the chat ↔ session link is `bots.pi_session_id` (not the slug).
- Web messages → Pi prompt; assistant tokens over **SSE** (`message.delta` then `message.updated`).
- Emoji reaction: the `react` tool puts an emoji on the turn's user bubble (`meta.reactions`), without a tool card, only when it is justified (thanks, a joke, good news). Most turns get none; a plain question does not get one just because it was answered. It does not end the turn: the reply text follows if needed. See [`reactions.md`](./reactions.md).
- Bot rail: sorted by **latest message** (sent or received), most recent at the top (`last_message_at` + live messages).
- Chat layout: **user on the right**, **assistant on the left**, **tools grouped** in the centre (`ToolGroup`). During the run: live preview of the **last tool call** (fixed height, so each result does not resize the thread). No blank tail under the thread — that block used to shove the conversation up in one jump. Opening a thread jumps straight to the latest messages (the pane stays hidden for that instant) — it does not animate through the history. Streaming growth stays instant. As soon as an LLM reply (or other message) follows: the group **collapses** into a summary bar — unless the user opened the details (caret). Detail menu = **list of collapsed tools** (`vm_ground`, `vm_click`, `vm_drag`, `vm_scroll`, …) — no separate target/pointer blocks. A line's **Error** status is in red. **Duration** (`meta.duration_ms` from Pi, or live elapsed while running) is shown **just before** Done/Error on the group summary and each tool row; **orange** when the tool ended on a timeout (`meta.timed_out` or `[timeout after Ns]` / « timed out waiting » in the result). Captures / crosses / overlays: only when expanding the relevant tool line.
- Markdown code blocks (`<pre>`): **copy** icon top right (hover / focus) → clipboard, "Copied" feedback.
- Markdown tables: light card, header, zebra, sticky 1st column, horizontal scroll if the table overflows.
- **User and assistant** bubbles: **90%** of the thread width. The time is beside them, outside those 90%. **System** messages (botmail) are a centred card, same width as tool groups, light blue background and dotted outline. **Webhook** and **scheduled task** messages have that same card, with a light orange background and a dotted outline.
- During a reply: the thread **no longer sticks** to the bottom if you scroll up; ↓ button to go back. Auto-scroll only if you are already near the bottom (or after sending).
- Input **always open** during a run: composer sends while busy / slot-held go straight to the **FIFO queue** (`meta.queued`, pinned at the bottom; timestamp slot shows muted « En file » / « Queued » with red « Supprimer » / « Delete » under it — no badge on the bubble) — **no mid-run steer** from the human chat (that let a later « 10 » jump ahead of « 8 » / « 9 »). Peer botmail may still mid-run steer. **Pre-stamp** `queued` on INSERT when busy / slot held / queue non-empty; **defer** SSE `message.created` until queue-vs-start is decided so the first event already has `queued` (no blue→queued flash). Optimistic bubble uses the same stamp (`runLocked`, other `tmp-*` / queued, or `sendsPending`) plus a monotonic client ``meta.queue_ord`` — the thread sorts the file by ``queue_ord`` (not raw `created_at`) so swapping optimistic ISO timestamps for server ones does not reshuffle 8/9/10. Store inherits `queued` + `queue_ord` from a dropped optimistic twin. The composer **serializes** `POST /messages` (send chain) so rapid Enter keeps API order. Click « Supprimer » → `DELETE /bots/:name/messages/:id` removes that bubble so it never drains. Live updates stay just above queued bubbles. On drain: oldest by `created_at` then `id`, `created_at` reset to now, then run (also after stop). Optional `prompt` on `POST /messages` overrides the agent text while keeping a short `content` bubble (`meta.agent_prompt`). `loadMessages` merges by id and drops `tmp-*` bubbles once the server echo exists (SSE `message.created` / HTTP) so the UI never shows the same send twice. Whitespace-only assistant placeholders are discarded (no timestamp-only rows).
- Visible timestamp: time to the **right** of assistant bubbles (left), to the **left** of user bubbles (right), vertically centred; if not today → `DD/MM` above the time. Also on the summary / tool lines (`ToolGroup`).
- The API only returns one page of events (`limit` ≤ 200). The client (`loadThread`) pages backward while each page is full (up to 20×200) so the **start** of the thread is loaded — not only until the first page that happens to contain a user bubble (that bug hid older history at the top, e.g. Manager kickoff).
- Input area: **textarea** — `Enter` sends, **`Shift+Enter`** new line (auto-resize). The text and attachments **leave the field immediately**, without waiting for the server response. If sending fails (or a vault secret is refused), the draft comes back. **Pasting an image** (Ctrl/Cmd+V) into the field → preview, then sent with the text; stored under `~/…/.autonomous/chat-attachments/`, passed to Pi as `images[]` (vision required on the model).
- Model picker: `ModelPicker` is the shared `MenuSelect` (no native `<select>`); short label + provider.
- Model **per bot** (creation + Details); if an RPC session is running, `set_model` mid-session.
- During a run: the send button becomes the **Working orb** ([thinking-orbs](https://libraries.dev/orbs), canvas engine `thinking-orbs/engine` via `WorkingOrb.vue`) — click = Pi `abort`. In the Conversation thread, the same orb appears **as long as no assistant text has started** (waiting for the model / between tool turns); from the first token, it disappears in favour of the bubble.
- If the Pi session dies while waiting for the user (vault / desktop): status `idle`, **Resume** chat card (`meta.kind=agent_interrupted`) → `POST /bots/:name/resume` relaunches the agent on the original task (without a new user bubble).
- **Retry** bar above the composer (idle with queue left undrained after a **2 s** grace, hard LLM failure bubble, pending Resume, or soft-stuck busy after **45 s** — not during a real human wait): **Relancer** is **manual only** → `POST /bots/:name/retry`. Soft-clears a dead worker (tools / streaming), keeps `pi_session_id` and the chat history, then drains the oldest queued user/webhook **or** resumes the last unfinished turn. Refuses with `waiting_for_user` if a vault/approval/clarify/desk card is still open. Right after send (`user` with no assistant yet, or busy waiting for the first token) must **not** show the bar — that is the normal Working-orb wait, not a failed turn. **Queued bubbles while the agent is live** (`busy` / streaming / running tools / waiting-for-reply orb) are normal — hide Relancer. Between two drains status can flicker `idle` with « En file » still present: the **2 s** idle-queue grace avoids flashing « Des messages sont en file » mid-burst. The front **must not** auto-POST `/retry` or `/resume` — recovery must work with no browser open.
- **Silent-busy watchdog** (server): each scheduler tick (`~30 s`) calls `recover_silent_busy_runs`. A bot left `busy` with no pending human wait, and either no live worker **or** a live worker with no Pi progress (token / tool / settle) for **45 s**, gets `retry_unprocessed` (90 s cooldown). Progress is stamped via `touch_run_progress` on every Pi event and at `start_run`. This unsticks dead GPU / post-guard hangs without a user watching.
- Desk ready while a run is still going: **no** second `resume_run` (avoids "Agent is already processing"). Always set `status=busy` back for the Working orb — don't leave a forced `idle` at the end of desk boot.
- On `tool_execution_end`, Pi often sends `args={}`: Autonomous keeps the args from the start and enriches `meta` (click/drag coords, `duration_ms`, `timed_out`) for the UI.
- **Actions** guard-rail (Settings, saved as soon as the field changes — no button), counter **since the last `user` message** (user, webhook or cron) — **not** the whole conversation, and **not** reset by a desk/vault resume:
  - `guard.review_every` (**100** default, `0` = off): **blocking** Pi steer → the agent must answer `GUARD:CONTINUE` or `GUARD:STOP` before any further tools;
  - `guard.max_actions` (**1000** default): hard stop + system message.
  - **UI** (`ChatPane.vue`): the review system message (`meta.kind=guard`, `review`) and the assistant reply `GUARD:CONTINUE` / `GUARD:STOP` are rendered as a **bordered centred card**, same width as tool groups: "🧭 Garde-fou : revue à N actions démarrée" / "on continue !" / "l’agent s’arrête". Text after the token stays a normal bubble; the partial token during streaming is hidden.
  - **Gate**: after the review milestone, further tools are blocked until `GUARD:CONTINUE` / `STOP`. The gate opens as soon as `GUARD:CONTINUE` streams (same-turn tools are allowed). If CONTINUE arrives after a gate abort, settle kicks a **task resume** run (so the bot does not stay idle). Tool-only replies without the token get a silent abort + gate follow-up — **no** “outils bloqués” chat card.
- After a `stop`, a user message left "queued" is relaunched (immediate drain + delayed retry at 1.5 s / 6 s if the old worker was still holding the slot).
- `stop_run` also clears the in-memory `_ACTIVE_RUNS` slot (`clear_active_run`). Without that, DB went `idle` while the next `start_run` kept logging « run already in progress » and the chat looked frozen (user bubble only). `start_run` also reclaim a stale slot once when DB status is already `idle`/`waiting`.
- **Serve restart / `--dev` reload**: `recover_stale_runs` (from `_serve_loop`) finds bots left `busy` with no live Pi worker — closes running tool cards, seals streaming assistant bubbles, sets `idle`, then drains queued user/webhook messages. If nothing was queued, posts an **Resume** card (`agent_interrupted`). Orphan `waiting` (no pending vault/approval/clarify/desk) is recovered the same way; a real human wait stays `waiting`.
- **No** run duration limit in the product (any timeout stays on the Cursor / manual test side).
- Vision: budget from the bot’s Pi model (`inputLimits.images.maxPerRequest` in `models.json`); fallback `guard.max_images_per_prompt` (**2**). Only this budget goes into `images[]`; the rest is listed as paths for later turns. If the provider returns "At most N image(s)", retry + persist N on that model (and the guard fallback). See [`llm-settings.md`](./llm-settings.md).
- Clear history = SQLite purge + **wipe** `pi/sessions/*.jsonl` + new `pi_session_id` (`autonomous-<uuid>`). Details asks first: a check icon at the end of the row (no confirm card). The button also empties `state.messages[name]` (no SSE on delete, otherwise the thread and the rail keep the old bubbles until a full reload).
- Delete a bot = stop Pi + destroy desk + **rm** `data/bots/<name>/` (otherwise orphan files).
- Chat ↔ Pi link: **only** `bots.pi_session_id` (Autonomous chooses the id, Pi doesn't know the slug).
- Same scheme for Docker VMs: `desk.container_name` = `autonomous-<uuid>` (see [`desk-screen.md`](./desk-screen.md)).

## Configuring a model / provider

Pi is **not** in the VMs. It's on the host.

### OpenAI-compatible provider

1. Prefer **Settings → LLM** (writes `~/.pi/agent/models.json`, merge-safe) or edit the file by hand.
2. **API key** → field in the UI, or `~/.pi/agent/env` / `$VAR` (mode `600`). Autonomous loads it via `pi_env()`.
3. Per model: display `name`, vision `input`, `inputLimits.images.maxPerRequest`, `contextWindow`, `maxTokens`.
4. Auth to built-in providers (`/login`) and advanced cases: [Pi models](https://pi.dev/docs/latest/models) + [models configuration](https://pi.dev/docs/latest/models-configuration).
5. `pi --list-models` → then model per bot (creation / Details).

## Implementation

- Markdown chat (`ChatPane.render`): escape raw `<`/`>` **before** `marked` so prose like Vue `<script setup>` cannot open a real HTML tag (DOMPurify would then drop the rest of the bubble). Then mentions, `wrapCodeBlocks` (`.code-block` + copy), `wrapTables` → `.md-table-wrap`; delegated click (`onChatClick`) → `navigator.clipboard` (`execCommand` fallback).
- Scroll: `stickToBottom` + ~100 px threshold; the messages watch coalesces follow-scroll with `requestAnimationFrame`. Do **not** toggle `messages-placing` (visibility:hidden) on live tool updates. Guard cards do **not** seal tool groups; walking backwards, only the **last** tools group stays live (earlier ones seal). Live preview is a **compact one-line** status (no args/result body) with fixed height — that stopped the thread jump on rapid tool spam. The jump is instant (`scrollTop`), including the first paint and a `?msg=` anchor. Live follow, **Send**, and ↓ all use the **absolute** bottom (full « En file » visible) — no second “peek above queue” target (that fought manual scroll and saccaded near the file). `isNearBottom` uses that same end only. The `.messages` scrollbar stays hidden until scroll (or hover), then fades out **2 s** after the last scroll event.
- Message queue: `chat.send_message` **parks** composer traffic with `meta.queued` whenever the bot is blocked or the run slot is held — never `steer_mid_run` from the UI path. User+agent inserts **defer** `message.created` until after the park/start decision (so `_mark_queued` cannot paint a non-queued created first). `list_queued_user_messages` reads SQLite directly (`json_extract … queued`, `ORDER BY created_at ASC, id ASC`). `drain_queued_user_messages` clears the badge on the oldest + `bump_created_at` then `start_run` (Pi finally / stop / desk ready). Peer mail to a busy bot may still mid-run steer. `ChatPane.send` chains POSTs so burst typing keeps server order.
- Empty assistant bubbles: `close_assistant` discards whitespace-only placeholders (`message.deleted`); the timeline also skips them for older threads.
- Blocking guard gate: `tool_execution_start` after the review milestone aborts further tools (`guard_blocked`), queues `_kick_guard_gate_run` (tools blocked until `GUARD:CONTINUE` / `STOP`).
- Agent backend: `agent_backend=pi` (default). pytest tests force `null`. An opt-in case (`AUTONOMOUS_LLM_TESTS=1`, `llm` mark) launches a real Pi: see [`events.md`](./events.md).
- Long-lived RPC: `pi --mode rpc … --offline` with **always** `--exclude-tools bash` (no host shell). Bot files: `files_*` (see [`agent-files.md`](./agent-files.md)). **VM** terminal: `vm_terminal_exec` (see [`agent-vm-terminal.md`](./agent-vm-terminal.md)).
- **API auth for tools**: each Pi RPC start calls `issue_bot_api_token` → env `AUTONOMOUS_TOKEN=abt_…` (SHA-256 in `bots.api_token_hash`). Extensions keep calling `Authorization: Bearer …`; the gate allows `/api/v1/bots/<this-bot>/…` plus vault/memory/approvals/clarifies/search/companion agent routes for that bot only — **not** the admin `data/token`. VNC/terminal WS still require session or admin Bearer.
- Web search extension: `npm:pi-web-access` (`pi install npm:pi-web-access`) → tools `web_search` / `fetch_content`.
- Vault extension: `autonomous/pi_extensions/vault.ts` via `--extension` (see `docs/features/vault.md`).
- VM extension: `autonomous/pi_extensions/vm.ts` → `vm_desk_status` / `vm_terminal_exec` / `vm_screenshot` (see `agent-vm-terminal.md`, `agent-vm-screenshot.md`).
- Inter-bot extension: `autonomous/pi_extensions/botmail.ts` → `bot_list` / `bot_tell` / `bot_ask` (see `botmail.md`). User composer: "Dit à @…" / "Demande à @…".
- Pi instructions (`pi_rpc.py`): `_VAULT_SYSTEM_HINT` (secret rules) and `_VM_SYSTEM_HINT` (desktop + browser) are **structured in numbered sections** — 1 Desk/shell, 2 Tools (read / wait / see / act / locate), 3 Action loop, 4 Block pages, 5 Login — one rule = one place only (no vault/VM duplicates). Generic: putting site-specific or captcha-vendor-specific recipes there is forbidden. Tool descriptions (`vm.ts`, `browser.ts`, `vault.ts`) must stay consistent with them (coordinates = snapshot or `vm_ground`, never `vm_look`).
- `vm_look` tool: the agent **never** has the PNG; `vm_look` = capture + host multimodal model → text. Rule: never announce an error that hasn't been read (`browser_text` / `vm_look`).
- `--append-system-prompt` at session start: core memory + hints (vault, files, VM, botmail, manager, events, memory, approval, clarification, search, vision). No more `bots.role` persona. That addendum is **frozen for the life of the Pi process** — each later `prompt()` only **appends** user/tool turns (append-only transcript). Do **not** reinject wall-clock “now”, refreshed core memory, or other per-message system rewrites: that busts provider / vLLM prefix (KV) cache. Memory / timezone changes apply on the **next** Pi start. Compaction is the intentional prefix rewrite (summary + recent turns).
- API: `GET /pi/status`, `GET /pi/models`, `POST /bots/:name/stop`, `POST /bots/:name/resume`, `POST /bots/:name/retry`.
- Resume a session outside the UI:  
  `cd data/bots/<name>/pi && pi --session-id <pi_session_id>`  
  (or `--session-dir …/sessions`).

## Pitfalls / non-regressions

- Never feed raw chat text to `marked` without escaping `<`/`>` first: a literal `<script …>` (e.g. Vue SFC) opens a real tag, DOMPurify strips it, and **the rest of the bubble disappears**.
- PATH: serve with `~/.local/bin` visible (the code enriches `PATH` for subprocesses).
- Host Pi tools active (web search + vault + terminal + VM screenshot). Computer-use / click = next step.
- `message.delta` is not replayed on refresh: the final content is in the database via `message.updated`.
- Do **not** rebroadcast SSE envelopes on `BroadcastChannel`: every tab already has EventSource, and the posting tab also receives its own broadcast → each `message.delta` was applied twice (duplicated tokens until refresh). See `frontend/src/sync.js`.
- Mid-turn navigation: `loadMessages` / mid-stream `message.updated` must not truncate SSE text already shown — `preferLiveStreamingMessage` keeps the longer body while `streaming` is true; missing bubbles are created on delta if `message.created` was missed.
- On Pi `message_end`: don't reopen a bubble if it was already finalised at `toolcall_start` (otherwise an identical duplicate right before the tool).
- On refresh, don't stop at the last page of tools: the `user` message (and therefore the assistant reply more recent than it) must stay in the displayed thread.
- Old DB with `agent_backend=null`: switch to `"pi"` via `PUT /settings` or Settings / CLI.
- `GET /settings` must return the dotted keys (`guard.review_every`, etc.). Otherwise the Settings screen shows the defaults and the next automatic save overwrites them.
- `PiRpcSession.start()` must **not** call `request()` under the same `threading.Lock` (non-reentrant → deadlock).
- Local endpoint down (e.g. Ollama) or other hard failures → assistant content `⚠️ …` rendered as a **centred red card** (not a left bubble), same family as secret-leak / guard.
- Never paste >`max_images_per_prompt` vision images into a single Pi prompt (otherwise 400 with many providers).
- Stop kills the RPC process (stdin abort alone may stay stuck if the HTTP provider hangs).
- **Stop**: `stop_run` closes in-progress cards, then does a delayed sweep (+1.5 s and +6 s) because a `tool_execution_start` already read by Pi just after the stop created an orphan "In progress" card (real case: `vault_type` stuck). The sweep goes back 400 messages (long series of grounding notes were hiding old cards). Tests: `tests/test_close_running_tools.py`.
- End of run / stop: `close_running_tools` switches `status=running` cards to **error** (otherwise `vm_ground` etc. stay "In progress" if Pi dies without `tool_execution_end`).
- Retry bar: do **not** treat `busy` + empty streaming / no assistant yet as immediately stuck — that is the normal Working-orb wait. Soft stuck needs a grace timer; hard stuck = abort/error/⚠️ only. Idle `lastTurnFailed` must require a real failure bubble — never “user message with no assistant yet” (that flashed Relancer on every send while status was still idle). Do **not** show Relancer solely because `meta.queued` exists while the agent is live — the queue drains after the current run. Also do **not** show it on the brief `idle` gap between two auto-drains (2 s grace on idle+queued). **Never** put auto-retry / auto-resume timers in the front — the server scheduler owns silent-busy recovery (grace + cooldown there).
- Queue flash: never publish a non-queued `message.created` then `message.updated` with `queued` for a busy bot — the optimistic bubble and the first SSE must already say « En file ».

- `vm_request_desk` (and desk failures of screenshot/exec) **block** until the user's authorisation — like the vault; the agent must not chain other tools.
- Pi cwd under the repo: always `--no-context-files` so as not to swallow Autonomous's `AGENTS.md`.
- Never leave `data/bots/<name>/pi/sessions` after a bot `DELETE`: Pi resumes the `*.jsonl` if the same `--session-id` comes back.
- User secret leak (`report_user_secret`): **stop** of the Pi process + scrub of the `*.jsonl` (otherwise the model "remembers" the password at the next message). See [`vault.md`](./vault.md).
- **Prompt / KV cache**: keep the leading system+tools prefix byte-stable across turns in one Pi session. Forbidden in future work: stamping the current time into `--append-system-prompt` per message, rebuilding the system block on every `prompt()`, or rotating “fresh” memory into the system mid-session. Allowed: append user/assistant/tool messages; Pi compaction; process restart (new freeze). Compaction budgets live in `~/.pi/agent/settings.json` (`compaction.reserveTokens` / `keepRecentTokens`); model `contextWindow` in `models.json` must match the real vLLM `--max-model-len` or Pi compacts / overflows on the wrong number.
- `loadThread`: do **not** stop paging when a page contains any `role=user` — that only guaranteed the latest turn was present and silently dropped older pages. Stop on a short page / empty page / cap.

## Quick check

```bash
export PATH="$HOME/.local/bin:$PATH"
pi --version
pi --list-models
curl -s -b cookies http://127.0.0.1:8787/api/v1/pi/status
# Send a web message → streaming assistant bubbles; Stop cuts the run.
python3 -m pytest tests/test_bot_api_token.py tests/test_chat.py::test_openapi_generated -q
python3 -m pytest tests/test_recover_stale_runs.py tests/test_retry_unprocessed.py tests/test_silent_busy_recover.py -q
```
