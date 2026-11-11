# Desktop / Screen (noVNC)

**Status**: in place  
**Key files**:
- `frontend/src/components/ScreenPane.vue`
- `frontend/src/styles.css` (`.screen-frame`)
- `autonomous/app.py` (proxy `/novnc/<bot>/`, HTML injection)
- `autonomous/services/desk.py`
- `autonomous/wsproxy.py` (WS → websockify)
- `docker/desktop/*`

**Last updated**: 2026-11-12 (screen without control sleeps; Wake button; clock held while controlling or while the agent runs)

## User behaviour

- **Two panes** (off by default, per bot): two-frame button to the left of the tabs — **hidden when the bot has no VM** (`desk.state` not in creating/running/sleeping/error); a saved split preference stays inert until a desk exists again. When active, it keeps the same grey border as the other round buttons. Once enabled, the tabs give way to two lists (Conversation, Terminal, Screen) — the left one then the right one — plus a button to swap them. No "Left / Right" label. The same pane cannot be on both sides: choosing it on the other side **swaps**. The URL follows the left pane (`/discussion`, `/terminal` or `/screen`). Right pane width adjustable (handle, 28–62%) — the drag strip matches `--bg-sidebar` at rest (accent only on hover/focus). Split screen/terminal cards use `height: calc(100% - chrome offset)` so `margin-top` does not clip the bottom Soft radius. Preference in `localStorage` (`autonomous.splitScreen`: `{ bot: { on, left, right } }`). Showing the screen does **not** wake a sleeping desk: the pane stays on **Wake** until the user asks, or the agent wakes the VM itself. Below 900 px, the panes stack.

- **Sleep** (default ON at creation): if the bot is idle and the desktop unused for **5 minutes**, the Docker container is **stopped** (`desk.state=sleeping`). The `~/files` files stay on the host. The clock stays at zero while the user **has control** of the screen (heartbeat `POST /desk/activity` every 60 s) and while the agent is **busy or waiting** (each scheduler tick refreshes `desk_last_active_at`). Sitting on the Screen tab **without** control does not reset the clock and does **not** auto-wake: after the 5 minutes the pane shows **Wake**. Opening Terminal, VM tools, or that button still call `POST /desk/wake`. Can be disabled in **Details** (long scripts).
- **A single VM**: creating the VM always publishes noVNC. The Terminal and Screen tabs open on it. There is no longer a "terminal only" option (the desktop was already running, the port was just hidden). Internet on/off remains the only choice. An old VM without a noVNC port: the Screen tab reopens creation, which replaces the container (`~/files` kept).
- **Screen** tab: the remote desktop stays **1920×1200**; the display **adapts** to the window (`scaleViewport`, mouse realigned by noVNC). No `resizeSession` (grounding coords unchanged).
- **Copy-paste** with the computer: take control of the screen, then Ctrl+C / Ctrl+V (text). Bridge injected into `vnc_lite` (remote copy → local clipboard; local Ctrl+V → VNC clipboard + remote Ctrl+V).
- Coloured frame around the area: orange (`--accent`) when viewing, **green** (`--ok`) when the user has control.
- Background around / behind the iframe: **no black** (`background: transparent` on `.screen-frame`).
- **View only by default**: the desktop is already visible under a transparent veil; a bottom banner "Take control" + hint ("already visible — click for mouse/keyboard"). No large centred text hiding the scene.
- Taking control: click on the veil. Release: click **outside** the area (no "Release" button).
- noVNC connection: `Connexion…` / error / disconnected states + Retry button (postMessage `autonomous-novnc` from the `vnc_lite` injection; the native noVNC status bar stays hidden).
- The Screen panel stays mounted with `v-show` so the desk/noVNC session survives tab changes. In two-pane mode it stays visible as long as one side is Screen (`active` true → wake + noVNC). The visual order comes from the `pane-left` / `pane-right` classes (a single instance of each panel). A window `resize` is emitted on drag and on side change so that `scaleViewport` and the terminal follow.
- If capability is missing **and** the user opens Terminal or Screen → same `CreateDeskModal` modal (internet on/off, no type).
- If **the agent** needs a desk (capability `none` / desk stopped) → `desk_request` **chat card** (title + short hint + Allow / Decline, without terminal/screen type), **centred** in the thread like vault / approval / clarify (not left-aligned as an assistant bubble). The `vm_request_desk` tool **blocks** (like the vault) until Allow+desk `running` or Decline — the agent must **not** chain other tools meanwhile. An already `running` desk is enough for the shell and captures. Allow creates the VM **without a modal**; bot status = `waiting` during the wait / `desk.state=creating`. When the desk goes `running`: if the tool poll is still active → `busy` without a second prompt; otherwise `resume_run`. Decline → `idle`. `CreateDeskModal` remains for a manual click on the Terminal/Screen tabs.
- Manage → **Restart desktop**, **Reset desktop**, and **Remove the VM** (`capability=none`, destroys the container) show only when a desktop exists (`creating`, `running`, `sleeping`, or `error`). They stay hidden while the desk is absent. Each waits for a check icon at the end of the row before it runs. There is no longer a "Remove the screen". Reset still wipes the desktop home folder.

