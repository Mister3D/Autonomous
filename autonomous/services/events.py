"""In-process SSE event bus (global + per-bot). Visible across all browser tabs."""

from __future__ import annotations

import json
import queue
import select
import socket
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Event:
    name: str
    data: dict[str, Any]
    bot: str | None = None
    ts: str = field(default_factory=_now)

    def to_sse(self) -> str:
        payload = {"ts": self.ts, "bot": self.bot, **self.data}
        return f"event: {self.name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[str, list[queue.Queue[Event | None]]] = defaultdict(list)
        # channel keys: "*" global, or bot name

    def subscribe(self, channel: str = "*") -> queue.Queue[Event | None]:
        q: queue.Queue[Event | None] = queue.Queue(maxsize=256)
        with self._lock:
            self._subs[channel].append(q)
        return q

    def unsubscribe(self, channel: str, q: queue.Queue[Event | None]) -> None:
        with self._lock:
            if q in self._subs[channel]:
                self._subs[channel].remove(q)

    def listener_count(self, channel: str = "*") -> int:
        with self._lock:
            return len(self._subs.get(channel, []))

    def publish(self, name: str, data: dict[str, Any], bot: str | None = None) -> Event:
        ev = Event(name=name, data=data, bot=bot)
        with self._lock:
            targets = list(self._subs.get("*", []))
            if bot:
                targets.extend(self._subs.get(bot, []))
        for q in targets:
            try:
                q.put_nowait(ev)
            except queue.Full:
                # Drop oldest-ish by skipping; keep publisher non-blocking
                pass
        return ev

    def stream(
        self,
        channel: str = "*",
        heartbeat: float = 15.0,
        stop_check: Callable[[], bool] | None = None,
    ) -> Iterator[str]:
        q = self.subscribe(channel)
        try:
            yield Event("ping", {"ok": True}).to_sse()
            last = time.monotonic()
            while True:
                # A client FIN is invisible to a write-only stream (CLOSE-WAIT
                # still accepts pings). Check at least once a second.
                if stop_check and stop_check():
                    return
                idle = time.monotonic() - last
                if idle >= heartbeat:
                    yield Event("ping", {"ok": True}).to_sse()
                    last = time.monotonic()
                    continue
                timeout = min(1.0, max(0.05, heartbeat - idle))
                try:
                    item = q.get(timeout=timeout)
                except queue.Empty:
                    continue
                if item is None:
                    break
                yield item.to_sse()
                last = time.monotonic()
        finally:
            self.unsubscribe(channel, q)


def peer_closed(sock: socket.socket | None) -> bool:
    """True when the peer has half-closed or dropped the connection.

    Empty MSG_PEEK means FIN. Non-empty data is left in the buffer.
    """
    if sock is None:
        return False
    try:
        readable, _, _ = select.select([sock], [], [], 0)
    except (OSError, ValueError):
        return True
    if not readable:
        return False
    try:
        data = sock.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
    except BlockingIOError:
        return False
    except OSError:
        return True
    return data == b""


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def sse_response(channel: str, *, heartbeat: float = 15.0):
    """text/event-stream response that ends when the client goes away.

    Do not set Connection: keep-alive here. Werkzeug always adds
    Connection: close; two Connection headers make browsers drop the stream.
    """
    from flask import Response, request, stream_with_context

    @stream_with_context
    def generate():
        def stop() -> bool:
            return peer_closed(request.environ.get("werkzeug.socket"))

        yield from BUS.stream(channel, heartbeat=heartbeat, stop_check=stop)

    return Response(generate(), mimetype="text/event-stream", headers=dict(_SSE_HEADERS))


BUS = EventBus()
