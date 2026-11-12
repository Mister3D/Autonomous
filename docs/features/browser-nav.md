# Autonomous web navigation (CDP + VNC)

**Status**: in place (generic — no site hacks)  
**Key files**: `autonomous/services/browser.py`, `chrome_cdp_worker.py`, `cdp_client.py`, `desk_input.py` (scroll/key/drag), `pi_extensions/browser.ts` + `vm.ts`, `POST /bots/:name/browser/*`, `POST …/screen/scroll|key|drag|ground`  
**Last updated**: 2026-11-12 (DOM finds the point; the click is always a real pointer)

## Action loop (enforced order)

The DOM says **where**. The pointer does the **click**. A CDP click (`browser_click_selector`, `el.click()`) is a bot signal and is not the path.

| Step | Tool | Role |
|-------|--------|------|
| 1. Read | **`browser_snapshot`** / **`browser_frames_snapshot`** | Controls with `screen=x,y`, overlays, `[FOCUSED]`, `[filled N chars]`. No gesture |
| 2. Locate the rest | **`vm_ground`** | Only when the control is absent from that read (canvas, image, native dialog, drawn widget). Slow (~10 s). If `ok=false`, do not click |
| 3. Act | **`vm_click`** / **`vm_drag`** / **`vm_type`** / **`vm_scroll`** | Real VNC pointer and keys. The mouse glides to the point |
| 4. Eyes | **`vm_look`** | When the snapshot is empty or inconclusive, or before reporting an error. Not before every click. Its x/y are guesses |

Do not steer the site with CDP scripts, in-page `fetch`, `curl`, or `wget`. Do not mash Backspace because `[filled N chars]` disagrees with the screen: one `vm_look`, then move on.

**Slider**: a `SLIDE-TO-VERIFY WIDGET` line is one `vm_drag` at the printed coordinates (still a real drag).

**Navigation discipline** (enforced): `browser_navigate` is the **first open** only. If the tab is already an http(s) page, every URL change is refused (`code=url_change`) — including reload and a link that is on the page. The first URL must be one a **user** message wrote, or that site's homepage (`code=invented_url` otherwise). An assistant sentence that names a path does not make it allowed. After that, take the **shortest path** on screen: click the visible target, do not detour. A Google search is the address bar (query, then Enter), never a site URL. A reload is one click on the refresh icon. Never bypass a browser security warning.

**Block page** ("access restricted / denied / unusual traffic", with no usable widget) = a decision about the **session** (cookies/state), not a puzzle: no reload loops, **no curl/wget** to the site from the VM, no home-made CDP/websocket scripts, no package installs. Recovery (only if `vm_look` confirms the page): `browser_reset_session` → click the refresh icon → start over from what is on screen (log in again), **2 resets max** per site, otherwise report to the user (text seen + attempts). Do not `browser_navigate` to a new URL. See `_VM_SYSTEM_HINT` in `pi_rpc.py`.

**Typing secrets / fields**: `vm_look` says which field is filled. `vault_type` **refuses** to type if the Chrome window has focus and the active element is not an editable field (iframe / terminal / CDP unavailable: not blocked), and accepts `password` as an alias when the entry has only one secret. The retry is `vm_ground` + `vm_click` on the field you see. `vm_look` must **never** provide coordinates.

**Waiting for load**: `browser_wait_load` (`POST /bots/:name/browser/wait_load {timeout?}`, default 15 s, max 30 s) replaces `sleep N`: `readyState == complete` on 2 consecutive polls, CDP reconnection if Chrome starts / changes page, and **never blocking** — a page that loads forever returns `timed_out=true` (often already usable). `browser_navigate` already waits for `load` (20 s max).

**Forms**: `browser_snapshot` `screen=` → `vm_click` (real mouse) → type. A point **rejected** by `vm_ground` must never be clicked (real case: it was a "send a code by e-mail" button instead of the password field → false OTP block). Do not reload the form or mash Backspace because a DOM counter disagreed with the screen.

