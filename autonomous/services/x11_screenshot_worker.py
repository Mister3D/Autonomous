#!/usr/bin/env python3
"""Capture X11 root window to PNG (stdlib + libX11 via ctypes).

Run inside the desktop container with DISPLAY set, e.g.:
  python3 x11_screenshot_worker.py /tmp/out.png
"""

from __future__ import annotations

import ctypes
import ctypes.util
import struct
import sys
import zlib
from ctypes import POINTER, byref, c_char_p, c_int, c_uint, c_ulong, c_void_p


class XImage(ctypes.Structure):
    _fields_ = [
        ("width", c_int),
        ("height", c_int),
        ("xoffset", c_int),
        ("format", c_int),
        ("data", c_void_p),
        ("byte_order", c_int),
        ("bitmap_unit", c_int),
        ("bitmap_bit_order", c_int),
        ("bitmap_pad", c_int),
        ("depth", c_int),
        ("bytes_per_line", c_int),
        ("bits_per_pixel", c_int),
        ("red_mask", c_ulong),
        ("green_mask", c_ulong),
        ("blue_mask", c_ulong),
    ]


def _mask_shift(mask: int) -> int:
    if mask == 0:
        return 0
    shift = 0
    while mask and (mask & 1) == 0:
        mask >>= 1
        shift += 1
    return shift


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_png(path: str, width: int, height: int, rgb: bytes) -> None:
    # rgb = packed RGB rows, width*3 each
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)  # filter None
        start = y * stride
        raw.extend(rgb[start : start + stride])
    compressed = zlib.compress(bytes(raw), 6)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    png = b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", compressed) + _png_chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def capture(out_path: str) -> tuple[int, int]:
    lib_name = ctypes.util.find_library("X11")
    if not lib_name:
        raise RuntimeError("libX11 not found")
    lib = ctypes.CDLL(lib_name)
    lib.XOpenDisplay.argtypes = [c_char_p]
    lib.XOpenDisplay.restype = c_void_p
    lib.XDefaultRootWindow.argtypes = [c_void_p]
    lib.XDefaultRootWindow.restype = c_ulong
    lib.XGetGeometry.argtypes = [
        c_void_p,
        c_ulong,
        POINTER(c_ulong),
        POINTER(c_int),
        POINTER(c_int),
        POINTER(c_uint),
        POINTER(c_uint),
        POINTER(c_uint),
        POINTER(c_uint),
    ]
    lib.XGetGeometry.restype = c_int
    lib.XGetImage.argtypes = [c_void_p, c_ulong, c_int, c_int, c_uint, c_uint, c_ulong, c_int]
    lib.XGetImage.restype = c_void_p
    lib.XDestroyImage.argtypes = [c_void_p]
    lib.XDestroyImage.restype = c_int
    lib.XCloseDisplay.argtypes = [c_void_p]
    lib.XCloseDisplay.restype = c_int

    display = lib.XOpenDisplay(None)
    if not display:
        raise RuntimeError("XOpenDisplay failed (is DISPLAY set?)")
    try:
        root = lib.XDefaultRootWindow(display)
        root_ret = c_ulong()
        x = c_int()
        y = c_int()
        w = c_uint()
        h = c_uint()
        bw = c_uint()
        depth = c_uint()
        if not lib.XGetGeometry(
            display, root, byref(root_ret), byref(x), byref(y), byref(w), byref(h), byref(bw), byref(depth)
        ):
            raise RuntimeError("XGetGeometry failed")
        width, height = int(w.value), int(h.value)
        ZPixmap = 2
        AllPlanes = 0xFFFFFFFFFFFFFFFF
        img_p = lib.XGetImage(display, root, 0, 0, width, height, AllPlanes, ZPixmap)
        if not img_p:
            raise RuntimeError("XGetImage failed")
        try:
            img = ctypes.cast(img_p, POINTER(XImage)).contents
            if img.bits_per_pixel not in (24, 32):
                raise RuntimeError(f"unsupported bits_per_pixel={img.bits_per_pixel}")
            r_shift = _mask_shift(int(img.red_mask))
            g_shift = _mask_shift(int(img.green_mask))
            b_shift = _mask_shift(int(img.blue_mask))
            src = ctypes.string_at(img.data, img.bytes_per_line * height)
            bpp = img.bits_per_pixel // 8
            rgb = bytearray(width * height * 3)
            di = 0
            for row in range(height):
                off = row * img.bytes_per_line
                for col in range(width):
                    px = off + col * bpp
                    if bpp == 4:
                        pixel = int.from_bytes(src[px : px + 4], "little")
                    else:
                        pixel = int.from_bytes(src[px : px + 3], "little")
                    rgb[di] = (pixel >> r_shift) & 0xFF
                    rgb[di + 1] = (pixel >> g_shift) & 0xFF
                    rgb[di + 2] = (pixel >> b_shift) & 0xFF
                    di += 3
            write_png(out_path, width, height, bytes(rgb))
            return width, height
        finally:
            lib.XDestroyImage(img_p)
    finally:
        lib.XCloseDisplay(display)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: x11_screenshot_worker.py <out.png>", file=sys.stderr)
        return 2
    out = argv[1]
    try:
        w, h = capture(out)
    except Exception as exc:
        print(f"screenshot failed: {exc}", file=sys.stderr)
        return 1
    print(f"{w}x{h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
