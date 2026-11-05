"""Minimal Chrome DevTools Protocol client (stdlib WebSocket).

Runs against a CDP HTTP endpoint (typically 127.0.0.1:9222 inside the desk).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import urllib.error
import urllib.request
from typing import Any


class CdpError(RuntimeError):
    pass


def _http_json(url: str, timeout: float = 5.0) -> Any:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise CdpError(f"CDP HTTP unreachable: {exc}") from exc


def list_targets(base: str = "http://127.0.0.1:9222") -> list[dict[str, Any]]:
    base = base.rstrip("/")
    data = _http_json(f"{base}/json/list")
    if not isinstance(data, list):
        raise CdpError("Unexpected /json/list payload")
    return data


def pick_page(targets: list[dict[str, Any]], *, url_contains: str | None = None) -> dict[str, Any]:
    pages = [t for t in targets if t.get("type") == "page"]
    if url_contains:
        needle = url_contains.lower()
        pages = [t for t in pages if needle in str(t.get("url") or "").lower()]
    if not pages:
        raise CdpError("No Chrome page target found (is Chrome running with CDP?)")
    # Prefer non-blank, most recently focused is usually first in list.
    for t in pages:
        u = str(t.get("url") or "")
        if u and not u.startswith("chrome://") and u != "about:blank":
            return t
    return pages[0]


class _Ws:
    def __init__(self, url: str, timeout: float = 15.0):
        if not url.startswith("ws://"):
            raise CdpError(f"Unsupported WS URL: {url}")
        rest = url[5:]
        hostport, _, path = rest.partition("/")
        path = "/" + path
        if ":" in hostport:
            host, port_s = hostport.rsplit(":", 1)
            port = int(port_s)
        else:
            host, port = hostport, 80
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {hostport}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        self._sock.sendall(req)
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise CdpError("CDP WebSocket handshake closed")
            buf += chunk
        header, _, _ = buf.partition(b"\r\n\r\n")
        if b"101" not in header.split(b"\r\n", 1)[0]:
            raise CdpError(f"CDP WS handshake failed: {header[:200]!r}")
        expect = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        )
        if expect not in header:
            # Some servers omit echoing; continue if 101.
            pass
        self._n = 0

    def send_json(self, obj: dict[str, Any]) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        header = bytearray([0x81])  # text, FIN
        n = len(raw)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", n))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack(">Q", n))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(raw))
        self._sock.sendall(bytes(header) + masked)

    def recv_json(self) -> dict[str, Any]:
        while True:
            hdr = self._recv_exact(2)
            opcode = hdr[0] & 0x0F
            masked = bool(hdr[1] & 0x80)
            ln = hdr[1] & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", self._recv_exact(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(ln)
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:  # close
                raise CdpError("CDP WebSocket closed")
            if opcode == 0x9:  # ping → pong
                self._sock.sendall(bytes([0x8A, len(payload)]) + payload)
                continue
            if opcode not in (0x1, 0x2):
                continue
            return json.loads(payload.decode("utf-8"))

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise CdpError("CDP WebSocket EOF")
            buf.extend(chunk)
        return bytes(buf)

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class CdpSession:
    def __init__(self, ws_url: str, timeout: float = 20.0):
        self._ws = _Ws(ws_url, timeout=timeout)
        self._id = 0
        self._timeout = timeout

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._id += 1
        msg_id = self._id
        payload: dict[str, Any] = {"id": msg_id, "method": method}
        if params:
            payload["params"] = params
        self._ws.send_json(payload)
        while True:
            msg = self._ws.recv_json()
            if msg.get("id") == msg_id:
                if "error" in msg:
                    err = msg["error"]
                    raise CdpError(f"{method}: {err.get('message') or err}")
                return msg.get("result")
            # ignore events

    def poll(self, timeout: float = 0.5) -> dict[str, Any] | None:
        """Read next CDP message (event or stray reply). None on socket timeout."""
        sock = self._ws._sock
        old = sock.gettimeout()
        try:
            sock.settimeout(max(0.05, float(timeout)))
            return self._ws.recv_json()
        except (TimeoutError, socket.timeout, OSError):
            return None
        finally:
            try:
                sock.settimeout(old if old is not None else self._timeout)
            except OSError:
                pass

    def close(self) -> None:
        self._ws.close()


def connect_page(base: str = "http://127.0.0.1:9222", *, url_contains: str | None = None) -> tuple[CdpSession, dict[str, Any]]:
    target = pick_page(list_targets(base), url_contains=url_contains)
    ws = target.get("webSocketDebuggerUrl")
    if not ws:
        raise CdpError("Target has no webSocketDebuggerUrl")
    return CdpSession(ws), target


def connect_target(
    target: dict[str, Any] | None = None,
    *,
    target_id: str | None = None,
    base: str = "http://127.0.0.1:9222",
) -> tuple[CdpSession, dict[str, Any]]:
    """Connect to any CDP target (page or cross-origin iframe)."""
    if target is None:
        if not target_id:
            raise CdpError("target or target_id required")
        matches = [t for t in list_targets(base) if t.get("id") == target_id]
        if not matches:
            raise CdpError(f"CDP target not found: {target_id}")
        target = matches[0]
    ws = target.get("webSocketDebuggerUrl")
    if not ws:
        raise CdpError("Target has no webSocketDebuggerUrl")
    return CdpSession(ws), target
