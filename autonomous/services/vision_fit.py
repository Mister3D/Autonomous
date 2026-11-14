"""Shrink an image before it is sent to the model.

The chat and ``~/files`` keep the original. The model gets a copy whose long
side is at most 2048 px, which is enough to read a screenshot or a photo
without shipping the full file.

Pillow is used when it is installed. Otherwise PNG (stdlib), WebP (libwebp,
already on the system) and baseline JPEG are decoded here.
"""

from __future__ import annotations

import base64
import ctypes
import io
import struct
import zlib
from pathlib import Path

MAX_SIDE = 2048
# Already small enough: leave the original bytes alone.
PASS_BYTES = 2 * 1024 * 1024

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def fit_image_path(path: Path, mime: str) -> tuple[bytes, str] | None:
    """Return ``(bytes, mime)`` for the model, or None when the file cannot be used."""
    try:
        size = path.stat().st_size
        raw = path.read_bytes()
    except OSError:
        return None
    return _fit_bytes(raw, mime, size)


def fit_image_b64(data_b64: str, mime: str) -> tuple[str, str] | None:
    """Same as :func:`fit_image_path` for a base64 payload. Returns base64 + mime."""
    try:
        raw = base64.b64decode("".join((data_b64 or "").split()), validate=False)
    except Exception:
        return None
    fitted = _fit_bytes(raw, mime, len(raw))
    if fitted is None:
        return None
    out, out_mime = fitted
    if out is raw:
        return data_b64, mime
    return base64.b64encode(out).decode("ascii"), out_mime


def _fit_bytes(raw: bytes, mime: str, size: int) -> tuple[bytes, str] | None:
    if size <= 0:
        return None
    dims = _dimensions(raw)
    if (
        dims is not None
        and max(dims) <= MAX_SIDE
        and size <= PASS_BYTES
    ):
        return raw, mime
    decoded = _decode(raw, mime)
    if decoded is None:
        if size <= PASS_BYTES:
            return raw, mime
        return None
    width, height, rgb = decoded
    if width <= 0 or height <= 0:
        return None
    nw, nh = _target_size(width, height)
    if (nw, nh) != (width, height):
        rgb = _resize(rgb, width, height, nw, nh)
        width, height = nw, nh
    from autonomous.services.grounding_image import png_bytes

    return png_bytes(width, height, rgb), "image/png"


def _target_size(width: int, height: int) -> tuple[int, int]:
    longest = max(width, height)
    if longest <= MAX_SIDE:
        return width, height
    scale = MAX_SIDE / longest
    return max(1, int(width * scale)), max(1, int(height * scale))


