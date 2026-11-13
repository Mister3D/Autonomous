"""Live companion tunnel: SOCKS, DNS, and MCP calls multiplexed on one socket."""

from __future__ import annotations

import json
import queue
import socket
import struct
import threading
from pathlib import Path
from typing import Any, Callable

from autonomous.services.companion_proto import (
    OP_CLOSE,
    OP_DATA,
    OP_DNS,
    OP_DNS_ERR,
    OP_DNS_OK,
    OP_MCP_CALL,
    OP_MCP_RESULT,
    OP_OPEN,
    OP_OPEN_ERR,
    OP_OPEN_OK,
    OP_PING,
    OP_PONG,
    OP_NOTIFY,
    decode_frame,
    encode_frame,
)

SendFrame = Callable[[int, int, bytes], None]
_HUBS: dict[str, "CompanionHub"] = {}
_HUBS_LOCK = threading.Lock()
_PEER_LOCK = threading.Lock()
# (home_key, device_id) → (monotonic_ts, ips)
_PEER_CACHE: dict[tuple[str, str], tuple[float, set[str]]] = {}
_PEER_TTL = 5.0
_MAX_MCP_IMAGES = 4


def _mcp_images(raw: Any) -> list[dict[str, str]]:
    """Image parts forwarded by the companion. Bytes stay base64 until saved."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        mime = str(item.get("mime") or item.get("mimeType") or "").split(";", 1)[0].strip().lower()
        data = "".join(str(item.get("data") or "").split())
        if not mime.startswith("image/") or not data:
            continue
        out.append({"mime": mime, "data": data})
        if len(out) >= _MAX_MCP_IMAGES:
            break
    return out


def _store_mcp_images(
    bot: str, images: list[dict[str, str]], *, home: Path | None
) -> list[dict[str, str]]:
    """Save each image into the bot's files and return markdown the chat can show."""
    from autonomous.services import files as files_svc
    from autonomous.services.errors import AutonomousError

    stored: list[dict[str, str]] = []
    for image in images:
        try:
            saved = files_svc.save_mcp_image(
                bot, image["mime"], image["data"], home=home
            )
        except AutonomousError:
            continue
        stored.append(
            {
                "mime": str(saved.get("mime") or image["mime"]),
                "data": image["data"],
                "markdown": str(saved.get("markdown") or ""),
                "url": str(saved.get("url") or ""),
            }
        )
    return stored


def _authorized_peer_ips(
    device_id: str,
    *,
    home: Path | None = None,
    force: bool = False,
) -> set[str]:
    """Desk IPs of bots that may use this companion's SOCKS/DNS.

    Only bots with ``companion_id == device_id`` and ``companion_egress`` on.
    Other desks on the host are rejected even if they are Autonomous VMs.
    """
    import time

    key = (str(home or ""), str(device_id or ""))
    now = time.monotonic()
    with _PEER_LOCK:
        hit = _PEER_CACHE.get(key)
        if not force and hit is not None and now - hit[0] < _PEER_TTL:
            return set(hit[1])
    ips: set[str] = set()
    try:
        from autonomous.services import bots as bots_svc
        from autonomous.services.companion_egress import bot_endpoints

        names = {
            str(row.get("name") or "")
            for row in bots_svc.companion_routes(home=home)
            if str(row.get("companion_id") or "") == str(device_id or "")
            and row.get("egress")
        }
        names.discard("")
        if names:
            ips_map, _subnets = bot_endpoints()
            ips = {ips_map[name] for name in names if name in ips_map}
    except Exception:
        ips = set()
    with _PEER_LOCK:
        _PEER_CACHE[key] = (time.monotonic(), set(ips))
        return set(ips)


def peer_allowed(
    ip: str,
    *,
    device_id: str | None = None,
    home: Path | None = None,
) -> bool:
    """Loopback or a desk IP authorized for this companion may use SOCKS/DNS.

    Listeners stay on 0.0.0.0 so iptables REDIRECT (docker bridge) still works;
    LAN clients and desks routed to another companion are rejected here.
    """
    if not ip:
        return False
    if ip == "::1" or ip.startswith("127."):
        return True
    if not device_id:
        return False
    if ip in _authorized_peer_ips(device_id, home=home):
        return True
    return ip in _authorized_peer_ips(device_id, home=home, force=True)