**Verification widgets** (cross-origin iframe): `browser_frames_snapshot` `screen=` when the control is readable, otherwise one `vm_ground`, then one `vm_drag` or `vm_click` (real pointer). A single careful attempt then check; don't stretch a drag beyond ~320px. **No** instructions specific to a site or captcha vendor in the prompts. The slider line printed by `browser_navigate` / `browser_wait_load` is one `vm_drag`.

**Block page** ("access restricted / denied / unusual traffic", with no usable widget) = a reputation decision, not a puzzle: no reload loops, **no curl/wget** to the site from the VM (same IP), no home-made CDP/websocket scripts, no package installs; one click on the refresh icon, then report to the user if it is still blocked (text seen + what was tried). See `_VM_SYSTEM_HINT` in `pi_rpc.py`.

If `in_viewport=false` on the target → **`vm_scroll`** (VNC wheel) until it is visible, **then** ground. Don't "teleport" the page.

### Anti-bot: scroll vs jump

| Method | Detectable? | Use |
|---------|--------------|--------|
| `vm_scroll` (VNC wheel) | Low — real mouse events | **Prefer** to reveal content |
| CDP `window.scrollBy` / `scrollTo` | Medium — no `wheel` | `browser_scroll`: avoid on protected pages |
| CDP `scrollIntoView` + `el.click()` | High — classic bot | `browser_click_selector`: avoid on anti-bot |
| Reading the DOM via CDP (`snapshot`) | Low *visually* (no movement); CDP can be fingerprinted | Not the navigation plan — the agent looks at the screen |

Moving **directly** to an offset without the wheel (jump) is often a bot signal. Look, **wheel** if the target is off screen, ground, click/drag.

## Layers

| Layer | Tools | Role |
|--------|--------|------|
| CDP read | `browser_snapshot`, `browser_frames_snapshot`, `browser_tabs`, `browser_wait_load` | Where the control is. `browser_navigate` is the first open only |
| VNC | `vm_scroll`, `vm_key`, `vm_click`, `vm_drag`, `vm_type` | The gesture. Always a real pointer, including when the point came from the DOM |
| Vision | `vm_look`, `vm_ground` | When the DOM does not list the control, or the read is inconclusive |

## API

```
GET  /bots/:name/browser/tabs
POST /bots/:name/browser/navigate       {url}                      → + slider_hints[] (same as wait_load)
POST /bots/:name/browser/snapshot       {max_elements?, query?}   → + overlays[] ; elements[].occluded_by
POST /bots/:name/browser/frames_snapshot {max_elements?, query?}   → + slider_hints[], query_fallback, frames[].box_screen
POST /bots/:name/browser/switch_tab     {index? | match?}          # brings the tab to the foreground (the other tools follow it)
POST /bots/:name/browser/close_tab      {index? | match?}          # default: active tab; the last tab is never closed
POST /bots/:name/browser/text           {max_chars?}
POST /bots/:name/browser/links          {query?, max_links?}
POST /bots/:name/browser/html           {selector?, max_chars?}
POST /bots/:name/browser/wait_load      {timeout?}
POST /bots/:name/browser/reset_session  {}
POST /bots/:name/browser/scroll         {dy?, dx?}
POST /bots/:name/browser/click_selector {selector}
POST /bots/:name/screen/scroll          {dy, x?, y?}
POST /bots/:name/screen/key             {key, repeats?}
POST /bots/:name/screen/drag            {x,y,x2,y2}
POST /bots/:name/screen/ground          {instruction, action_hint?}
POST /bots/:name/screen/describe        {question?, show_in_chat?}  → {ok,text,screenshot_id} (tool `vm_look`)
```

`action_hint` ∈ `click|left_click|right_click|double|drag|scroll`.

Chrome CDP `:9222`; profile `$HOME/.autonomous-chrome` (see `chrome-desktop-image.md`).

## Realistic VNC gestures (`vnc_type_worker.py`)