def _resize(rgb: bytes | bytearray, width: int, height: int, nw: int, nh: int) -> bytes:
    """Box average. One sample per source pixel that lands in the dest pixel."""
    out = bytearray(nw * nh * 3)
    for y in range(nh):
        y0 = y * height // nh
        y1 = max(y0 + 1, (y + 1) * height // nh)
        for x in range(nw):
            x0 = x * width // nw
            x1 = max(x0 + 1, (x + 1) * width // nw)
            acc = [0, 0, 0]
            count = 0
            for sy in range(y0, y1):
                row = sy * width
                for sx in range(x0, x1):
                    i = (row + sx) * 3
                    acc[0] += rgb[i]
                    acc[1] += rgb[i + 1]
                    acc[2] += rgb[i + 2]
                    count += 1
            di = (y * nw + x) * 3
            out[di] = acc[0] // count
            out[di + 1] = acc[1] // count
            out[di + 2] = acc[2] // count
    return bytes(out)


def _dimensions(data: bytes) -> tuple[int, int] | None:
    if data.startswith(_PNG_SIG) and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data.startswith(b"\xff\xd8"):
        return _jpeg_size(data)
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return _webp_size(data)
    return None


def _decode(data: bytes, mime: str) -> tuple[int, int, bytes] | None:
    kind = (mime or "").split(";", 1)[0].strip().lower()
    if data.startswith(_PNG_SIG) or kind == "image/png":
        got = _decode_png(data)
        if got is not None:
            return got
    if data.startswith(b"RIFF") or kind == "image/webp":
        got = _decode_webp(data)
        if got is not None:
            return got
    if data.startswith(b"\xff\xd8") or kind in ("image/jpeg", "image/jpg"):
        got = _decode_jpeg(data)
        if got is not None:
            return got
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(data)) as im:
            rgb = im.convert("RGB")
            w, h = rgb.size
            return w, h, rgb.tobytes()
    except Exception:
        return None


def _decode_png(data: bytes) -> tuple[int, int, bytes] | None:
    if not data.startswith(_PNG_SIG):
        return None
    pos = 8
    width = height = bit_depth = color_type = interlace = 0
    palette = b""
    idat = bytearray()
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        tag = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            if len(chunk) < 13:
                return None
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(
                ">IIBBBBB", chunk[:13]
            )
        elif tag == b"PLTE":
            palette = chunk
        elif tag == b"IDAT":
            idat.extend(chunk)
        elif tag == b"IEND":
            break
    if width <= 0 or height <= 0 or bit_depth != 8 or interlace != 0:
        return None
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        return None
    if color_type == 3 and len(palette) < 3:
        return None
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error:
        return None
    stride = width * channels
    if len(raw) < (stride + 1) * height:
        return None
    try:
        rows = _unfilter(raw, width, height, channels)
    except ValueError:
        return None
    rgb = bytearray(width * height * 3)
    for y in range(height):
        src = rows[y]
        for x in range(width):
            di = (y * width + x) * 3
            if color_type == 0:
                v = src[x]
                rgb[di : di + 3] = bytes((v, v, v))
            elif color_type == 2:
                i = x * 3
                rgb[di : di + 3] = src[i : i + 3]
            elif color_type == 3:
                idx = src[x] * 3
                if idx + 2 >= len(palette):
                    return None
                rgb[di : di + 3] = palette[idx : idx + 3]
            elif color_type == 4:
                v = src[x * 2]
                rgb[di : di + 3] = bytes((v, v, v))
            else:
                i = x * 4
                rgb[di : di + 3] = src[i : i + 3]
    return width, height, bytes(rgb)


def _unfilter(raw: bytes, width: int, height: int, channels: int) -> list[bytearray]:
    stride = width * channels
    rows: list[bytearray] = []
    prev = bytearray(stride)
    offset = 0
    for _ in range(height):
        filt = raw[offset]
        row = bytearray(raw[offset + 1 : offset + 1 + stride])
        offset += stride + 1
        if filt == 1:
            for i in range(stride):
                left = row[i - channels] if i >= channels else 0
                row[i] = (row[i] + left) & 255
        elif filt == 2:
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 255
        elif filt == 3:
            for i in range(stride):
                left = row[i - channels] if i >= channels else 0
                row[i] = (row[i] + ((left + prev[i]) // 2)) & 255
        elif filt == 4:
            for i in range(stride):
                left = row[i - channels] if i >= channels else 0
                up = prev[i]
                ul = prev[i - channels] if i >= channels else 0
                row[i] = (row[i] + _paeth(left, up, ul)) & 255
        elif filt != 0:
            raise ValueError("bad png filter")
        rows.append(row)
        prev = row
    return rows


def _paeth(left: int, up: int, ul: int) -> int:
    estimate = left + up - ul
    dl = abs(estimate - left)
    du = abs(estimate - up)
    dul = abs(estimate - ul)
    if dl <= du and dl <= dul:
        return left
    if du <= dul:
        return up
    return ul


def _webp_size(data: bytes) -> tuple[int, int] | None:
    lib = _webp()
    if lib is None:
        return None
    w = ctypes.c_int()
    h = ctypes.c_int()
    buf = ctypes.create_string_buffer(data)
    if not lib.WebPGetInfo(buf, len(data), ctypes.byref(w), ctypes.byref(h)):
        return None
    if w.value <= 0 or h.value <= 0:
        return None
    return w.value, h.value


def _decode_webp(data: bytes) -> tuple[int, int, bytes] | None:
    lib = _webp()
    if lib is None or not data.startswith(b"RIFF"):
        return None
    w = ctypes.c_int()
    h = ctypes.c_int()
    buf = ctypes.create_string_buffer(data)
    ptr = lib.WebPDecodeRGB(buf, len(data), ctypes.byref(w), ctypes.byref(h))
    if not ptr or w.value <= 0 or h.value <= 0:
        return None
    try:
        raw = ctypes.string_at(ptr, w.value * h.value * 3)
    finally:
        lib.WebPFree(ptr)
    return w.value, h.value, raw


_WEBP = None
_WEBP_TRIED = False


def _webp():
    global _WEBP, _WEBP_TRIED
    if _WEBP_TRIED:
        return _WEBP
    _WEBP_TRIED = True
    try:
        lib = ctypes.CDLL("libwebp.so.7")
        lib.WebPGetInfo.argtypes = [
            ctypes.c_void_p, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
        ]
        lib.WebPGetInfo.restype = ctypes.c_int
        lib.WebPDecodeRGB.argtypes = [
            ctypes.c_void_p, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
        ]
        lib.WebPDecodeRGB.restype = ctypes.c_void_p
        lib.WebPFree.argtypes = [ctypes.c_void_p]
        _WEBP = lib
    except OSError:
        _WEBP = None
    return _WEBP


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    """SOF width/height. Does not decode the pixels."""
    pos = 2
    n = len(data)
    while pos + 4 <= n:
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        pos += 2
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if pos + 2 > n:
            return None
        seg = struct.unpack(">H", data[pos : pos + 2])[0]
        if marker in (0xC0, 0xC1, 0xC2) and pos + 7 <= n:
            height, width = struct.unpack(">HH", data[pos + 3 : pos + 7])
            if width > 0 and height > 0:
                return width, height
        pos += seg
    return None


def _decode_jpeg(data: bytes) -> tuple[int, int, bytes] | None:
    """Baseline JPEG (SOF0), YCbCr, 4:4:4 or 4:2:0. None for progressive."""
    try:
        return _Jpeg(data).decode()
    except Exception:
        return None


class _Jpeg:
    """Small baseline decoder. Enough for photos and screenshots saved as JPEG."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.quants: dict[int, list[int]] = {}
        self.huffs: dict[tuple[int, int], tuple[list[int], list[int]]] = {}
        self.width = 0
        self.height = 0
        self.components: list[dict] = []
        self.restart = 0

    def decode(self) -> tuple[int, int, bytes] | None:
        if self.data[:2] != b"\xff\xd8":
            return None
        self.pos = 2
        sof = False
        while self.pos < len(self.data):
            marker = self._marker()
            if marker == 0xD9:
                break
            if marker == 0xDA:
                if not sof:
                    return None
                return self._scan()
            if marker in (0xC0,):
                self._sof()
                sof = True
            elif marker == 0xC2:
                return None
            elif marker == 0xDB:
                self._dqt()
            elif marker == 0xC4:
                self._dht()
            elif marker == 0xDD:
                self._dri()
            else:
                self._skip()
        return None

    def _marker(self) -> int:
        data = self.data
        while self.pos < len(data) and data[self.pos] != 0xFF:
            self.pos += 1
        while self.pos < len(data) and data[self.pos] == 0xFF:
            self.pos += 1
        if self.pos >= len(data):
            raise ValueError("truncated jpeg")
        marker = data[self.pos]
        self.pos += 1
        return marker

    def _segment(self) -> bytes:
        if self.pos + 2 > len(self.data):
            raise ValueError("truncated jpeg")
        length = struct.unpack(">H", self.data[self.pos : self.pos + 2])[0]
        if length < 2 or self.pos + length > len(self.data):
            raise ValueError("bad jpeg segment")
        body = self.data[self.pos + 2 : self.pos + length]
        self.pos += length
        return body

    def _skip(self) -> None:
        self._segment()

    def _dqt(self) -> None:
        body = self._segment()
        i = 0
        while i < len(body):
            header = body[i]
            i += 1
            table = header & 15
            precision = header >> 4
            count = 64 * (precision + 1)
            raw = body[i : i + count]
            i += count
            if precision:
                vals = [struct.unpack(">H", raw[j : j + 2])[0] for j in range(0, 128, 2)]
            else:
                vals = list(raw)
            if len(vals) != 64:
                raise ValueError("bad dqt")
            ordered = [0] * 64
            for zig, value in enumerate(vals):
                ordered[_ZIGZAG[zig]] = value
            self.quants[table] = ordered

    def _dht(self) -> None:
        body = self._segment()
        i = 0
        while i < len(body):
            header = body[i]
            i += 1
            klass = header >> 4
            table = header & 15
            counts = list(body[i : i + 16])
            i += 16
            total = sum(counts)
            symbols = list(body[i : i + total])
            i += total
            self.huffs[(klass, table)] = (counts, symbols)

    def _dri(self) -> None:
        body = self._segment()
        self.restart = struct.unpack(">H", body[:2])[0]

    def _sof(self) -> None:
        body = self._segment()
        if body[0] != 8:
            raise ValueError("jpeg precision")
        self.height, self.width = struct.unpack(">HH", body[1:5])
        count = body[5]
        self.components = []
        pos = 6
        for _ in range(count):
            cid, samp, qid = body[pos], body[pos + 1], body[pos + 2]
            pos += 3
            self.components.append({
                "id": cid,
                "h": samp >> 4,
                "v": samp & 15,
                "q": qid,
            })

    def _scan(self) -> tuple[int, int, bytes]:
        if self.pos + 2 > len(self.data):
            raise ValueError("truncated sos")
        length = struct.unpack(">H", self.data[self.pos : self.pos + 2])[0]
        body = self.data[self.pos + 2 : self.pos + length]
        self.pos += length
        count = body[0]
        mapping = {}
        pos = 1
        for _ in range(count):
            cid, tables = body[pos], body[pos + 1]
            pos += 2
            mapping[cid] = (tables >> 4, tables & 15)
        bits = _Bitstream(self.data, self.pos)
        comps = []
        max_h = max(c["h"] for c in self.components)
        max_v = max(c["v"] for c in self.components)
        for comp in self.components:
            dc_id, ac_id = mapping[comp["id"]]
            comps.append({
                **comp,
                "dc": _Huffman(*self.huffs[(0, dc_id)]),
                "ac": _Huffman(*self.huffs[(1, ac_id)]),
                "quant": self.quants[comp["q"]],
                "pred": 0,
                "blocks_x": (self.width + 8 * max_h - 1) // (8 * max_h) * comp["h"],
                "blocks_y": (self.height + 8 * max_v - 1) // (8 * max_v) * comp["v"],
            })
        mcu_w = max_h * 8
        mcu_h = max_v * 8
        mcus_x = (self.width + mcu_w - 1) // mcu_w
        mcus_y = (self.height + mcu_h - 1) // mcu_h
        planes = [
            [0] * (c["blocks_x"] * c["blocks_y"] * 64)
            for c in comps
        ]
        mcu_index = 0
        for my in range(mcus_y):
            for mx in range(mcus_x):
                if self.restart and mcu_index and mcu_index % self.restart == 0:
                    bits.skip_restart()
                    for c in comps:
                        c["pred"] = 0
                for ci, comp in enumerate(comps):
                    for vy in range(comp["v"]):
                        for hx in range(comp["h"]):
                            bx = mx * comp["h"] + hx
                            by = my * comp["v"] + vy
                            block = _read_block(bits, comp)
                            dest = (by * comp["blocks_x"] + bx) * 64
                            planes[ci][dest : dest + 64] = block
                mcu_index += 1
        return self.width, self.height, _ycbcr_to_rgb(
            self.width, self.height, comps, planes, max_h, max_v
        )


_ZIGZAG = [
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5,
    12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
]


class _Bitstream:
    def __init__(self, data: bytes, pos: int) -> None:
        self.data = data
        self.pos = pos
        self.acc = 0
        self.n = 0

    def _pull(self) -> int:
        if self.pos >= len(self.data):
            raise ValueError("jpeg bits")
        byte = self.data[self.pos]
        self.pos += 1
        if byte == 0xFF:
            if self.pos >= len(self.data):
                raise ValueError("jpeg bits")
            nxt = self.data[self.pos]
            self.pos += 1
            if nxt == 0x00:
                return 0xFF
            # Marker stuffed into the scan. Step back so the caller can see it.
            self.pos -= 2
            return -1
        return byte

    def read(self, count: int) -> int:
        while self.n < count:
            byte = self._pull()
            if byte < 0:
                raise ValueError("marker in entropy")
            self.acc = (self.acc << 8) | byte
            self.n += 8
        self.n -= count
        value = (self.acc >> self.n) & ((1 << count) - 1)
        return value

    def align(self) -> None:
        self.n = 0
        self.acc = 0

    def skip_restart(self) -> None:
        self.align()
        if (
            self.pos + 1 < len(self.data)
            and self.data[self.pos] == 0xFF
            and 0xD0 <= self.data[self.pos + 1] <= 0xD7
        ):
            self.pos += 2


class _Huffman:
    def __init__(self, counts: list[int], symbols: list[int]) -> None:
        self.lookup: dict[int, tuple[int, int]] = {}
        code = 0
        index = 0
        for length, count in enumerate(counts, start=1):
            for _ in range(count):
                self.lookup[(code, length)] = (symbols[index], length)
                index += 1
                code += 1
            code <<= 1

    def decode(self, bits: _Bitstream) -> int:
        code = 0
        for length in range(1, 17):
            code = (code << 1) | bits.read(1)
            found = self.lookup.get((code, length))
            if found is not None:
                return found[0]
        raise ValueError("bad huffman")


def _read_block(bits: _Bitstream, comp: dict) -> list[int]:
    comp["pred"] += _receive(bits, comp["dc"].decode(bits))
    coef = [0] * 64
    coef[0] = comp["pred"]
    k = 1
    while k < 64:
        symbol = comp["ac"].decode(bits)
        if symbol == 0:
            break
        if symbol == 0xF0:
            k += 16
            continue
        k += symbol >> 4
        size = symbol & 15
        if k >= 64 or size == 0:
            break
        coef[_ZIGZAG[k]] = _receive(bits, size)
        k += 1
    quant = comp["quant"]
    for i in range(64):
        coef[i] *= quant[i]
    return _idct(coef)


def _receive(bits: _Bitstream, length: int) -> int:
    if length == 0:
        return 0
    value = bits.read(length)
    if value < (1 << (length - 1)):
        value -= (1 << length) - 1
    return value


def _idct(block: list[int]) -> list[int]:
    """Slow integer IDCT, output 0..255 centered then shifted."""
    out = [0] * 64
    for y in range(8):
        for x in range(8):
            acc = 0.0
            for v in range(8):
                for u in range(8):
                    coef = block[v * 8 + u]
                    if coef == 0:
                        continue
                    cu = 0.70710678118 if u == 0 else 1.0
                    cv = 0.70710678118 if v == 0 else 1.0
                    acc += (
                        cu * cv * coef
                        * _COS[u][x]
                        * _COS[v][y]
                    )
            out[y * 8 + x] = int(round(acc / 4.0 + 128))
    return out


_COS = [
    [__import__("math").cos((2 * x + 1) * u * __import__("math").pi / 16) for x in range(8)]
    for u in range(8)
]


def _plane_at(plane: list[int], comp: dict, sx: int, sy: int) -> int:
    bx, ix = divmod(sx, 8)
    by, iy = divmod(sy, 8)
    if bx < 0 or by < 0 or bx >= comp["blocks_x"] or by >= comp["blocks_y"]:
        return 128
    return plane[(by * comp["blocks_x"] + bx) * 64 + iy * 8 + ix]


def _ycbcr_to_rgb(
    width: int,
    height: int,
    comps: list[dict],
    planes: list[list[int]],
    max_h: int,
    max_v: int,
) -> bytes:
    rgb = bytearray(width * height * 3)
    if len(comps) == 1:
        for y in range(height):
            for x in range(width):
                sx = x * comps[0]["h"] // max_h
                sy = y * comps[0]["v"] // max_v
                value = _clamp(_plane_at(planes[0], comps[0], sx, sy))
                i = (y * width + x) * 3
                rgb[i : i + 3] = bytes((value, value, value))
        return bytes(rgb)
    for y in range(height):
        for x in range(width):
            samples = []
            for comp, plane in zip(comps, planes):
                sx = x * comp["h"] // max_h
                sy = y * comp["v"] // max_v
                samples.append(_plane_at(plane, comp, sx, sy))
            yy, cb, cr = samples[0], samples[1] - 128, samples[2] - 128
            i = (y * width + x) * 3
            rgb[i] = _clamp(yy + 1.402 * cr)
            rgb[i + 1] = _clamp(yy - 0.344136 * cb - 0.714136 * cr)
            rgb[i + 2] = _clamp(yy + 1.772 * cb)
    return bytes(rgb)


def _clamp(value: float) -> int:
    if value < 0:
        return 0
    if value > 255:
        return 255
    return int(round(value))
