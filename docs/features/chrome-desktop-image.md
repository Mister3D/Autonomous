# Desktop image & Chrome

**Status**: in place  
**Key files**:
- `docker/desktop/Dockerfile`
- `docker/desktop/bot-chrome`
- `docker/desktop/maximize-window.py`
- `docker/desktop/entrypoint.sh`
- `docker/desktop/chrome-policy.json`
- `docker/desktop/webgl-spoof-cdp.py` / `webgl-spoof.js`

**Last updated**: 2026-11-17 (Chrome starts on demand — not at desk boot)

## Expected behaviour in the VM

- Chrome does **not** autostart with the desk (no XFCE `chrome.desktop`, no `xstartup` launch, no `restart_bot_chrome` on create/wake). The first **`browser_*`** tool runs `ensure_bot_chrome` on the host. Soft CDP reads after a VNC gesture (`page_marker` / `read_after_gesture`) must **not** start Chrome — otherwise `vm_click` on a calculator spawned `about:blank` over the desk. Desk create/wake also kills leftover Chrome from legacy images. Shell-only / calculator tasks keep a light desktop.
- When started, Chrome opens **maximised** on the 1920×1200 desktop (usable area ~1920×1171 excluding the bar).
- **Chrome sandbox enabled** (default): the desk starts with `security_opt: seccomp=unconfined` so that the zygote/userns works. **No** `--no-sandbox` or `--test-type` except the escape hatch `BOT_CHROME_NO_SANDBOX=1`. If CDP doesn't come up → **explicit error** (no half-dead browser).
- Useful flags in `bot-chrome`: `--start-maximized`, `--remote-debugging-port`, `--lang=fr-FR`, plus CDP helper/`maximize-window.py`.
- **Persistent CDP profile**: `BOT_CHROME_USER_DATA_DIR` = **`$HOME/shared/.autonomous-chrome`** (host bind-mount `data/bots/<bot>/home`). Cookies / localStorage / anti-bot "clearance" cookies survive a container **recreate**. The old path `$HOME/.autonomous-chrome` (container layer) is migrated on first launch. Not `~/.config/google-chrome` (Chrome ≥136 ignores remote-debugging on it).
- **Locale / TZ**: desk `TZ=Europe/Paris`, `LANG=fr_FR.UTF-8` (otherwise `UTC` + `en-US` vs FR IP = anti-bot signal).
- **Translate disabled**: policy `TranslateEnabled: false`, prefs `translate.enabled=false` + blocked languages, flag `--disable-features=Translate,TranslateUI`.
- **No welcome / EULA screens**: `First Run` and `EULA Accepted` sentinel files in the profile (Chrome 151 shows the « Additional Terms of Service » dialog by default unless `EULA Accepted` is present; `--no-first-run` alone does not skip it). `bot-chrome` writes that file before every launch. Waking a desk writes it into the running container as well, and tries once to accept a dialog that is already open, without restarting Chrome. Prefs `distribution.require_eula=false`, `--no-first-run` / `--no-default-browser-check`, and `dismiss-chrome-tos.py` (xdotool → Accept) remain as a safety net. The EU search-engine choice dialog is skipped with `--disable-features=SearchEngineChoice` and `default_search_provider.choice_screen.completion_timestamp`.
- Spoofed WebGL fingerprint (Intel UHD 620 via CDP) — see env `UNMASKED_VENDOR_WEBGL` / `UNMASKED_RENDERER_WEBGL`. Without an active spoof, Chrome exposes **`llvmpipe`** (software GPU) → very bot-like (detected by anti-bots).
- Spoof OK ≠ site OK: an anti-bot may still show an interstitial (CDP remote-debugging, etc.). The GPU is only one signal.

### What is `--no-sandbox`?

Chrome isolates each tab in an OS **sandbox** (namespaces / seccomp). In "tight" Docker, this sandbox often fails (`Operation not permitted` on PID namespaces) — hence the habit of passing `--no-sandbox`, which **turns off** this isolation. Consequences: (1) less safe if a page is malicious; (2) **very visible** to anti-bots, which read the flags / environment. We prefer to loosen Docker a little (`seccomp=unconfined`) and keep the Chrome sandbox, rather than a browser that "works" but is fingerprinted as a bot.
- Useful shell / GUI packages (via Dockerfile): `nano`, `vim-tiny`, `less`, `galculator`, `drawing`, `libreoffice-calc`, `wmctrl`. Agents still may `sudo apt-get install` anything else the task needs.
- Downloads → `/home/autonomous/shared` (policy in the image). That path is the same private folder as `~/files` and `~/workspace`, not a folder other bots can read.

## Rebuild

`autonomous serve` builds the image in the background when it is missing or when files under `docker/desktop/` change (hash in `$AUTONOMOUS_HOME/desk-image/status.json`). Manual:

```bash
cd docker/desktop
docker build -t autonomous-desktop:latest .
```

**New** desks use this image. An already created container keeps its filesystem until recreate/reset.

## Hot-patch (debug)

If the VM is still running with an old `/usr/local/bin/bot-chrome`:

```bash
# Replace <container> with desk.container_name (autonomous-<uuid>), not the bot slug.
docker cp docker/desktop/bot-chrome <container>:/tmp/bot-chrome.new
docker exec -u root <container> install -m 755 /tmp/bot-chrome.new /usr/local/bin/bot-chrome
docker cp docker/desktop/chrome-policy.json <container>:/tmp/autonomous.json
docker exec -u root <container> install -m 644 /tmp/autonomous.json /etc/opt/chrome/policies/managed/autonomous.json
# same for maximize-window.py; then kill Chrome and relaunch bot-chrome
```

