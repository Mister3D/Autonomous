"""Minimal RGB PNG ops for GUI grounding (stdlib only — no Pillow)."""

from __future__ import annotations

import base64
import math
import struct
import zlib
from pathlib import Path


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_png(path: str | Path, width: int, height: int, rgb: bytes | bytearray) -> None:
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        start = y * stride
        raw.extend(rgb[start : start + stride])
    compressed = zlib.compress(bytes(raw), 6)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )
    Path(path).write_bytes(png)


def png_bytes(width: int, height: int, rgb: bytes | bytearray) -> bytes:
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        start = y * stride
        raw.extend(rgb[start : start + stride])
    compressed = zlib.compress(bytes(raw), 6)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


def data_url_png(width: int, height: int, rgb: bytes | bytearray) -> str:
    b64 = base64.b64encode(png_bytes(width, height, rgb)).decode("ascii")
    return f"data:image/png;base64,{b64}"


def read_png(path: str | Path) -> tuple[int, int, bytearray]:
    """Read 8-bit RGB (color type 2) or RGBA (6) PNG → packed RGB."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos = 8
    width = height = 0
    bit_depth = 8
    color_type = 2
    idat = bytearray()
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        tag = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk[:10])
            if bit_depth != 8 or color_type not in (2, 6):
                raise ValueError(f"unsupported PNG type depth={bit_depth} ct={color_type}")
        elif tag == b"IDAT":
            idat.extend(chunk)
        elif tag == b"IEND":
            break
    raw = zlib.decompress(bytes(idat))
    bpp = 3 if color_type == 2 else 4
    stride = width * bpp
    expected = (stride + 1) * height
    if len(raw) < expected:
        raise ValueError("truncated PNG data")
    # Only filter type 0 (None) — our screenshots + our writers use that.
    rgb = bytearray(width * height * 3)
    for y in range(height):
        row_start = y * (stride + 1)
        if raw[row_start] != 0:
            raise ValueError(f"unsupported PNG filter {raw[row_start]} (need 0)")
        src = row_start + 1
        dst = y * width * 3
        if color_type == 2:
            rgb[dst : dst + width * 3] = raw[src : src + width * 3]
        else:
            for x in range(width):
                i = src + x * 4
                o = dst + x * 3
                rgb[o : o + 3] = raw[i : i + 3]
    return width, height, rgb


def resize_nn(
    width: int, height: int, rgb: bytes | bytearray, new_w: int, new_h: int
) -> bytearray:
    """Nearest-neighbour resize (deterministic)."""
    out = bytearray(new_w * new_h * 3)
    for y in range(new_h):
        sy = min(height - 1, (y * height) // new_h)
        for x in range(new_w):
            sx = min(width - 1, (x * width) // new_w)
            si = (sy * width + sx) * 3
            di = (y * new_w + x) * 3
            out[di : di + 3] = rgb[si : si + 3]
    return out


def fit_size(
    width: int,
    height: int,
    *,
    max_side: int = 1280,
    multiple: int = 28,
    max_pixels: int = 1280 * 1280,
) -> tuple[int, int]:
    """Deterministic size for the grounder (aspect preserved, multiples)."""
    if width <= 0 or height <= 0:
        raise ValueError("invalid size")
    scale = min(1.0, max_side / max(width, height))
    if width * height * scale * scale > max_pixels:
        scale = (max_pixels / (width * height)) ** 0.5
    w = max(multiple, int(round(width * scale)))
    h = max(multiple, int(round(height * scale)))
    w = max(multiple, (w // multiple) * multiple)
    h = max(multiple, (h // multiple) * multiple)
    return w, h


def _set_px(
    rgb: bytearray, w: int, h: int, x: int, y: int, color: tuple[int, int, int]
) -> None:
    if 0 <= x < w and 0 <= y < h:
        i = (y * w + x) * 3
        rgb[i], rgb[i + 1], rgb[i + 2] = color


def _stroke_disk(
    rgb: bytearray,
    w: int,
    h: int,
    x: int,
    y: int,
    *,
    r: float,
    color: tuple[int, int, int],
) -> None:
    """Filled disk (for halo / thick stroke samples)."""
    ri = int(math.ceil(r))
    r2 = r * r
    for dy in range(-ri, ri + 1):
        for dx in range(-ri, ri + 1):
            if dx * dx + dy * dy <= r2:
                _set_px(rgb, w, h, x + dx, y + dy, color)


def _stroke_line(
    rgb: bytearray,
    w: int,
    h: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    *,
    color: tuple[int, int, int],
    thickness: float = 1.0,
) -> None:
    """Bresenham-ish thick line via disk stamps (no full-bleed spans)."""
    dx = x1 - x0
    dy = y1 - y0
    steps = max(abs(dx), abs(dy), 1)
    for i in range(steps + 1):
        t = i / steps
        x = int(round(x0 + dx * t))
        y = int(round(y0 + dy * t))
        _stroke_disk(rgb, w, h, x, y, r=thickness, color=color)


def draw_hollow_cross(
    width: int,
    height: int,
    rgb: bytes | bytearray,
    x: int,
    y: int,
    *,
    gap: int = 5,
    radius: int = 14,
    arm: int = 22,
) -> bytearray:
    """Compact hollow reticle — short arms + ring; center pixel stays visible.

    No full-screen crosshairs (those look like giant arrows and drown the UI).
    """
    out = bytearray(rgb)
    cx, cy = int(x), int(y)
    white = (255, 255, 255)
    red = (220, 40, 40)

    # Four short arms (outside the hole), halo then red.
    segments = [
        (cx - (gap + arm), cy, cx - gap, cy),  # left
        (cx + gap, cy, cx + gap + arm, cy),  # right
        (cx, cy - (gap + arm), cx, cy - gap),  # up
        (cx, cy + gap, cx, cy + gap + arm),  # down
    ]
    for x0, y0, x1, y1 in segments:
        _stroke_line(out, width, height, x0, y0, x1, y1, color=white, thickness=2.0)
    for x0, y0, x1, y1 in segments:
        _stroke_line(out, width, height, x0, y0, x1, y1, color=red, thickness=1.0)

    # Ring around the hole (donut): paint ring pixels only.
    r_out = float(radius)
    r_in = float(max(gap + 1, radius - 3))
    for deg in range(0, 360, 1):
        rad = math.radians(deg)
        for rr in (r_in, (r_in + r_out) / 2, r_out):
            px = int(round(cx + rr * math.cos(rad)))
            py = int(round(cy + rr * math.sin(rad)))
            _set_px(out, width, height, px, py, white)
            _set_px(out, width, height, px + 1, py, white)
    for deg in range(0, 360, 1):
        rad = math.radians(deg)
        px = int(round(cx + r_out * math.cos(rad)))
        py = int(round(cy + r_out * math.sin(rad)))
        _set_px(out, width, height, px, py, red)
        px2 = int(round(cx + ((r_in + r_out) / 2) * math.cos(rad)))
        py2 = int(round(cy + ((r_in + r_out) / 2) * math.sin(rad)))
        _set_px(out, width, height, px2, py2, red)

    # Tiny center tick (not filling the hole): leave (cx,cy) original.
    return out


def draw_drag_connector(
    width: int,
    height: int,
    rgb: bytes | bytearray,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
) -> bytearray:
    """Subtle dashed connector + small chevron (drag start → end)."""
    out = bytearray(rgb)
    white = (255, 255, 255)
    red = (220, 40, 40)
    dx = x1 - x0
    dy = y1 - y0
    dist = math.hypot(dx, dy) or 1.0
    ux, uy = dx / dist, dy / dist
    # Pull endpoints off the reticle centers a bit
    sx = int(round(x0 + ux * 18))
    sy = int(round(y0 + uy * 18))
    ex = int(round(x1 - ux * 18))
    ey = int(round(y1 - uy * 18))
    steps = max(int(dist), 1)
    for i in range(steps + 1):
        if (i // 6) % 2 == 1:
            continue  # dash gap
        t = i / steps
        x = int(round(sx + (ex - sx) * t))
        y = int(round(sy + (ey - sy) * t))
        _stroke_disk(out, width, height, x, y, r=1.6, color=white)
        _set_px(out, width, height, x, y, red)
    # Chevron tip at end
    px, py = -uy, ux  # perpendicular
    tip = (ex, ey)
    left = (int(round(ex - ux * 10 + px * 6)), int(round(ey - uy * 10 + py * 6)))
    right = (int(round(ex - ux * 10 - px * 6)), int(round(ey - uy * 10 - py * 6)))
    _stroke_line(out, width, height, tip[0], tip[1], left[0], left[1], color=white, thickness=1.8)
    _stroke_line(out, width, height, tip[0], tip[1], right[0], right[1], color=white, thickness=1.8)
    _stroke_line(out, width, height, tip[0], tip[1], left[0], left[1], color=red, thickness=1.0)
    _stroke_line(out, width, height, tip[0], tip[1], right[0], right[1], color=red, thickness=1.0)
    return out


def zoom_around(
    width: int,
    height: int,
    rgb: bytes | bytearray,
    x: int,
    y: int,
    *,
    crop: int = 160,
    zoom: int = 2,
) -> tuple[int, int, bytearray]:
    """Crop around point then nearest-neighbour zoom."""
    half = crop // 2
    x0 = max(0, min(width - crop, x - half))
    y0 = max(0, min(height - crop, y - half))
    if width < crop:
        x0, cw = 0, width
    else:
        cw = crop
    if height < crop:
        y0, ch = 0, height
    else:
        ch = crop
    patch = bytearray(cw * ch * 3)
    for row in range(ch):
        src = ((y0 + row) * width + x0) * 3
        dst = row * cw * 3
        patch[dst : dst + cw * 3] = rgb[src : src + cw * 3]
    return cw * zoom, ch * zoom, resize_nn(cw, ch, patch, cw * zoom, ch * zoom)


def stack_vertical(
    sheets: list[tuple[int, int, bytearray]],
    *,
    gap: int = 8,
    bg: tuple[int, int, int] = (32, 32, 32),
) -> tuple[int, int, bytearray]:
    width = max(s[0] for s in sheets)
    height = sum(s[1] for s in sheets) + gap * (len(sheets) - 1)
    out = bytearray(width * height * 3)
    for i in range(0, len(out), 3):
        out[i], out[i + 1], out[i + 2] = bg
    y = 0
    for w, h, rgb in sheets:
        for row in range(h):
            src = row * w * 3
            dst = ((y + row) * width) * 3
            out[dst : dst + w * 3] = rgb[src : src + w * 3]
        y += h + gap
    return width, height, out
