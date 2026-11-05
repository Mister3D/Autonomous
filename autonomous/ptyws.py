"""Interactive container PTY over WebSocket (for xterm.js)."""

from __future__ import annotations

import json
import logging
import select
import struct
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("autonomous.ptyws")


def _recvexact(sock, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except OSError:
            return None
        if not chunk:
            return None
        buf += chunk
    return buf


def ws_send(sock, payload: bytes, opcode: int = 0x2) -> None:
    ln = len(payload)
    header = bytearray([0x80 | (opcode & 0x0F)])
    if ln < 126:
        header.append(ln)
    elif ln < 65536:
        header.append(126)
        header.extend(struct.pack("!H", ln))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", ln))
    sock.sendall(bytes(header) + payload)


def ws_recv(sock) -> tuple[int, bytes] | None:
    """Read one WebSocket data frame. Handles ping; returns None on close/error."""
    while True:
        hdr = _recvexact(sock, 2)
        if not hdr:
            return None
        b1, b2 = hdr[0], hdr[1]
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        ln = b2 & 0x7F
        if ln == 126:
            ext = _recvexact(sock, 2)
            if not ext:
                return None
            ln = struct.unpack("!H", ext)[0]
        elif ln == 127:
            ext = _recvexact(sock, 8)
            if not ext:
                return None
            ln = struct.unpack("!Q", ext)[0]
        mask = _recvexact(sock, 4) if masked else b"\x00\x00\x00\x00"
        if mask is None:
            return None
        data = _recvexact(sock, ln) if ln else b""
        if data is None:
            return None
        if masked:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if opcode == 0x8:  # close
            return None
        if opcode == 0x9:  # ping → pong
            try:
                ws_send(sock, data, 0xA)
            except OSError:
                return None
            continue
        if opcode in (0x1, 0x2, 0x0):
            return opcode, data
        # ignore other control opcodes
        continue


def _bot_ready(bot: str, home: Path | None) -> tuple[bool, str]:
    from autonomous.services import bots as bots_svc
    from autonomous.services import desk as desk_svc
    from autonomous.services.errors import AutonomousError

    try:
        b = bots_svc.get_bot(bot, home=home)
    except AutonomousError as exc:
        return False, str(exc)
    if b.get("capability") == "none":
        return False, "no_capability"
    desk = b.get("desk") or {}
    if desk.get("state") == "sleeping":
        try:
            desk_svc.wake_desk(bot, home=home)
        except AutonomousError as exc:
            return False, str(exc)
    elif desk.get("state") == "running":
        desk_svc.touch_activity(bot, home=home)
    else:
        return False, "desk_not_running"
    return True, desk_svc.container_name(bot, home=home)


def attach_container_pty(
    client: Any,
    bot: str,
    *,
    home: Path | None = None,
    leftover: bytes = b"",
) -> None:
    """
    After HTTP 101 on ``client``, attach an interactive bash in the bot container.
    Binary frames ↔ PTY bytes. Text frames: JSON ``{"type":"resize","cols":N,"rows":M}``.
    """
    ok, info = _bot_ready(bot, home)
    if not ok:
        try:
            ws_send(client, f"\r\n[autonomous] {info}\r\n".encode(), opcode=0x1)
        except OSError:
            pass
        try:
            client.close()
        except OSError:
            pass
        return

    container_name = info
    docker_sock = None
    exec_id = None
    try:
        import docker

        dclient = docker.from_env()
        container = dclient.containers.get(container_name)
        api = dclient.api
        exec_id = api.exec_create(
            container.id,
            ["/bin/bash", "-l"],
            tty=True,
            stdin=True,
            user="autonomous",
            workdir="/home/autonomous/workspace",
            environment={
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
            },
        )["Id"]
        sock_io = api.exec_start(exec_id, tty=True, socket=True, demux=False)
        docker_sock = sock_io._sock
        docker_sock.setblocking(False)
        try:
            api.exec_resize(exec_id, height=24, width=80)
        except Exception:
            pass
    except Exception as exc:
        log.warning("pty open failed for %s: %s", bot, exc)
        try:
            ws_send(client, f"\r\n[autonomous] pty error: {exc}\r\n".encode(), opcode=0x1)
        except OSError:
            pass
        try:
            client.close()
        except OSError:
            pass
        return

    stop = threading.Event()

    def _close_all() -> None:
        stop.set()
        for s in (client, docker_sock):
            if s is None:
                continue
            try:
                s.shutdown(2)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass

    def _handle_client_payload(opcode: int, data: bytes) -> None:
        if opcode == 0x1:
            # Control JSON (resize) — otherwise treat as typed text
            try:
                msg = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                msg = None
            if isinstance(msg, dict) and msg.get("type") == "resize":
                cols = max(20, min(int(msg.get("cols") or 80), 500))
                rows = max(5, min(int(msg.get("rows") or 24), 200))
                try:
                    import docker

                    docker.from_env().api.exec_resize(exec_id, height=rows, width=cols)
                except Exception as exc:
                    log.debug("resize failed: %s", exc)
                return
            if data:
                docker_sock.sendall(data)
            return
        if data:
            docker_sock.sendall(data)

    def client_to_pty() -> None:
        try:
            # Rare: client data arrived with the HTTP upgrade request
            if leftover:
                pass  # full WS frames in leftover are uncommon; ignore partial noise
            while not stop.is_set():
                readable, _, _ = select.select([client], [], [], 0.5)
                if not readable:
                    continue
                frame = ws_recv(client)
                if frame is None:
                    break
                opcode, data = frame
                try:
                    _handle_client_payload(opcode, data)
                except OSError:
                    break
        finally:
            _close_all()

    def pty_to_client() -> None:
        try:
            while not stop.is_set():
                readable, _, _ = select.select([docker_sock], [], [], 0.5)
                if not readable:
                    # Detect exited exec
                    try:
                        import docker

                        st = docker.from_env().api.exec_inspect(exec_id)
                        if st and not st.get("Running", True):
                            break
                    except Exception:
                        pass
                    continue
                try:
                    chunk = docker_sock.recv(65536)
                except BlockingIOError:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                try:
                    ws_send(client, chunk, opcode=0x2)
                except OSError:
                    break
        finally:
            _close_all()

    t1 = threading.Thread(target=client_to_pty, daemon=True, name=f"pty-in-{bot}")
    t2 = threading.Thread(target=pty_to_client, daemon=True, name=f"pty-out-{bot}")
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    log.info("pty session closed bot=%s", bot)
