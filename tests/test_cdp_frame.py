"""A short read timeout must not split a Chrome CDP frame."""

import json
import socket

from autonomous.services.cdp_client import CdpError, _Ws


def _frame(text: str) -> bytes:
    raw = text.encode("utf-8")
    return bytes([0x81, len(raw)]) + raw


class _Sock:
    def __init__(self, pieces: list):
        self.pieces = list(pieces)
        self.timeout = None
        self.closed = False
        self.recvs = 0

    def settimeout(self, value):
        self.timeout = value

    def recv(self, _n):
        self.recvs += 1
        if not self.pieces:
            return b""
        item = self.pieces.pop(0)
        if item == "timeout":
            raise socket.timeout("timed out")
        return item

    def close(self):
        self.closed = True


def _ws(pieces: list) -> _Ws:
    ws = object.__new__(_Ws)
    ws._sock = _Sock(pieces)
    ws._buf = bytearray()
    ws._timeout = 5.0
    ws._n = 0
    return ws


def test_a_timeout_in_the_middle_of_a_frame_still_returns_the_message():
    raw = _frame(json.dumps({"method": "Page.loadEventFired"}))
    ws = _ws([raw[:1], "timeout", raw[1:3], raw[3:]])
    ws._sock.settimeout(0.5)
    msg = ws.recv_json()
    assert msg["method"] == "Page.loadEventFired"
    assert ws._sock.timeout == 5.0


def test_an_idle_timeout_with_nothing_buffered_is_a_timeout():
    ws = _ws(["timeout"])
    try:
        ws.recv_json()
    except socket.timeout:
        return
    raise AssertionError("expected a timeout")


def test_an_absurd_frame_closes_the_socket_instead_of_being_read():
    header = bytes([0x81, 127]) + (2**32).to_bytes(8, "big")
    ws = _ws([header])
    try:
        ws.recv_json()
    except CdpError as exc:
        assert "too large" in str(exc)
    else:
        raise AssertionError("expected CdpError")
    assert ws._sock.closed
    assert ws._sock.recvs == 1
