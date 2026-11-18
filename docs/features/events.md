# Scheduled tasks & webhooks (Events)

**Status**: in place  
**Key files**: `autonomous/migrations/001_schema.sql`, `autonomous/services/{bot_events,cronutil,scheduler}.py`, `autonomous/api/{bots,hooks}.py`, `autonomous/pi_extensions/events.ts`, `frontend/src/components/{EventsPane,ChatPane}.vue`  
**Last updated**: 2026-11-12 (bot may schedule its own relaunch)

## User behaviour

- **Événements** / **Events** inspector tab (next to Details / Files).
- **Input** (Pi `schedule_*` tools only): 5-field cron in the **time zone chosen in Settings → Agent** (`settings.timezone`). The field filters as you type (Paris → `Europe/Paris`) and saves as soon as you pick, without a button. With no saved value, the default is **Europe/Paris**. An explicit empty string remains the host time zone.
- **Storage**: equivalent expression in UTC (`cron_utc`) + `next_run_at` / `last_run_at` in UTC. `GET /api/v1/clock` exposes the effective time zone (`timezone` + `utc_offset`).
- The UI shows the cron and the next run in that time zone (the cron tooltip shows the UTC expression). Changing the time zone in Settings redisplays already saved tasks without rewriting them.
- **Creation**: Pi tools only. The tab has no form. Cron **update**: Pi tools. The header only shows the active time zone (`Fuseau : …`).
- **Self-relaunch**: if the turn cannot finish (site down, wait longer than the turn, the bot told the user it will retry), the system hint tells the bot to call `schedule_create` itself, without asking. A shell echo is not a schedule. One-shot retry → `recurring=false`, and the instruction must carry the state and the next step. `schedule_create` is hidden in the thread, so the proof is the Events row and the later orange fire card. An already open Pi session keeps the previous hint until the next start.
- The open **Events** tab updates itself when the agent creates, modifies or deletes a reminder (SSE `schedule.updated` / `schedule.deleted`, same for webhooks). No need to switch tabs.
- To know the time before a relative cron, the agent runs `TZ=<timezone> date` with `vm_terminal_exec` (the VM is requested if there isn't one). It does not invent the time. `date -u` is UTC and ignores `TZ=`: the terminal output points this out, along with the local time. No separate clock tool.
- A one-shot whose time has already passed today (day and day-of-week as `*`) is **refused** (`oneshot_too_far`) instead of being silently pushed to the next day. To target another day, the cron must set the day of month and the month. `GET /clock` includes `now` (`YYYY-MM-DD HH:MM`).
- **User**: small switch in front of the name (pause / resume, without the word "Actif"). Task: click the **name** to open the standing `instruction` modal; delete icon to the right of the next run. Webhook: click the **name** for the same modal; the token is not shown; copy + delete stay on the right. Modal = scrollable body for long texts. Empty → "(no instruction)". The chat fire card no longer repeats that body. The copy button puts a **curl** with `Authorization: Bearer <token>` on the clipboard (token not in the URL). Deleting a webhook opens a confirmation in the list ("Oui, supprimer" / "Annuler"), not a browser dialog.
- `recurring=false` → deleted after firing, **unless** the next slot is less than 15 minutes away (burst, e.g. every 5 min). The row then stays until the first longer gap. For an hour of reminders, the cron must set the day and the hour (`25-55/5 11 1 11 *`). An hour set to `*` repeats the burst every hour, then stops when the gap exceeds 15 minutes (e.g. `25-55/5` stops after :55).
- Missed ticks: **catch-up** (at most **one** due execution per task if `next_run_at <= now`), no N×missed burst.
- Firing → chat message `role=user` with `meta.kind=schedule|webhook` (FIFO queue if busy, like user messages). The bot always receives the full preamble + standing instruction in `content` / `meta.agent_prompt` (unchanged for Pi). Meta also stores `instruction` for the UI. In the thread: centred card, light orange background, dotted outline — **type + name** (and optional anchor). Click the **card or the name** → scrollable modal. A webhook modal leads with **Charge** (the POST body, pretty-printed JSON or raw text) then the standing instruction. A schedule modal is the instruction only. Same name click on the Events list (instruction only). No eye icon. Webhook JSON stays in `meta.payload` for the UI; the same payload is copied into `meta.agent_prompt` (`Payload : …`, size-capped) so the agent can apply standing rules without relying on meta alone. A body sent as `Content-Type: application/json` that is not valid JSON is kept as text (mail forwarders do this). `{}` and an empty body still count as no payload.
- Public webhook: **POST only** `/api/v1/hooks` (no trailing `/` — single collection resource) with `Authorization: Bearer <token>` (no session auth; token is the secret, not in the URL). GET / path-token URLs are rejected. Rate-limited: 30 / min / token and 60 / min / client IP. Open exact path: `/api/v1/hooks` only.
- **Copy curl** in Events uses the **browser origin** (`location.origin` + `/api/v1/hooks`), not the server-built absolute URL. Otherwise the clipboard often has `http://127.0.0.1:8787/…` (or plain HTTP behind a TLS proxy) → **301** on curl, Bearer/POST dropped on follow, while the bot may still claim the webhook exists. Absolute `url` in the API still prefers `AUTONOMOUS_PUBLIC_URL` when set.
- **From a VM** (desktop with Internet): `host.docker.internal` + env `AUTONOMOUS_HOOKS_BASE` / file `~/files/.autonomous/host-api.env` (the desktop image helper still reads the legacy mount `~/shared/.autonomous/host-api.env`, same private folder). Helper: `autonomous-hook <token> '{"ok":true}'` (sends Bearer). Without Internet (`network=none`) the VM cannot reach the host — recreate the desk with Internet, or call the webhook from outside.

## Implementation

- Tables `bot_schedules`, `bot_webhooks` — column `bot` = **`bots.id` (UUID)**.
- Scheduler: daemon thread in `serve` (tick ~30s), catch-up on the 1st tick.
- Internal cron parser (`cronutil.py`) — no `croniter` / `apscheduler`. The matcher stays in UTC; `local_cron_to_utc` / `utc_cron_to_local` shift the fields at the API boundary (user time zone offset, otherwise the host's).
- Injection: `bot_events.inject_trigger_message` → `meta.queued` + `drain_queued_user_messages` if busy.
- Pi tools hidden from the thread (`_HIDDEN_TOOL_CARDS`).

## Pitfalls / non-regressions

- Don't name the service module `events.py` (conflict with `services.events.BUS`).
- Open exact `/api/v1/hooks` only in `app._OPEN_EXACT` — do not also register `/hooks/` (keeps one CRUD collection path).
- Events **Copy** must not paste `w.url` from the API when the UI is opened via another host/scheme — use `location.origin`; path must be `/api/v1/hooks` without a trailing slash.
- One-shot: delete **after** a successful fire, not before. If the cron has another slot within 15 minutes, advance `next_run_at` instead of deleting (otherwise "every 5 min for 1 h" disappears on the first shot).
- Catch-up: advance `next_run_at` after a single fire (don't replay all missed ticks).
- Webhook disabled / unknown token → 404 (no fine-grained existence leak).
- Time shift (DST): the UTC expression is frozen with the offset **at save time**. A "9am" task can slip by one hour when the clocks change, until the cron is saved again.
- Unknown time zone in `PUT /settings` → 400 `invalid_timezone`. Empty string: back to the host time zone. Missing key: `Europe/Paris` (default at init).
- An already open Pi session keeps the old time zone in its prompt until the next start. The display, however, follows the setting immediately.
- Impossible conversion (slots crossing midnight differently, or day-of-month going outside 1–31) → `invalid_cron`. Prefer a single hour, or `*` for day-of-month and day-of-week.
- A PATCH without a `cron` field does not reconvert: it keeps `cron_utc`.
- `date -u` (even preceded by `TZ=`) gives the UTC time. A one-shot cron set on that time, while the time zone is ahead, already falls in the past: previously, the next run became the next day and the reminder never went out. The server refuses this one-shot as long as the day is not set.
- The already open Pi session keeps the old tool text. The `oneshot_too_far` refusal, however, comes from the API and applies immediately.
- `AUTONOMOUS_LLM_TEST_CLOCK=1` is only for the LLM test: `date` (with no other command) runs on the host instead of the VM. Don't enable it for normal `serve`.
- The Events tab doesn't reload by itself only on mount: it must apply `schedule.updated` / `schedule.deleted` (otherwise a reminder created by the agent doesn't appear until you switch bots).
- No creation form in the tab. Only the agent creates a task or a webhook. The user pauses, resumes, deletes, copies a Bearer curl, and peeks the carrier instruction by clicking the event name. The webhook token is not shown in the list: it stays behind the copy icon, on the same line as the name.
- Desks created **before** `host.docker.internal`: recreate the desktop (or `curl` via the Docker gateway IP). `sync_host_api_env` updates the env file on the shared volume on every wake.

## Quick check

```bash
# UI: click an orange webhook bubble → modal shows Charge (POST body) then the instruction.
# Events tab → webhook = switch + name, copy curl (Bearer) + delete, no raw token in the list
# Prompt: unfinished work → the bot creates its own one-shot schedule (no permission ask).
pytest tests/test_events.py tests/test_llm_schedules.py -q
# Real model call (Pi + provider already configured on the host):
# AUTONOMOUS_LLM_TESTS=1 pytest tests/test_llm_schedules.py -q -m llm
```

```bash
# Bearer — token not in the URL:
#   curl -sS -X POST "$AUTONOMOUS_HOOKS_BASE" -H "Authorization: Bearer <token>" -H 'Content-Type: application/json' -d '{}'
# In the VM (Internet ON):
#   autonomous-hook <token> '{"from":"vm"}'
```

The LLM case sends "Pendants 1h, rapelle moi toutes les 5 min de me focus !" ("For 1h, remind me every 5 min to focus!") and requires a series of about one hour, every 5 minutes, that then stops. It does not run with the default suite. This test's `serve` has `AUTONOMOUS_LLM_TEST_CLOCK=1`: a bare `date` answers on the host, without a Docker desktop. This variable must not be set on the everyday server.