## Pitfalls

- Repo up to date ≠ container up to date. Always check the Chrome cmdline in the container (`--test-type`, `Translate`, absence of `--disable-setuid-sandbox`).
- Don't reintroduce `--disable-setuid-sandbox` or `--no-sandbox` by default in `bot-chrome`.
- Desks **already created** before `seccomp=unconfined`: **recreate** the desktop (otherwise Chrome without sandbox flags may crash — that's intended: better an error than a flagged bot).
- Don't force SwiftShader (`--use-gl=swiftshader`) — anti-bot fingerprint.
- **"Native" WebGL spoof**: `webgl-spoof.js` wraps the original `getParameter` in a `Proxy` (no marker property) and masks `Function.prototype.toString` (`[native code]`). The daemon uses `Target.setAutoAttach` with `waitForDebuggerOnStart: true` (page, iframe, **Worker / SharedWorker / ServiceWorker**): the spoof is set before any page script, then `Runtime.runIfWaitingForDebugger` is **always** called (`finally`) so as never to freeze a tab. Verified with CreepJS: the Worker's GPU is no longer `llvmpipe`. 
- **Fonts**: the image installs ~260 faces (Liberation, DejaVu, Noto core/mono/emoji, Roboto, Open Sans, Lato, Cantarell, Carlito/Caladea = Calibri/Cambria metrics, Inconsolata, FreeFont, Droid fallback). Measured by canvas width: 14 common families detected (Arial/Helvetica/Times/Courier via Liberation fontconfig aliases) versus 7 before. Proprietary MS fonts (Verdana, Segoe UI…) remain absent (licence). **Image must be rebuilt** (`docker build -t autonomous-desktop:latest docker/desktop`); already created desks keep their old fonts until recreate/reset.
- **New tabs**: `_spoof_page` first registers `Page.addScriptToEvaluateOnNewDocument` (without `runImmediately`), then `Runtime.evaluate` best effort (3 s). Before, `runImmediately` on a tab opened by `target=_blank` (without a document) timed out and left the tab **blank forever**.
- **Media devices**: `webgl-spoof.js` wraps `MediaDevices.enumerateDevices`: if the native list is empty (container without camera/mic), returns 3 entries (`audioinput`, `videoinput`, `audiooutput`, empty id/label = state of a browser without permission), real `MediaDeviceInfo`, masked `toString`. A real list is never modified. `getUserMedia` is not simulated. Also applied to existing desks (script synced on Chrome restart).
- **`webgl-spoof-cdp.py`**: the CDP reader must **never** `await call()` on an event (deadlock → 10s timeout → dead spoof → `llvmpipe` in the clear). Spoof via `asyncio.create_task` + reconnection.
- No `/dev/dri` in the container → real GPU impossible; the JS spoof is mandatory.
- Chrome preferences (`window_placement.maximized`) help at startup; the maximizer remains a safety net.
- If `curl 127.0.0.1:9222/json/version` refuses in headed mode: check that Chrome is not using `~/.config/google-chrome` (hot-patch `bot-chrome` + kill Chrome + relaunch).
- On desk **creation**, the host syncs `docker/desktop/bot-chrome` (+ WebGL spoof, `xstartup`, etc.) and **does not** start Chrome. The first `browser_*` tool calls `ensure_bot_chrome` → `restart_bot_chrome` so CDP uses the synced script + `shared/.autonomous-chrome` (not a stale image default profile).
- **`desk.state` stays `creating` until the job has finished** (script sync). `desk.status()` no longer switches it to `running` as soon as the Docker container is running (except `creating` > 240 s = dead job).
- After the first browser tool: `curl 127.0.0.1:9222/json/version` = 200, cmdline with `--user-data-dir=…/shared/.autonomous-chrome`, spoof log "WebGL spoof applied". Before any browser tool, CDP may be down — that is expected.
- `desk reset` (volume wipe) **also erases** the shared Chrome profile — deliberate recreate = new fingerprint.
- **No** `--disable-blink-features=AutomationControlled`: Chrome ≥ 150 shows an "unsupported command-line flag" bar (automation signal, and it shifts the viewport) while `navigator.webdriver` stays `false` with `--remote-debugging-port` alone. Verified: bot.sannysoft.com all green, bot-detector.rebrowser.net without `runtimeEnableLeak` or `navigatorWebdriver`.
- `desk restart` **does not resync** `bot-chrome` (only `desk create` does): after modifying the script, **recreate** the desktop (destroy + create) to test.
- Remaining detectable flags: `--remote-debugging-port` (needed for the WebGL spoof / agent). Avoid `--no-sandbox` / `--test-type`.
- Rebuild the image when the repo moves forward: `docker build -t autonomous-desktop:latest docker/desktop` (avoids depending on the hot-sync). Live desks also get `xstartup` + removal of `~/.config/autostart/chrome.desktop` via `sync_desktop_scripts` (create/wake).

## Quick check

```bash
pytest tests/test_ensure_bot_chrome.py -q
# Desk up, no browser tool yet → CDP 9222 down, no chrome process.
# After browser_tabs / navigate → curl 127.0.0.1:9222/json/version = 200
```