## Implementation

- Docker container named **`autonomous-<uuid>`** (same scheme as Pi sessions). Bot ↔ VM link = `desk.container_name` (+ label `autonomous.bot=<slug>`). Image `autonomous-desktop:fr`.
- Host volume `data/bots/<bot>/home` mounted at **`/home/autonomous/files`**, **`/home/autonomous/workspace`**, and **`/home/autonomous/shared`** (same private source — `shared` is a legacy alias, not a folder other bots can read) — **persists** if the container is stopped or destroyed (except `desk reset` which wipes the volume). Chrome CDP profile: `shared/.autonomous-chrome/` (see [`chrome-desktop-image.md`](./chrome-desktop-image.md)).
- Old desks without `container_name`: legacy fallback `autonomous-<slug>` until recreate.
- Auto-sleep: column `bots.auto_sleep` + `desk_last_active_at`; tick via the `serve` scheduler (~30s). A busy or waiting bot refreshes that stamp on each tick. `POST …/desk/activity` does the same and does not wake. `desk.ensure_awake` / `POST …/desk/wake` before the terminal and VM tools. `GET …/desk/novnc` and the `/novnc/` proxy only report a port while the desk is running.
- Agent: `vm_desk_status` does **not** ask for `vm_request_desk` for a `sleeping` desk (the tools wake it); `vm_request_desk` wakes first if sleeping.
- Host API access from the VM (bridge): `extra_hosts host.docker.internal=host-gateway`, env `AUTONOMOUS_API_BASE` / `AUTONOMOUS_HOOKS_BASE`, helper `autonomous-hook` (see [events.md](./events.md)).
- noVNC port published on localhost; UI via `/novnc/<bot>/` + mux WS upgrade.
- HTTP `/novnc/` and the WebSocket upgrade both require a logged-in session (or Bearer). The mux rejects unauthenticated WS before tunneling to websockify.
- Geometry: `VNC_GEOMETRY=1920x1200` (desk env + entrypoint). Already created desks keep the old geometry until recreate.
- noVNC injection (`app.py`): light background, `viewOnly` / `scale` coerced (beware of the `view_only=0` truthy pitfall in JS — don't return `0` as a boolean) + clipboard bridge.
- Fit to window = `scale=true` + iframe 100% of the pane — **no** forced CSS `width/height` on the noVNC canvas (breaks the mouse).
- Clipboard: images / rich text not guaranteed; HTTP outside localhost may limit `navigator.clipboard` (`execCommand` fallback).

## Pitfalls / non-regressions

- Don't put a `#111` background back on `.screen-frame`.
- Don't force the frame to fixed `1920×1200` px (go back to fill + `scaleViewport`).
- Don't enable `resizeSession`: it would change the remote geometry and break grounding.
- Don't reintroduce a "release" button: release = outside click + cooldown.
- Don't enable two panes by default, nor for all bots: per-bot opt-in. Without this button, Conversation / Terminal / Screen stay a single pane. Don't show the split control when there is no desktop — dual pane is useless without a VM.
- Don't re-centre a large opaque label over the whole viewport: the desktop must stay readable in view-only mode.
- Keep the connect/disconnect `postMessage` in the injection (otherwise the UI thinks it's "stuck" with no feedback).
- Containers created before the `~/files` mount: `serve` start links `~/files` → `workspace` on desks already running, before Pi recovery. Sleeping desks get the link on wake. `~/shared` may still exist (Chrome). New desks bind all three names. The prompt tells the bot not to use `~/shared`.
- Stale Docker image ≠ `docker/desktop/` sources on the host → rebuild or `docker cp` the scripts (`bot-chrome`, etc.).

## Quick check

1. Open `/b/<bot>/screen`.
2. Orange frame visible, no black bars around it; desktop readable under the bottom hint.
3. If VNC drops → message + Retry (not just "Take control").
4. Take control → green frame, mouse OK in Chrome.
5. Switch tab then come back → session still there.
6. Without the two-frame button: a single pane, the usual tabs. Click → two lists without a Left/Right label, URL = left pane. Choosing Screen on the left and Conversation on the right swaps the display without duplicating a pane. Second click on the button → a single pane. Other bot → no split.

## noVNC ports and orphan containers (2026-10-30)

- `_allocate_vnc_port` also skips ports **actually in use on the host** (`_host_port_free`), not only those known in the database: an orphan container no longer blocks creation ("port is already allocated").
- A bot deleted **during** the creation of its desktop no longer leaves a container behind: the job checks the bot still exists after `containers.run` and before finalisation, otherwise `remove(force=True)`.
