"""SSE bus: heartbeats and client-disconnect detection."""

from __future__ import annotations

import socket
import threading
import time

from autonomous.services.events import EventBus, peer_closed


def test_peer_closed_on_fin():
    a, b = socket.socketpair()
    try:
        assert peer_closed(a) is False
        b.close()
        # FIN is readable.
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and not peer_closed(a):
            time.sleep(0.01)
        assert peer_closed(a) is True
    finally:
        a.close()


def test_stream_stops_when_client_goes_away():
    bus = EventBus()
    stopped = threading.Event()

    def stop_check() -> bool:
        return stopped.is_set()

    chunks: list[str] = []

    def consume():
        for chunk in bus.stream("sse-test", heartbeat=0.2, stop_check=stop_check):
            chunks.append(chunk)

    t = threading.Thread(target=consume, daemon=True)
    t.start()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not chunks:
        time.sleep(0.01)
    assert chunks and chunks[0].startswith("event: ping")
    stopped.set()
    t.join(timeout=2)
    assert not t.is_alive()