def hub_for(home: Path | None) -> "CompanionHub":
    key = str(home or "")
    with _HUBS_LOCK:
        hub = _HUBS.get(key)
        if hub is None:
            hub = CompanionHub(home)
            _HUBS[key] = hub
        return hub


def online_device_ids(home: Path | None) -> list[str]:
    return hub_for(home).online_ids()


def drop_device(device_id: str, *, home: Path | None) -> None:
    hub_for(home).drop(device_id)


class Stream:
    def __init__(self) -> None:
        self.ready = threading.Event()
        self.ok = False
        self.err = ""
        self.inbox: queue.Queue[bytes | None] = queue.Queue()


class CompanionSession:
    """One connected companion. `send_frame` writes a protocol frame to the socket."""

    def __init__(
        self,
        device_id: str,
        send_frame: SendFrame,
        *,
        home: Path | None = None,
    ) -> None:
        self.device_id = device_id
        self.home = home
        self.send_frame = send_frame
        self.streams: dict[int, Stream] = {}
        self.lock = threading.Lock()
        self._next = 1
        self.closed = False
        self.socks_port = 0
        self.dns_port = 0
        self._socks: socket.socket | None = None
        self._dns: socket.socket | None = None

    def start_listeners(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", 0))
        sock.listen(64)
        self.socks_port = sock.getsockname()[1]
        self._socks = sock
        threading.Thread(target=self._accept_socks, args=(sock,), daemon=True).start()

        dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        dns.bind(("0.0.0.0", 0))
        self.dns_port = dns.getsockname()[1]
        self._dns = dns
        threading.Thread(target=self._dns_loop, args=(dns,), daemon=True).start()

    def close(self) -> None:
        self.closed = True
        with self.lock:
            streams = list(self.streams.values())
            self.streams.clear()
        for stream in streams:
            stream.ok = False
            stream.ready.set()
            stream.inbox.put(None)
        for sock in (self._socks, self._dns):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def handle_frame(self, op: int, stream_id: int, payload: bytes) -> None:
        if op == OP_PING:
            self.send_frame(OP_PONG, stream_id, payload)
            return
        if op in (OP_OPEN_OK, OP_OPEN_ERR, OP_DATA, OP_CLOSE, OP_DNS_OK, OP_DNS_ERR, OP_MCP_RESULT):
            with self.lock:
                stream = self.streams.get(stream_id)
            if stream is None:
                return
            if op == OP_OPEN_OK:
                stream.ok = True
                stream.ready.set()
            elif op == OP_OPEN_ERR:
                stream.err = payload.decode("utf-8", errors="replace")[:500]
                stream.ready.set()
            elif op == OP_DNS_OK:
                stream.ok = True
                stream.inbox.put(payload)
                stream.ready.set()
            elif op == OP_DNS_ERR:
                stream.err = payload.decode("utf-8", errors="replace")[:500]
                stream.ready.set()
            elif op == OP_MCP_RESULT:
                stream.inbox.put(payload)
                stream.ready.set()
            elif op == OP_DATA:
                stream.inbox.put(payload)
            elif op == OP_CLOSE:
                stream.inbox.put(None)

    def call_mcp(self, server: str, tool: str, arguments: Any, timeout: float = 90.0) -> dict[str, Any]:
        payload = json.dumps(
            {"server": server, "tool": tool, "arguments": arguments or {}},
            ensure_ascii=False,
        ).encode("utf-8")
        stream_id, stream = self._alloc()
        self.send_frame(OP_MCP_CALL, stream_id, payload)
        if not stream.ready.wait(timeout):
            self._release(stream_id)
            raise TimeoutError("Companion did not answer the MCP call.")
        try:
            raw = stream.inbox.get(timeout=2)
        except queue.Empty:
            raw = b""
        self._release(stream_id)
        if raw is None:
            raw = b""
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {"text": raw.decode("utf-8", errors="replace")[:8000], "images": []}
        if not isinstance(body, dict):
            return {"text": str(body)[:8000], "images": []}
        if not body.get("ok", True):
            raise RuntimeError(str(body.get("error") or "MCP call failed"))
        return {
            "text": str(body.get("text") or "")[:16000],
            "images": _mcp_images(body.get("images")),
        }

    def _alloc(self) -> tuple[int, Stream]:
        stream = Stream()
        with self.lock:
            if self.closed:
                raise RuntimeError("Companion is offline.")
            stream_id = self._next
            self._next = (self._next + 1) & 0xFFFFFFFF or 1
            self.streams[stream_id] = stream
        return stream_id, stream

    def _release(self, stream_id: int) -> None:
        with self.lock:
            self.streams.pop(stream_id, None)

    def _accept_socks(self, sock: socket.socket) -> None:
        while not self.closed:
            try:
                conn, addr = sock.accept()
            except OSError:
                return
            peer = addr[0] if addr else ""
            if not peer_allowed(peer, device_id=self.device_id, home=self.home):
                try:
                    conn.close()
                except OSError:
                    pass
                continue
            threading.Thread(target=self._socks_client, args=(conn,), daemon=True).start()

    def _socks_client(self, conn: socket.socket) -> None:
        stream_id = 0
        try:
            target = _socks_accept(conn)
            if target is None:
                return
            host, port = target
            stream_id, stream = self._alloc()
            self.send_frame(OP_OPEN, stream_id, f"{host}\n{port}".encode("utf-8"))
            if not stream.ready.wait(20):
                _socks_reply(conn, granted=False)
                return
            if not stream.ok:
                _socks_reply(conn, granted=False)
                return
            _socks_reply(conn, granted=True)
            _relay(conn, stream, stream_id, self)
        except Exception:
            try:
                conn.close()
            except OSError:
                pass
        finally:
            if stream_id:
                try:
                    self.send_frame(OP_CLOSE, stream_id, b"")
                except Exception:
                    pass
                self._release(stream_id)

    def _dns_loop(self, sock: socket.socket) -> None:
        while not self.closed:
            try:
                data, addr = sock.recvfrom(4096)
            except OSError:
                return
            if not data:
                continue
            peer = addr[0] if addr else ""
            if not peer_allowed(peer, device_id=self.device_id, home=self.home):
                continue
            threading.Thread(
                target=self._dns_one, args=(sock, data, addr), daemon=True
            ).start()

    def _dns_one(self, sock: socket.socket, query: bytes, addr) -> None:
        stream_id = 0
        try:
            stream_id, stream = self._alloc()
            self.send_frame(OP_DNS, stream_id, query)
            if not stream.ready.wait(5) or not stream.ok:
                return
            reply = stream.inbox.get_nowait() if not stream.inbox.empty() else b""
            if reply:
                sock.sendto(reply, addr)
        except Exception:
            return
        finally:
            if stream_id:
                self._release(stream_id)


def _recvexact(conn: socket.socket, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        try:
            chunk = conn.recv(n - len(buf))
        except OSError:
            return None
        if not chunk:
            return None
        buf += chunk
    return buf


def _socks_accept(conn: socket.socket) -> tuple[str, int] | None:
    hdr = _recvexact(conn, 2)
    if not hdr or hdr[0] != 5:
        return None
    methods = _recvexact(conn, hdr[1])
    if methods is None:
        return None
    conn.sendall(b"\x05\x00")
    req = _recvexact(conn, 4)
    if not req or req[1] != 1:
        _socks_reply(conn, granted=False)
        return None
    atyp = req[3]
    if atyp == 1:
        raw = _recvexact(conn, 4)
        if raw is None:
            return None
        host = socket.inet_ntoa(raw)
    elif atyp == 3:
        ln_b = _recvexact(conn, 1)
        if not ln_b:
            return None
        raw = _recvexact(conn, ln_b[0])
        if raw is None:
            return None
        host = raw.decode("utf-8", errors="replace")
    elif atyp == 4:
        raw = _recvexact(conn, 16)
        if raw is None:
            return None
        host = socket.inet_ntop(socket.AF_INET6, raw)
    else:
        return None
    port_b = _recvexact(conn, 2)
    if not port_b:
        return None
    port = struct.unpack("!H", port_b)[0]
    return host, port


def _socks_reply(conn: socket.socket, *, granted: bool) -> None:
    status = b"\x00" if granted else b"\x05"
    try:
        conn.sendall(b"\x05" + status + b"\x00\x01\x00\x00\x00\x00\x00\x00")
    except OSError:
        pass


def _relay(conn: socket.socket, stream: Stream, stream_id: int, session: CompanionSession) -> None:
    def uplink() -> None:
        try:
            while True:
                data = conn.recv(32768)
                if not data:
                    break
                session.send_frame(OP_DATA, stream_id, data)
        except OSError:
            pass
        finally:
            try:
                session.send_frame(OP_CLOSE, stream_id, b"")
            except Exception:
                pass

    threading.Thread(target=uplink, daemon=True).start()
    while True:
        chunk = stream.inbox.get()
        if chunk is None:
            break
        try:
            conn.sendall(chunk)
        except OSError:
            break
    try:
        conn.close()
    except OSError:
        pass


class CompanionHub:
    def __init__(self, home: Path | None) -> None:
        self.home = home
        self._sessions: dict[str, CompanionSession] = {}
        self._lock = threading.Lock()

    def attach(self, device_id: str, session: CompanionSession) -> None:
        with self._lock:
            previous = self._sessions.get(device_id)
            self._sessions[device_id] = session
        if previous is not None and previous is not session:
            previous.close()
        from autonomous.services import companion_egress as egress_svc
        from autonomous.services import devices as devices_svc

        devices_svc.touch(device_id, home=self.home)
        egress_svc.refresh(self.home)

    def detach(self, device_id: str, session: CompanionSession) -> None:
        with self._lock:
            if self._sessions.get(device_id) is session:
                self._sessions.pop(device_id, None)
        session.close()
        from autonomous.services import companion_egress as egress_svc

        egress_svc.refresh(self.home)

    def drop(self, device_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(device_id, None)
        if session is not None:
            session.close()
        from autonomous.services import companion_egress as egress_svc

        egress_svc.refresh(self.home)

    def online_ids(self) -> list[str]:
        with self._lock:
            return list(self._sessions)

    def session_for(self, device_id: str) -> CompanionSession | None:
        with self._lock:
            return self._sessions.get(device_id)

    def call_mcp(
        self,
        server: str,
        tool: str,
        arguments: Any,
        *,
        bot: str,
        companion: str = "",
        home: Path | None,
    ) -> dict[str, Any]:
        from autonomous.services import devices as devices_svc

        catalog = devices_svc.mcp_catalog(bot=bot, home=home)
        matches = [
            row
            for row in catalog
            if row["server"] == server and row["name"] == tool
        ]
        if companion:
            wanted = companion.strip().casefold()
            matches = [
                row for row in matches if str(row.get("device_name") or "").casefold() == wanted
            ]
        online = [row for row in matches if row["online"]]
        if not online:
            if matches:
                raise RuntimeError("The companion that owns this MCP tool is offline.")
            raise RuntimeError(
                "This bot is not allowed to use this MCP tool, "
                "or the server/tool name does not match mcp_list."
            )
        device_ids = {row["device_id"] for row in online}
        if len(device_ids) > 1:
            names = sorted({str(row.get("device_name") or "") for row in online})
            raise RuntimeError(
                "Several companions expose this MCP tool ("
                + ", ".join(names)
                + "). Pass the companion name."
            )
        device_id = online[0]["device_id"]
        session = self.session_for(device_id)
        if session is None:
            raise RuntimeError("The companion that owns this MCP tool is offline.")
        result = session.call_mcp(server, tool, arguments)
        return {
            "text": result.get("text") or "",
            "images": _store_mcp_images(bot, result.get("images") or [], home=home),
        }

    def notify_all(self, payload: bytes, *, device_ids: set[str] | None = None) -> int:
        with self._lock:
            sessions = [
                session
                for device_id, session in self._sessions.items()
                if not session.closed and (device_ids is None or device_id in device_ids)
            ]
        for session in sessions:
            session.send_frame(OP_NOTIFY, 0, payload)
        return len(sessions)

    def connected_egress(self) -> CompanionSession | None:
        from autonomous.services import devices as devices_svc

        for row in devices_svc.egress_devices(home=self.home):
            session = self.session_for(row["id"])
            if session is not None and not session.closed:
                return session
        return None
