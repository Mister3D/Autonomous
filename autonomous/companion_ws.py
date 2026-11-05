"""WebSocket endpoint for a paired companion (/ws/companion)."""

from __future__ import annotations

import logging
import socket
import threading
from pathlib import Path

from autonomous.ptyws import ws_recv, ws_send
from autonomous.services.companion_proto import OP_PING, decode_frame, encode_frame
from autonomous.services.companion_link import CompanionSession, hub_for
from autonomous.services.devices import device_from_token, touch

log = logging.getLogger("autonomous.companion")


class _SockBuf:
    def __init__(self, sock: socket.socket, pre: bytes) -> None:
        self._sock = sock
        self._pre = bytearray(pre)

    def recv(self, n: int) -> bytes:
        if self._pre:
            out = bytes(self._pre[:n])
            del self._pre[:n]
            return out
        return self._sock.recv(n)

    def sendall(self, data: bytes) -> None:
        self._sock.sendall(data)

    def settimeout(self, value) -> None:
        self._sock.settimeout(value)

    def close(self) -> None:
        self._sock.close()


def attach_companion(conn: socket.socket, home: Path, token: str, leftover: bytes = b"") -> None:
    # Token already validated before the HTTP 101 in wsproxy; re-check defensively.
    device = device_from_token(token, home=home)
    if device is None:
        try:
            conn.close()
        except OSError:
            pass
        return

    sock = _SockBuf(conn, leftover)
    lock = threading.Lock()

    def send_frame(op: int, stream_id: int, payload: bytes = b"") -> None:
        with lock:
            ws_send(sock, encode_frame(op, stream_id, payload))

    session = CompanionSession(device["id"], send_frame)
    session.start_listeners()
    hub = hub_for(home)
    hub.attach(device["id"], session)
    touch(device["id"], home=home)
    log.info("companion connected %s (%s)", device["name"], device["id"])
    try:
        while True:
            frame = ws_recv(sock)
            if frame is None:
                break
            _opcode, data = frame
            try:
                op, stream_id, payload = decode_frame(data)
            except ValueError:
                continue
            if op == OP_PING:
                touch(device["id"], home=home)
            session.handle_frame(op, stream_id, payload)
    except Exception as exc:
        log.warning("companion socket closed: %s", exc)
    finally:
        hub.detach(device["id"], session)
        try:
            sock.close()
        except OSError:
            pass
        log.info("companion disconnected %s", device["id"])
