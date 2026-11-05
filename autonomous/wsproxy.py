"""Stdlib WebSocket ↔ TCP bridge for noVNC (same origin as the Flask app)."""

from __future__ import annotations

import base64
import hashlib
import logging
import select
import socket
import threading
from typing import Callable

log = logging.getLogger("autonomous.wsproxy")

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _accept_key(key: str) -> str:
    digest = hashlib.sha1((key + GUID).encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def _read_http_headers(conn: socket.socket) -> tuple[str, dict[str, str], bytes]:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
        if len(data) > 65536:
            break
    head, _, rest = data.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1", errors="replace").split("\r\n")
    request_line = lines[0] if lines else ""
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return request_line, headers, rest


def _pipe(a: socket.socket, b: socket.socket) -> None:
    sockets = [a, b]
    try:
        while True:
            readable, _, errored = select.select(sockets, [], sockets, 60)
            if errored:
                break
            if not readable:
                continue
            for src in readable:
                dst = b if src is a else a
                data = src.recv(65536)
                if not data:
                    return
                dst.sendall(data)
    except OSError:
        return
    finally:
        for s in sockets:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass


def handle_novnc_websocket(conn: socket.socket, port: int, leftover: bytes = b"") -> None:
    """Complete WS handshake then tunnel bytes to websockify on localhost:port."""
    try:
        upstream = socket.create_connection(("127.0.0.1", int(port)), timeout=10)
    except OSError as exc:
        log.warning("upstream websockify %s failed: %s", port, exc)
        try:
            conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
        except OSError:
            pass
        conn.close()
        return

    # Client already sent HTTP upgrade request on `conn`; we still need to reply 101.
    # Caller passes parsed key via leftover protocol — see MuxServer.
    raise RuntimeError("use MuxServer path")


class MuxServer:
    """
    Accept TCP on host:port.
    WebSocket upgrades:
      /novnc/<bot>/ → tunnel to that bot's websockify port (session/Bearer)
      /ws/terminal/<bot> → interactive container PTY (session/Bearer)
      /ws/companion → device Bearer (adc_…)
    Everything else is handed to a WSGI request callable via werkzeug.
    """

    def __init__(
        self,
        host: str,
        port: int,
        wsgi_app,
        resolve_bot_port: Callable[[str], int | None],
        terminal_handler: Callable[[socket.socket, str, bytes], None] | None = None,
        companion_handler: Callable[[socket.socket, str, bytes], None] | None = None,
        *,
        home=None,
    ):
        self.host = host
        self.port = port
        self.wsgi_app = wsgi_app
        self.resolve_bot_port = resolve_bot_port
        self.terminal_handler = terminal_handler
        self.companion_handler = companion_handler
        self.home = home
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _require_user_auth(self, headers: dict[str, str], request: socket.socket) -> bool:
        """Reject unauthenticated UI WebSockets (VNC / terminal)."""
        from pathlib import Path

        from autonomous.ws_auth import ws_authenticated

        home = self.home
        if home is None:
            home = Path(getattr(self.wsgi_app, "config", {}).get("AUTONOMOUS_HOME", "data"))
        if ws_authenticated(headers, app=self.wsgi_app, home=Path(home)):
            return True
        try:
            request.sendall(
                b"HTTP/1.1 401 Unauthorized\r\n"
                b"Connection: close\r\n"
                b"Content-Type: text/plain\r\n"
                b"Content-Length: 12\r\n"
                b"\r\n"
                b"Unauthorized"
            )
        except OSError:
            pass
        try:
            request.close()
        except OSError:
            pass
        return False

    def start(self) -> None:
        from werkzeug.serving import make_server

        # Use werkzeug for normal HTTP; wrap via threaded acceptor for WS sniffing.
        self._http = make_server(self.host, self.port, self.wsgi_app, threaded=True)
        dispatch_http = self._http.process_request_thread

        def process_request(request, client_address):
            # Sniff on a worker. A blocking peek on the accept thread stalls
            # every other connection (the browser then sees ERR_EMPTY_RESPONSE).
            threading.Thread(
                target=self._sniff_dispatch,
                args=(request, client_address, dispatch_http),
                daemon=True,
            ).start()

        self._http.process_request = process_request  # type: ignore[method-assign]
        self._thread = threading.Thread(target=self._http.serve_forever, daemon=True)
        self._thread.start()
        log.info("mux server on %s:%s", self.host, self.port)

    def _sniff_dispatch(self, request: socket.socket, client_address, dispatch_http) -> None:
        """Peek for a WebSocket upgrade, then hand HTTP to Werkzeug.

        The 5s peek timeout must not stay on the socket. SSE writes a ping
        every 15s and then blocks; a leftover send timeout kills the stream
        and the browser's reconnect gets net::ERR_EMPTY_RESPONSE.
        """
        try:
            request.settimeout(5)
            peek = request.recv(8192, socket.MSG_PEEK)
        except OSError:
            try:
                request.close()
            except OSError:
                pass
            return
        if not peek:
            try:
                request.close()
            except OSError:
                pass
            return
        if b"\r\n\r\n" in peek and b"upgrade: websocket" in peek.lower():
            self._handle_ws(request, client_address, peek)
            return
        try:
            request.settimeout(None)
        except OSError:
            try:
                request.close()
            except OSError:
                pass
            return
        dispatch_http(request, client_address)

    def _handle_ws(self, request: socket.socket, client_address, peeked: bytes) -> None:
        try:
            # Consume full headers
            data = peeked
            while b"\r\n\r\n" not in data:
                chunk = request.recv(4096)
                if not chunk:
                    request.close()
                    return
                data += chunk
            # Re-sync: we've only peeked; need to actually read
            # After MSG_PEEK, data is still in buffer — read until headers done
            consumed = data
            # Drain exactly what we peeked/read into a clean parse
            # Because we used MSG_PEEK for first recv, buffer still has it.
            # Read and discard until we have headers, tracking bytes.
            buf = b""
            # The socket still contains peeked bytes; read them for real
            while b"\r\n\r\n" not in buf:
                chunk = request.recv(8192)
                if not chunk:
                    request.close()
                    return
                buf += chunk
            request_line, headers, rest = _read_http_headers_from_bytes(buf)
            parts = request_line.split()
            path = parts[1] if len(parts) >= 2 else ""
            # Strip query string
            path = path.split("?", 1)[0]

            key = headers.get("sec-websocket-key")
            if not key:
                request.sendall(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
                request.close()
                return
            accept = _accept_key(key)

            if path == "/ws/companion":
                if not self.companion_handler:
                    request.sendall(b"HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n")
                    request.close()
                    return
                auth = headers.get("authorization", "")
                token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
                response = (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n"
                    "\r\n"
                )
                request.sendall(response.encode("ascii"))
                request.settimeout(None)
                self.companion_handler(request, token, rest)
                return

            # Interactive PTY: /ws/terminal/<bot>
            if path.startswith("/ws/terminal/"):
                segs = [s for s in path.split("/") if s]
                bot = segs[2] if len(segs) >= 3 else None
                if not bot or not self.terminal_handler:
                    request.sendall(b"HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n")
                    request.close()
                    return
                if not self._require_user_auth(headers, request):
                    return
                response = (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n"
                    "\r\n"
                )
                request.sendall(response.encode("ascii"))
                request.settimeout(None)
                self.terminal_handler(request, bot, rest)
                return

            # /novnc/<bot>/ or /novnc/<bot>/websockify
            bot = None
            if path.startswith("/novnc/"):
                segs = path.strip("/").split("/")
                if len(segs) >= 2:
                    bot = segs[1]
            if not bot:
                request.sendall(b"HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n")
                request.close()
                return
            if not self._require_user_auth(headers, request):
                return
            port = self.resolve_bot_port(bot)
            if not port:
                request.sendall(b"HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n")
                request.close()
                return
            proto = headers.get("sec-websocket-protocol")
            extra = ""
            if proto:
                # websockify often uses binary
                first = proto.split(",")[0].strip()
                extra = f"Sec-WebSocket-Protocol: {first}\r\n"
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n"
                f"{extra}"
                "\r\n"
            )
            request.sendall(response.encode("ascii"))

            upstream = socket.create_connection(("127.0.0.1", int(port)), timeout=10)
            # Perform upstream WS handshake with websockify
            up_key = base64.b64encode(b"autonomous-proxy-key-12").decode()
            up_req = (
                f"GET / HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {up_key}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                "\r\n"
            )
            upstream.sendall(up_req.encode("ascii"))
            up_buf = b""
            while b"\r\n\r\n" not in up_buf:
                chunk = upstream.recv(4096)
                if not chunk:
                    raise OSError("upstream closed")
                up_buf += chunk
            if b"101" not in up_buf.split(b"\r\n", 1)[0]:
                raise OSError(f"upstream handshake failed: {up_buf[:200]!r}")
            # If client sent early frames in `rest`, forward them
            if rest:
                upstream.sendall(rest)
            _pipe(request, upstream)
        except Exception as exc:
            log.warning("ws proxy error: %s", exc)
            try:
                request.close()
            except OSError:
                pass

    def shutdown(self) -> None:
        try:
            self._http.shutdown()
        except Exception:
            pass


def _read_http_headers_from_bytes(data: bytes) -> tuple[str, dict[str, str], bytes]:
    head, _, rest = data.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1", errors="replace").split("\r\n")
    request_line = lines[0] if lines else ""
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return request_line, headers, rest