- **Mouse**: never teleports. The pointer glides from its last position (stored in the container's `/tmp/.autonomous-pointer.json`) to the target: Bézier curve, ease-in-out, micro-jitter, 30–70 `mousemove`s; "aiming" pause 70–220 ms; press 50–130 ms. Drag / wheel also start from that position.
- **Typing**: 40–130 ms between keys (+ occasional hesitations), key held 25–75 ms. Beyond 150 characters the pace is sped up (30 s exec budget). `paste` unchanged.
- **Ambient drift**: after each successful `browser_navigate`, the cursor drifts 2–4 times (no button) via `desk_input.wander` in a daemon thread — a mouse frozen until the 1st click is a bot signal. Modes that move the pointer (`click`/`drag`/`scroll`/`wander`) are **serialised** by a `flock` (`/tmp/.autonomous-pointer.lock`): a click launched during the drift waits for it to end (~3 s).
- Pitfall: the old typing at ~125 chars/s (`sleep(0.008)`) and the click without a trajectory were the "speed too regular" signals of anti-bot block pages.

## Verification widgets: generic detection (2026-10-30)

- `browser_navigate` / `browser_wait_load` / `browser_frames_snapshot` return `slider_hints[]`: a "slide to verify" widget is detected **without a vendor name** (role `slider`, or classes `slider|handle|thumb|knob|drag…`; destination = `target|goal|end` element, otherwise end of the track). The TS prints `SLIDE-TO-VERIFY WIDGET … vm_drag(x,y,x2,y2)`: the agent does **a single** drag at the exact DOM coordinates, without `vm_ground`/`vm_look` (that was the source of bad drags, hence blocks).
- LLM-free test bench (reset_session → navigate → frames_snapshot → drag) on a real site's widget: 8/8, ~15 s each.
- `frames_snapshot`: a `query` with no result **falls back to the full list** (`query_fallback`) — a failed filter must never hide the widget. Each iframe has its **own offset** (`DOM.getFrameOwner` + `getBoxModel`; before: the 1st iframe's offset for all) and a `box_screen`. Iframe with no readable control (drawn widget, e.g. closed checkbox): the TS gives the box + its centre → `vm_ground`/`vm_click` inside that box.
- Tabs: a `target=_blank` link opens a tab that **loads** (the spoof daemon set `addScriptToEvaluateOnNewDocument` with `runImmediately` on a tab without a document → hang; now hook first, immediate execution best effort). Tools follow the foreground tab; `browser_switch_tab` / `browser_close_tab` to drive them.
- Hover: `vm_click button=move` (hover only, no click) for menus that open on hover.
- Known limit: **image** challenges (reCAPTCHA grid "select the traffic lights") exceed current vision — the agent keeps trying until timeout.

## "Generic navigation" test bench (2026-10-30)

20 agent tasks (real LLM): 12 on a demo site (dynamic wait, native `alert/prompt`, hover, drag&drop, editor iframe, shadow DOM, keys, select, new tab, nested frames, basic auth, Wikipedia reading) and 8 on real sites with cookies/anti-bot (newspaper, search engine, code forge, video, marketplace, booking, classifieds, rental): **all succeeded**, 9–130 s. Turnstile: succeeded (82 s). reCAPTCHA v2 with image grid: failed (see limit).

## Serial validation (2026-10-29)

10 consecutive runs, fresh bot + desk each time (image with extended fonts + `enumerateDevices` spoof), "get my latest order" scenario: **10/10 succeeded**, 140–248 s (average ≈ 195 s) after the screen was ready, 46–74 tools per run. No block page encountered → `browser_reset_session` **not exercised** in real conditions (only checked by hand).

## Pitfalls / non-regressions

- `vm_look` is not refused for lack of a DOM snapshot. `observe_gate.refuse_vm_look_message` always returns `None`. Do not put the DOM-first gate back: it made the agent debug focus and filled-char counts instead of looking at the screen.

## Quick check

```bash
TOKEN=$(cat data/token)
curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"max_elements":20}' http://127.0.0.1:8787/api/v1/bots/playmo/browser/snapshot | head -c 600
python3 -m pytest tests/test_observe_gate.py tests/test_url_policy.py -q
```

Restart the Pi session after changing `browser.ts` / `vm.ts` (`DELETE …/messages` or stop_all) so the new system hint / tool text loads.
