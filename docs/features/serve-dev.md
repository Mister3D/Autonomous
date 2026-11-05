# Server: `serve` / stop / `--dev`

**Status**: in place  
**Key files**:
- `autonomous/cli.py` (`cmd_serve`, `serve stop`, reloader, vite watch)
- `autonomous/paths.py` (`serve.pid`, `vite-watch.pid`)
- `autonomous/wsproxy.py` (`MuxServer` in front of Werkzeug)

**Last updated**: 2026-11-05 (bind public guard + WS auth)

## Behaviour

```bash
autonomous serve --host 127.0.0.1 --port 8787
autonomous serve stop
autonomous serve --host 127.0.0.1 --port 8787 --dev
```

- `serve stop`: kills via `serve.pid` (SIGTERM then SIGKILL if needed).
- `--dev`:
  - Python autoreload (files under the package)
  - `vite build --watch` → writes to `autonomous/static/`
  - signals only on the **main thread** (avoids reloader crash)
  - on stop: clean up the Vite process group (`killpg` / `pkill`)

## Mux

A single TCP port:

- HTTP → Flask (UI + `/api/v1`)
- WS `/novnc/<bot>/…` → the desk's websockify (session cookie or Bearer required)
- WS `/ws/terminal/<bot>` → PTY (`ptyws.py`, same auth)
- Non-loopback `--host` is refused unless `AUTONOMOUS_BIND_PUBLIC=1`. `serve` also refuses to start without `init` / token (unless `AUTONOMOUS_ALLOW_INSECURE=1`).

## Pitfalls

- Two `serve` instances: check `serve.pid` / "already running" message.
- In `--dev`, an orphan Vite may serve old assets: `serve stop` then relaunch.
- Don't install system packages without asking the user.
- The WebSocket sniff (5 s timeout, `MSG_PEEK`) must **not** stay on the HTTP socket, nor block the thread that does `accept`. Otherwise `GET /api/v1/events` (SSE, ping every 15 s) is cut; the browser retries and shows `net::ERR_EMPTY_RESPONSE`. The bus drops the subscription as soon as the client sends FIN (a successful write in `CLOSE-WAIT` is not enough to detect the close).
- Don't send `Connection: keep-alive` on the SSE: Werkzeug already adds `Connection: close`. Two `Connection` headers make the stream fail on the browser side.
- The client (`frontend/src/sync.js`) does not reopen `EventSource` on every route change: closing a GET that has not yet been answered produces the same `ERR_EMPTY_RESPONSE`.

## Quick check

`curl -s http://127.0.0.1:8787/api/v1/health` then `autonomous serve stop`.
