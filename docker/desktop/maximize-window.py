#!/usr/bin/env python3
"""Maximize Chrome windows via EWMH (_NET_WM_STATE)."""
from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--port", type=int, default=0)  # accepted for bot-chrome compat
    args = ap.parse_args()

    lib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")

    class Display(ctypes.Structure):
        pass

    DisplayPtr = ctypes.POINTER(Display)
    Window = ctypes.c_ulong
    Atom = ctypes.c_ulong
    # Xlib format-32 values are returned as C longs
    XLong = ctypes.c_long

    lib.XOpenDisplay.restype = DisplayPtr
    lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    lib.XCloseDisplay.argtypes = [DisplayPtr]
    lib.XDefaultRootWindow.restype = Window
    lib.XDefaultRootWindow.argtypes = [DisplayPtr]
    lib.XInternAtom.restype = Atom
    lib.XInternAtom.argtypes = [DisplayPtr, ctypes.c_char_p, ctypes.c_int]
    lib.XGetWindowProperty.restype = ctypes.c_int
    lib.XGetWindowProperty.argtypes = [
        DisplayPtr,
        Window,
        Atom,
        ctypes.c_long,
        ctypes.c_long,
        ctypes.c_int,
        Atom,
        ctypes.POINTER(Atom),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
    ]
    lib.XFlush.argtypes = [DisplayPtr]
    lib.XSendEvent.restype = ctypes.c_int
    lib.XSendEvent.argtypes = [DisplayPtr, Window, ctypes.c_int, ctypes.c_long, ctypes.c_void_p]
    lib.XMapRaised.argtypes = [DisplayPtr, Window]
    # Intentionally never XFree — short-lived helper; avoids ctypes/XFree crashes.

    class XClientMessageEvent(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_int),
            ("serial", ctypes.c_ulong),
            ("send_event", ctypes.c_int),
            ("display", DisplayPtr),
            ("window", Window),
            ("message_type", Atom),
            ("format", ctypes.c_int),
            ("data0", ctypes.c_long),
            ("data1", ctypes.c_long),
            ("data2", ctypes.c_long),
            ("data3", ctypes.c_long),
            ("data4", ctypes.c_long),
        ]

    class XEvent(ctypes.Union):
        _fields_ = [("type", ctypes.c_int), ("xclient", XClientMessageEvent), ("pad", ctypes.c_long * 24)]

    dpy = lib.XOpenDisplay(None)
    if not dpy:
        print("maximize-window: no DISPLAY", file=sys.stderr)
        return 1

    root = lib.XDefaultRootWindow(dpy)
    AnyPropertyType = Atom(0)
    atom_list = lib.XInternAtom(dpy, b"_NET_CLIENT_LIST", 0)
    atom_wm_class = lib.XInternAtom(dpy, b"WM_CLASS", 0)
    atom_state = lib.XInternAtom(dpy, b"_NET_WM_STATE", 0)
    atom_max_h = lib.XInternAtom(dpy, b"_NET_WM_STATE_MAXIMIZED_HORZ", 0)
    atom_max_v = lib.XInternAtom(dpy, b"_NET_WM_STATE_MAXIMIZED_VERT", 0)
    ClientMessage = 33
    masks = (1 << 20) | (1 << 19)

    def get_prop(win: int, atom: Atom, length: int = 4096):
        atype = Atom()
        fmt = ctypes.c_int()
        nitems = ctypes.c_ulong()
        bytes_after = ctypes.c_ulong()
        prop = ctypes.POINTER(ctypes.c_ubyte)()
        st = lib.XGetWindowProperty(
            dpy,
            Window(win),
            atom,
            0,
            length,
            0,
            AnyPropertyType,
            ctypes.byref(atype),
            ctypes.byref(fmt),
            ctypes.byref(nitems),
            ctypes.byref(bytes_after),
            ctypes.byref(prop),
        )
        if st != 0 or not prop or nitems.value == 0:
            return None, 0, 0
        return prop, fmt.value, int(nitems.value)

    def list_windows() -> list[int]:
        prop, fmt, nitems = get_prop(root, atom_list, 8192)
        if not prop or nitems == 0:
            return []
        if fmt == 32:
            arr = ctypes.cast(prop, ctypes.POINTER(XLong))
            return [int(arr[i]) for i in range(nitems) if int(arr[i]) != 0]
        unit = max(fmt // 8, 1)
        data = ctypes.string_at(prop, nitems * unit)
        out = []
        for i in range(0, len(data), unit):
            v = int.from_bytes(data[i : i + unit], sys.byteorder)
            if v:
                out.append(v)
        return out

    def is_chrome(win: int) -> bool:
        prop, fmt, nitems = get_prop(win, atom_wm_class, 256)
        if not prop or nitems == 0:
            return False
        unit = 4 if fmt == 32 else max(fmt // 8, 1)
        raw = ctypes.string_at(prop, nitems * unit)
        return b"chrome" in raw.lower()

    def maximize(win: int) -> None:
        lib.XMapRaised(dpy, Window(win))
        ev = XEvent()
        ev.xclient.type = ClientMessage
        ev.xclient.send_event = 1
        ev.xclient.display = dpy
        ev.xclient.window = Window(win)
        ev.xclient.message_type = atom_state
        ev.xclient.format = 32
        ev.xclient.data0 = 1
        ev.xclient.data1 = atom_max_h
        ev.xclient.data2 = atom_max_v
        ev.xclient.data3 = 1
        ev.xclient.data4 = 0
        lib.XSendEvent(dpy, root, 0, masks, ctypes.byref(ev))
        lib.XFlush(dpy)

    deadline = time.time() + args.timeout
    targets: list[int] = []
    while time.time() < deadline:
        try:
            targets = [w for w in list_windows() if is_chrome(w)]
        except Exception as exc:
            print(f"maximize-window: scan err {exc}", file=sys.stderr)
            targets = []
        if targets:
            break
        time.sleep(0.3)

    if not targets:
        lib.XCloseDisplay(dpy)
        print("maximize-window: no chrome window", file=sys.stderr)
        return 2

    for _ in range(12):
        try:
            targets = [w for w in list_windows() if is_chrome(w)] or targets
            for win in targets:
                maximize(win)
        except Exception as exc:
            print(f"maximize-window: max err {exc}", file=sys.stderr)
        time.sleep(0.35)

    lib.XCloseDisplay(dpy)
    print("maximize-window: maximized", " ".join(hex(w) for w in targets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
