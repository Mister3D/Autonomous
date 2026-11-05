#!/usr/bin/env python3
"""Type / paste / click into the desk via local TigerVNC RFB (no XTest / xdotool).

Text modes read UTF-8 from stdin (never argv). Click takes --x/--y on argv.
Intended to run *inside* the desktop container against 127.0.0.1:5901
(SecurityTypes=None, localhost only).

Usage:
  printf '%s' "$text" | python3 vnc_type_worker.py type
  printf '%s' "$text" | python3 vnc_type_worker.py paste
  python3 vnc_type_worker.py click --x 100 --y 200 [--button left|right|middle|double]
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import math
import random
import socket
import struct
import sys
import time

# X11 keysyms
_XK_Control_L = 0xFFE3
_XK_Shift_L = 0xFFE1
_XK_V = 0x0076

# RFB button mask bits
_BTN_LEFT = 1
_BTN_MIDDLE = 2
_BTN_RIGHT = 4
_BTN_WHEEL_UP = 8
_BTN_WHEEL_DOWN = 16

_KEYSYMS = {
    "Return": 0xFF0D,
    "Enter": 0xFF0D,
    "Tab": 0xFF09,
    "Escape": 0xFF1B,
    "BackSpace": 0xFF08,
    "Delete": 0xFFFF,
    "Left": 0xFF51,
    "Up": 0xFF52,
    "Right": 0xFF53,
    "Down": 0xFF54,
    "Page_Up": 0xFF55,
    "Page_Down": 0xFF56,
    "Home": 0xFF50,
    "End": 0xFF57,
    "space": 0x0020,
}


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError("VNC connection closed")
        buf.extend(chunk)
    return bytes(buf)


def _handshake(sock: socket.socket) -> None:
    server_ver = _recv_exact(sock, 12)
    if not server_ver.startswith(b"RFB "):
        raise RuntimeError(f"Not an RFB server: {server_ver!r}")
    sock.sendall(b"RFB 003.008\n")
    n = _recv_exact(sock, 1)[0]
    types = _recv_exact(sock, n) if n else b""
    if 1 not in types:  # None
        raise RuntimeError(f"VNC SecurityTypes None unavailable: {list(types)}")
    sock.sendall(bytes([1]))
    result = struct.unpack(">I", _recv_exact(sock, 4))[0]
    if result != 0:
        raise RuntimeError(f"VNC security handshake failed: {result}")
    # ClientInit: shared = 1
    sock.sendall(bytes([1]))
    # ServerInit: width(2) + height(2) + PIXEL_FORMAT(16) + name-length(4) + name
    _recv_exact(sock, 20)
    name_len = struct.unpack(">I", _recv_exact(sock, 4))[0]
    if name_len < 0 or name_len > 1_000_000:
        raise RuntimeError(f"Invalid VNC desktop name length: {name_len}")
    if name_len:
        _recv_exact(sock, name_len)


def _key_event(sock: socket.socket, keysym: int, down: bool) -> None:
    sock.sendall(struct.pack(">BBHI", 4, 1 if down else 0, 0, keysym & 0xFFFFFFFF))


def _tap(sock: socket.socket, keysym: int, hold: float = 0.0) -> None:
    _key_event(sock, keysym, True)
    if hold > 0:
        time.sleep(hold)
    _key_event(sock, keysym, False)


def _type_char(sock: socket.socket, ch: str, hold: float = 0.0) -> None:
    """Type one Unicode character via Latin-1 keysym when possible, else UCS."""
    cp = ord(ch)
    if ch == "\n":
        _tap(sock, 0xFF0D, hold)  # Return
        return
    if ch == "\t":
        _tap(sock, 0xFF09, hold)
        return
    if cp < 0x100:
        # Latin-1: keysym == codepoint (includes ASCII).
        # Uppercase / symbols needing Shift are still sent as the character
        # keysym; TigerVNC maps them correctly for typing.
        _tap(sock, cp, hold)
        return
    # Unicode via DirectAccess keysym (XK_void + 0x01000000 | codepoint)
    _tap(sock, 0x01000000 | cp, hold)


def _human_type(sock: socket.socket, text: str) -> None:
    """Keystroke dynamics of a person (≈ 50–150 ms between keys, key hold, hesitations).

    ~125 chars/s with zero hold time is the textbook « too-regular speed » tell.
    Very long texts are accelerated so the host exec budget (30 s) is respected.
    """
    scale = 1.0 if len(text) <= 150 else max(0.15, 150.0 / len(text))
    for ch in text:
        _type_char(sock, ch, hold=random.uniform(0.025, 0.075) * scale)
        gap = random.uniform(0.04, 0.13)
        if random.random() < 0.07:
            gap += random.uniform(0.15, 0.40)  # brief hesitation
        time.sleep(gap * scale)


def _client_cut_text(sock: socket.socket, text: str) -> None:
    data = text.encode("utf-8")
    # message-type 6, 3 bytes padding, length, text
    sock.sendall(struct.pack(">B3sI", 6, b"\x00\x00\x00", len(data)) + data)


def _paste_keys(sock: socket.socket) -> None:
    # Ctrl+Shift+V — xfce4-terminal / most GTK terminals
    _key_event(sock, _XK_Control_L, True)
    _key_event(sock, _XK_Shift_L, True)
    _tap(sock, _XK_V)
    _key_event(sock, _XK_Shift_L, False)
    _key_event(sock, _XK_Control_L, False)


_STATE_PATH = "/tmp/.autonomous-pointer.json"


def _last_pointer(tx: int, ty: int) -> tuple[float, float]:
    """Where the (virtual) pointer was last left — persisted across worker runs."""
    try:
        with open(_STATE_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
        return float(d["x"]), float(d["y"])
    except Exception:
        # Unknown start: come from a plausible nearby spot, not from (0,0).
        return (
            max(0.0, tx + random.choice((-1, 1)) * random.uniform(180, 520)),
            max(0.0, ty + random.choice((-1, 1)) * random.uniform(90, 300)),
        )


def _save_pointer(x: float, y: float) -> None:
    try:
        with open(_STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump({"x": int(x), "y": int(y)}, fh)
    except Exception:
        pass


def _move_to(sock: socket.socket, x: int, y: int, buttons: int = 0) -> None:
    """Glide the pointer to (x, y) like a hand: curved path, ease-in-out, jitter.

    A single teleporting `mousemove` right before `mousedown` is a classic bot signal.
    """
    lx, ly = _last_pointer(x, y)
    dist = math.hypot(x - lx, y - ly)
    if dist < 3:
        _pointer(sock, x, y, buttons)
        _save_pointer(x, y)
        return
    duration = max(0.18, min(0.95, 0.20 + dist / 2000.0)) * random.uniform(0.85, 1.3)
    steps = max(10, min(90, int(duration / 0.014)))
    nx, ny = -(y - ly) / dist, (x - lx) / dist
    bend = max(-70.0, min(70.0, random.uniform(-0.14, 0.14) * dist))
    cx, cy = (lx + x) / 2 + nx * bend, (ly + y) / 2 + ny * bend
    for i in range(1, steps + 1):
        t = i / steps
        e = t * t * (3.0 - 2.0 * t)
        bx = (1 - e) ** 2 * lx + 2 * (1 - e) * e * cx + e ** 2 * x
        by = (1 - e) ** 2 * ly + 2 * (1 - e) * e * cy + e ** 2 * y
        if i < steps:
            bx += random.uniform(-0.8, 0.8) * (1 - t)
            by += random.uniform(-0.8, 0.8) * (1 - t)
        _pointer(sock, int(round(bx)), int(round(by)), buttons)
        time.sleep((duration / steps) * random.uniform(0.8, 1.2))
    _pointer(sock, x, y, buttons)
    _save_pointer(x, y)


def _pointer(sock: socket.socket, x: int, y: int, buttons: int = 0) -> None:
    sock.sendall(
        struct.pack(
            ">BBHH",
            5,
            buttons & 0xFF,
            max(0, min(0xFFFF, int(x))),
            max(0, min(0xFFFF, int(y))),
        )
    )


def _click(
    sock: socket.socket, x: int, y: int, *, button: str = "left"
) -> None:
    mask = {
        "left": _BTN_LEFT,
        "middle": _BTN_MIDDLE,
        "right": _BTN_RIGHT,
    }.get(button, _BTN_LEFT)
    _move_to(sock, x, y)
    if button == "move":  # hover only (menus / tooltips that open on mouse-over)
        time.sleep(random.uniform(0.5, 0.8))
        return
    time.sleep(random.uniform(0.07, 0.22))  # aim / hover before pressing
    if button == "double":
        for i in range(2):
            _pointer(sock, x, y, _BTN_LEFT)
            time.sleep(random.uniform(0.04, 0.09))
            _pointer(sock, x, y, 0)
            if i == 0:
                time.sleep(random.uniform(0.07, 0.14))
        return
    _pointer(sock, x, y, mask)
    time.sleep(random.uniform(0.05, 0.13))  # button held down
    _pointer(sock, x, y, 0)


def _drag(
    sock: socket.socket,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    steps: int | None = None,
) -> None:
    """Left-button drag with timing and jitter (matters for slide captchas).

    A ~0.3s linear/ease-out path is a classic bot signal. Real slides take
    roughly 0.8–1.8s with ease-in-out, micro y-jitter, and a short settle.
    """
    dist = max(1.0, math.hypot(x2 - x1, y2 - y1))
    # ~1.1s base for a ~300px slide; clamp to a plausible pointer range.
    duration = max(0.85, min(1.85, 0.55 + dist / 420.0))
    duration *= random.uniform(0.92, 1.12)
    if steps is None:
        steps = int(round(duration / 0.016))  # ~60 Hz samples
    steps = max(28, min(int(steps), 120))

    # Approach: hover near the handle before grabbing.
    ax = x1 + random.randint(-3, 3)
    ay = y1 + random.randint(-2, 2)
    _move_to(sock, ax, ay)
    time.sleep(random.uniform(0.08, 0.18))
    _pointer(sock, x1, y1, 0)
    time.sleep(random.uniform(0.05, 0.12))
    _pointer(sock, x1, y1, _BTN_LEFT)
    time.sleep(random.uniform(0.07, 0.16))

    # Slight overshoot then settle. Keep tiny on short captcha tracks
    # so we don't fly past the target well and fail the challenge.
    if dist >= 200:
        overshoot = random.uniform(0.02, 0.05)
    elif dist >= 80:
        overshoot = random.uniform(0.01, 0.025)
    else:
        overshoot = 0.0
    ox = int(round(x1 + (x2 - x1) * (1.0 + overshoot)))
    oy = int(round(y1 + (y2 - y1) * (1.0 + overshoot)))

    for i in range(1, steps + 1):
        t = i / steps
        # smoothstep ease-in-out
        e = t * t * (3.0 - 2.0 * t)
        x = int(round(x1 + (ox - x1) * e))
        y = int(round(y1 + (oy - y1) * e))
        # Perpendicular micro-jitter (decays toward the end).
        # Keep vertical jitter tiny on horizontal slides so we stay on-track.
        if i < steps:
            horiz = abs(x2 - x1) >= abs(y2 - y1)
            jitter = (1.0 - t) * random.uniform(
                0.2, 0.7 if horiz else 1.4
            )
            nx, ny = -(y2 - y1) / dist, (x2 - x1) / dist
            x += int(round(nx * jitter * random.choice((-1, 1))))
            y += int(round(ny * jitter * random.choice((-1, 1))))
        _pointer(sock, x, y, _BTN_LEFT)
        # Variable pace: slower near start/end.
        pace = 0.55 + 0.9 * math.sin(math.pi * t)
        time.sleep((duration / steps) * pace * random.uniform(0.85, 1.15))

    # Settle onto exact end, brief hold, release.
    _pointer(sock, x2, y2, _BTN_LEFT)
    time.sleep(random.uniform(0.06, 0.14))
    _pointer(sock, x2, y2, 0)
    _save_pointer(x2, y2)
    time.sleep(random.uniform(0.04, 0.10))


def _wheel(sock: socket.socket, x: int, y: int, *, down: bool, clicks: int) -> None:
    mask = _BTN_WHEEL_DOWN if down else _BTN_WHEEL_UP
    _move_to(sock, x, y)
    time.sleep(random.uniform(0.05, 0.15))
    for _ in range(max(1, clicks)):
        _pointer(sock, x, y, mask)
        time.sleep(random.uniform(0.02, 0.05))
        _pointer(sock, x, y, 0)
        time.sleep(random.uniform(0.05, 0.14))


@contextlib.contextmanager
def _pointer_lock():
    """Serialize pointer-moving workers (click/drag/scroll/wander) in the desk."""
    fh = open("/tmp/.autonomous-pointer.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()


def _wander(sock: socket.socket) -> int:
    """Idle, hand-like cursor drift (no buttons): people never leave the mouse frozen."""
    hops = random.randint(2, 4)
    for _ in range(hops):
        tx = random.randint(260, 1660)
        ty = random.randint(220, 980)
        _move_to(sock, tx, ty)
        time.sleep(random.uniform(0.25, 0.9))
    return hops


def run(
    mode: str,
    text: str = "",
    *,
    host: str = "127.0.0.1",
    port: int = 5901,
    x: int = 0,
    y: int = 0,
    button: str = "left",
    dy: int = 0,
    key: str = "",
    repeats: int = 1,
    x2: int = 0,
    y2: int = 0,
) -> int:
    if mode not in ("type", "paste", "click", "scroll", "key", "drag", "wander"):
        raise RuntimeError(
            f"mode must be type|paste|click|scroll|key|drag|wander, got {mode!r}"
        )
    if mode in ("click", "drag", "scroll", "wander"):
        with _pointer_lock():
            return _run_inner(mode, text, host=host, port=port, x=x, y=y, button=button,
                              dy=dy, key=key, repeats=repeats, x2=x2, y2=y2)
    return _run_inner(mode, text, host=host, port=port, x=x, y=y, button=button,
                      dy=dy, key=key, repeats=repeats, x2=x2, y2=y2)


def _run_inner(
    mode: str,
    text: str = "",
    *,
    host: str = "127.0.0.1",
    port: int = 5901,
    x: int = 0,
    y: int = 0,
    button: str = "left",
    dy: int = 0,
    key: str = "",
    repeats: int = 1,
    x2: int = 0,
    y2: int = 0,
) -> int:
    sock = socket.create_connection((host, port), timeout=5)
    try:
        sock.settimeout(10)
        _handshake(sock)
        if mode == "wander":
            return _wander(sock)
        if mode == "click":
            _click(sock, x, y, button=button)
            time.sleep(0.05)
            return 1
        if mode == "drag":
            _drag(sock, int(x), int(y), int(x2), int(y2))
            time.sleep(0.05)
            return 1
        if mode == "scroll":
            # Negative dy = scroll content up (wheel down) — same as human reading down.
            clicks = max(1, min(abs(int(dy)) // 80 or 3, 20))
            down = int(dy) >= 0
            cx = x if x > 0 else 640
            cy = y if y > 0 else 360
            _wheel(sock, cx, cy, down=down, clicks=clicks)
            time.sleep(0.05)
            return clicks
        if mode == "key":
            name = (key or "").strip()
            keysym = _KEYSYMS.get(name)
            if keysym is None and len(name) == 1:
                keysym = ord(name)
            if keysym is None:
                raise RuntimeError(f"unknown key {name!r}")
            for _ in range(max(1, int(repeats))):
                _tap(sock, keysym)
                time.sleep(0.04)
            return max(1, int(repeats))
        if mode == "paste":
            _client_cut_text(sock, text)
            time.sleep(0.05)
            _paste_keys(sock)
        else:
            _human_type(sock, text)
        time.sleep(0.05)
    finally:
        sock.close()
    return len(text)


def main(argv: list[str]) -> int:
    mode = (argv[1] if len(argv) > 1 else "type").strip().lower()
    host = "127.0.0.1"
    port = 5901
    x = y = 0
    button = "left"
    dy = 400
    key = ""
    repeats = 1
    x2 = y2 = 0
    i = 2
    while i < len(argv):
        if argv[i] == "--host" and i + 1 < len(argv):
            host = argv[i + 1]
            i += 2
        elif argv[i] == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
            i += 2
        elif argv[i] == "--x" and i + 1 < len(argv):
            x = int(argv[i + 1])
            i += 2
        elif argv[i] == "--y" and i + 1 < len(argv):
            y = int(argv[i + 1])
            i += 2
        elif argv[i] == "--x2" and i + 1 < len(argv):
            x2 = int(argv[i + 1])
            i += 2
        elif argv[i] == "--y2" and i + 1 < len(argv):
            y2 = int(argv[i + 1])
            i += 2
        elif argv[i] == "--button" and i + 1 < len(argv):
            button = argv[i + 1].strip().lower()
            i += 2
        elif argv[i] == "--dy" and i + 1 < len(argv):
            dy = int(argv[i + 1])
            i += 2
        elif argv[i] == "--key" and i + 1 < len(argv):
            key = argv[i + 1]
            i += 2
        elif argv[i] == "--repeat" and i + 1 < len(argv):
            repeats = int(argv[i + 1])
            i += 2
        else:
            print(f"unknown arg: {argv[i]}", file=sys.stderr)
            return 2
    try:
        if mode == "click":
            n = run(mode, host=host, port=port, x=x, y=y, button=button)
            print(f"ok click x={x} y={y} button={button} n={n}")
            return 0
        if mode == "drag":
            n = run(mode, host=host, port=port, x=x, y=y, x2=x2, y2=y2)
            print(f"ok drag ({x},{y})->({x2},{y2}) n={n}")
            return 0
        if mode == "wander":
            n = run(mode, host=host, port=port)
            print(f"ok wander hops={n}")
            return 0
        if mode == "scroll":
            n = run(mode, host=host, port=port, x=x, y=y, dy=dy)
            print(f"ok scroll dy={dy} clicks={n} at={x},{y}")
            return 0
        if mode == "key":
            n = run(mode, host=host, port=port, key=key, repeats=repeats)
            print(f"ok key={key} n={n}")
            return 0
        text = sys.stdin.buffer.read().decode("utf-8")
        if not text:
            print("empty stdin", file=sys.stderr)
            return 2
        n = run(mode, text, host=host, port=port)
    except Exception as exc:
        print(f"vnc_type failed: {exc}", file=sys.stderr)
        return 1
    print(f"ok chars={n} mode={mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
