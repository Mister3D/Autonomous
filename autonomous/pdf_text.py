"""Minimal Unicode PDF writer (TrueType, Identity-H) — no third-party deps.

Supports a chat-like layout: bubbles, tool cards, day separators.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class _Font:
    name: str
    data: bytes
    units_per_em: int
    ascent: int
    descent: int
    bbox: tuple[int, int, int, int]
    cmap: dict[int, int]
    advances: list[int]
    num_glyphs: int


def _u16(data: bytes, off: int) -> int:
    return struct.unpack_from(">H", data, off)[0]


def _i16(data: bytes, off: int) -> int:
    return struct.unpack_from(">h", data, off)[0]


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from(">I", data, off)[0]


def _load_ttf(path: Path, name: str) -> _Font:
    data = path.read_bytes()
    if len(data) < 12:
        raise ValueError(f"invalid font: {path}")
    num_tables = _u16(data, 4)
    tables: dict[str, tuple[int, int]] = {}
    for i in range(num_tables):
        o = 12 + i * 16
        tag = data[o : o + 4].decode("ascii", errors="ignore")
        offset = _u32(data, o + 8)
        length = _u32(data, o + 12)
        tables[tag] = (offset, length)

    def table(tag: str) -> bytes:
        if tag not in tables:
            raise ValueError(f"font missing table {tag}")
        o, n = tables[tag]
        return data[o : o + n]

    head = table("head")
    units = _u16(head, 18)
    x_min, y_min, x_max, y_max = struct.unpack_from(">hhhh", head, 36)

    hhea = table("hhea")
    ascent = _i16(hhea, 4)
    descent = _i16(hhea, 6)
    num_h_metrics = _u16(hhea, 34)

    maxp = table("maxp")
    num_glyphs = _u16(maxp, 4)

    hmtx = table("hmtx")
    advances: list[int] = []
    for i in range(num_h_metrics):
        advances.append(_u16(hmtx, i * 4))
    last = advances[-1] if advances else units
    while len(advances) < num_glyphs:
        advances.append(last)

    cmap_raw = table("cmap")
    cmap = _parse_cmap(cmap_raw)
    return _Font(
        name=name,
        data=data,
        units_per_em=units or 1000,
        ascent=ascent,
        descent=descent,
        bbox=(x_min, y_min, x_max, y_max),
        cmap=cmap,
        advances=advances,
        num_glyphs=num_glyphs,
    )


def _parse_cmap(cmap: bytes) -> dict[int, int]:
    if len(cmap) < 4:
        return {}
    num = _u16(cmap, 2)
    records = []
    for i in range(num):
        o = 4 + i * 8
        platform = _u16(cmap, o)
        encoding = _u16(cmap, o + 2)
        offset = _u32(cmap, o + 4)
        records.append((platform, encoding, offset))
    preferred = sorted(
        records,
        key=lambda r: (
            0
            if (r[0] == 3 and r[1] == 10)
            else 1
            if (r[0] == 0)
            else 2
            if (r[0] == 3 and r[1] == 1)
            else 9
        ),
    )
    out: dict[int, int] = {}
    for _, _, offset in preferred:
        if offset + 2 > len(cmap):
            continue
        fmt = _u16(cmap, offset)
        if fmt == 4:
            out.update(_parse_cmap_fmt4(cmap, offset))
            if out:
                return out
        elif fmt == 12:
            out.update(_parse_cmap_fmt12(cmap, offset))
            if out:
                return out
    return out


def _parse_cmap_fmt4(cmap: bytes, offset: int) -> dict[int, int]:
    length = _u16(cmap, offset + 2)
    seg_count_x2 = _u16(cmap, offset + 6)
    seg_count = seg_count_x2 // 2
    end_o = offset + 14
    start_o = end_o + seg_count_x2 + 2
    delta_o = start_o + seg_count_x2
    range_o = delta_o + seg_count_x2
    ends = [_u16(cmap, end_o + 2 * i) for i in range(seg_count)]
    starts = [_u16(cmap, start_o + 2 * i) for i in range(seg_count)]
    deltas = [_i16(cmap, delta_o + 2 * i) for i in range(seg_count)]
    ranges = [_u16(cmap, range_o + 2 * i) for i in range(seg_count)]
    mapping: dict[int, int] = {}
    for i in range(seg_count):
        for cp in range(starts[i], ends[i] + 1):
            if ranges[i] == 0:
                gid = (cp + deltas[i]) & 0xFFFF
            else:
                glyph_o = range_o + 2 * i + ranges[i] + 2 * (cp - starts[i])
                if glyph_o + 2 > offset + length:
                    continue
                gid = _u16(cmap, glyph_o)
                if gid != 0:
                    gid = (gid + deltas[i]) & 0xFFFF
            if gid:
                mapping[cp] = gid
    return mapping


def _parse_cmap_fmt12(cmap: bytes, offset: int) -> dict[int, int]:
    n_groups = _u32(cmap, offset + 12)
    mapping: dict[int, int] = {}
    base = offset + 16
    for i in range(n_groups):
        o = base + i * 12
        start = _u32(cmap, o)
        end = _u32(cmap, o + 4)
        glyph = _u32(cmap, o + 8)
        for cp in range(start, end + 1):
            mapping[cp] = glyph + (cp - start)
    return mapping


def _pdf_escape_name(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name) or "Font"


def _to_unicode_cmap(used: dict[int, int]) -> bytes:
    pairs = sorted((gid, cp) for cp, gid in used.items())
    lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Adobe-Identity-UCS def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<0000> <FFFF>",
        "endcodespacerange",
    ]
    i = 0
    while i < len(pairs):
        chunk = pairs[i : i + 100]
        lines.append(f"{len(chunk)} beginbfchar")
        for gid, cp in chunk:
            lines.append(f"<{gid:04X}> <{cp:04X}>")
        lines.append("endbfchar")
        i += 100
    lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    return ("\n".join(lines) + "\n").encode("ascii")


def _rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)


def _round_rect_path(x: float, y: float, w: float, h: float, r: float) -> str:
    """PDF path for a rounded rect; (x,y) = bottom-left."""
    r = min(r, w / 2, h / 2)
    # Bezier kappa for quarter circle
    k = 0.5522847498 * r
    x1, y1 = x + w, y + h
    return "\n".join(
        [
            f"{x + r:.2f} {y:.2f} m",
            f"{x1 - r:.2f} {y:.2f} l",
            f"{x1 - r + k:.2f} {y:.2f} {x1:.2f} {y + r - k:.2f} {x1:.2f} {y + r:.2f} c",
            f"{x1:.2f} {y1 - r:.2f} l",
            f"{x1:.2f} {y1 - r + k:.2f} {x1 - r + k:.2f} {y1:.2f} {x1 - r:.2f} {y1:.2f} c",
            f"{x + r:.2f} {y1:.2f} l",
            f"{x + r - k:.2f} {y1:.2f} {x:.2f} {y1 - r + k:.2f} {x:.2f} {y1 - r:.2f} c",
            f"{x:.2f} {y + r:.2f} l",
            f"{x:.2f} {y + r - k:.2f} {x + r - k:.2f} {y:.2f} {x + r:.2f} {y:.2f} c",
            "h",
        ]
    )


@dataclass
class _DrawOp:
    kind: str
    # rect
    x: float = 0
    y: float = 0
    w: float = 0
    h: float = 0
    radius: float = 0
    fill: str | None = None
    stroke: str | None = None
    stroke_w: float = 1.0
    # text
    text: str = ""
    size: float = 10
    bold: bool = False
    color: str = "#2c2c2e"


@dataclass
class _Page:
    ops: list[_DrawOp] = field(default_factory=list)


# UI colours (frontend/src/styles.css)
COL_BG = "#ffffff"
COL_USER_BG = "#2f6fed"
COL_USER_FG = "#ffffff"
COL_ASSIST_BG = "#f2f2f4"
COL_ASSIST_FG = "#2c2c2e"
COL_TOOL_BG = "#fafafb"
COL_TOOL_BORDER = "#e4e4e8"
COL_TOOL_FG = "#3a3a3e"
COL_TOOL_DONE_BORDER = "#d7e8d9"
COL_TOOL_ERR_BG = "#fff6f6"
COL_TOOL_ERR_BORDER = "#f0c9c9"
COL_TOOL_RUN_BG = "#f5f8fd"
COL_TOOL_RUN_BORDER = "#d8e2f5"
COL_TOOL_ROW_BG = "#ffffff"
COL_DANGER = "#c53434"
COL_MUTED = "#8a8a90"
COL_TITLE = "#1c1c1e"
COL_CARD_BG = "#fafafb"
COL_LINE = "#e4e4e8"
COL_SEP = "#000000"  # drawn at 5% opacity via light gray
COL_SEP_LINE = "#f0f0f2"


class ChatPdf:
    """Paginated chat transcript styled like the Discussion pane."""

    def __init__(self, font: _Font, *, bold: _Font | None = None):
        self.font = font
        self.bold = bold or font
        self.page_w = 595.0
        self.page_h = 842.0
        self.margin = 36.0
        self.content_w = self.page_w - 2 * self.margin
        self._pages: list[_Page] = [_Page()]
        self._y = self.page_h - self.margin
        # White page background
        self._pages[0].ops.append(
            _DrawOp(kind="rect", x=0, y=0, w=self.page_w, h=self.page_h, fill=COL_BG)
        )

    def _advance(self, font: _Font, cp: int, size: float) -> float:
        gid = font.cmap.get(cp) or font.cmap.get(ord("?")) or 0
        if gid >= len(font.advances):
            adv = font.units_per_em
        else:
            adv = font.advances[gid]
        return adv * size / font.units_per_em

    def text_width(self, text: str, size: float, bold: bool = False) -> float:
        font = self.bold if bold else self.font
        return sum(self._advance(font, ord(ch), size) for ch in text)

    def wrap(self, text: str, max_w: float, size: float, bold: bool = False) -> list[str]:
        font = self.bold if bold else self.font
        if not text:
            return [""]
        lines: list[str] = []
        for para in text.split("\n"):
            if not para:
                lines.append("")
                continue
            words = para.split(" ")
            cur = ""
            cur_w = 0.0
            space_w = self._advance(font, ord(" "), size)
            for word in words:
                ww = sum(self._advance(font, ord(ch), size) for ch in word)
                if cur and cur_w + space_w + ww > max_w:
                    lines.append(cur)
                    while ww > max_w and word:
                        chunk = ""
                        cw = 0.0
                        for i, ch in enumerate(word):
                            a = self._advance(font, ord(ch), size)
                            if chunk and cw + a > max_w:
                                lines.append(chunk)
                                word = word[i:]
                                ww = sum(self._advance(font, ord(c), size) for c in word)
                                break
                            chunk += ch
                            cw += a
                        else:
                            lines.append(chunk)
                            word = ""
                            ww = 0.0
                    cur = word
                    cur_w = ww
                else:
                    if cur:
                        cur += " "
                        cur_w += space_w
                    cur += word
                    cur_w += ww
            if cur or not words:
                lines.append(cur)
        return lines or [""]

    def _ensure(self, need: float) -> None:
        if self._y - need >= self.margin:
            return
        self._pages.append(_Page())
        self._pages[-1].ops.append(
            _DrawOp(kind="rect", x=0, y=0, w=self.page_w, h=self.page_h, fill=COL_BG)
        )
        self._y = self.page_h - self.margin

    def _emit(self, op: _DrawOp) -> None:
        self._pages[-1].ops.append(op)

    def add_header(self, title: str, subtitle: str = "") -> None:
        self._ensure(56)
        self._emit(
            _DrawOp(
                kind="text",
                x=self.margin,
                y=self._y - 16,
                text=title,
                size=18,
                bold=True,
                color=COL_TITLE,
            )
        )
        self._y -= 22
        if subtitle:
            self._emit(
                _DrawOp(
                    kind="text",
                    x=self.margin,
                    y=self._y - 11,
                    text=subtitle,
                    size=9,
                    color=COL_MUTED,
                )
            )
            self._y -= 16
        # accent underline like a soft header rule
        self._emit(
            _DrawOp(
                kind="rect",
                x=self.margin,
                y=self._y - 2,
                w=self.content_w,
                h=1,
                fill=COL_LINE,
            )
        )
        self._y -= 18

    def add_day(self, label: str) -> None:
        self._ensure(28)
        tw = self.text_width(label, 9)
        x = self.margin + (self.content_w - tw) / 2
        self._emit(
            _DrawOp(
                kind="text",
                x=x,
                y=self._y - 12,
                text=label,
                size=9,
                color=COL_MUTED,
            )
        )
        self._y -= 22

    def add_bubble(self, role: str, text: str, time: str = "") -> None:
        size = 10.5
        leading = size * 1.4
        pad_x, pad_y = 12.0, 10.0
        # ~90% width like the UI
        max_bubble = min(self.content_w * 0.9, 420.0)
        time_w = 36.0 if time else 0.0
        gap = 8.0 if time else 0.0
        inner_w = max_bubble - 2 * pad_x
        lines = self.wrap(text, inner_w, size)
        text_h = max(leading, len(lines) * leading)
        bubble_h = text_h + 2 * pad_y
        bubble_w = min(
            max_bubble,
            max((self.text_width(ln, size) for ln in lines), default=40) + 2 * pad_x,
        )
        bubble_w = max(bubble_w, 56.0)
        need = bubble_h + 14
        self._ensure(need)

        user = role == "user"
        # Layout: [time][bubble] for user (right), [bubble][time] for assistant (left)
        if user:
            bx = self.margin + self.content_w - bubble_w
            if time:
                tx = bx - gap - time_w
            bg, fg = COL_USER_BG, COL_USER_FG
            # sharper bottom-right like CSS border-bottom-right-radius: 6px
            radius_note = "user"
        else:
            bx = self.margin
            if time:
                tx = bx + bubble_w + gap
            bg, fg = COL_ASSIST_BG, COL_ASSIST_FG
            radius_note = "assistant"

        by = self._y - bubble_h
        # Custom radii: 18px all around, 6px on the "tail" corner
        r = 14.0
        self._emit(
            _DrawOp(
                kind="bubble",
                x=bx,
                y=by,
                w=bubble_w,
                h=bubble_h,
                radius=r,
                fill=bg,
                text=radius_note,
            )
        )
        ty = by + bubble_h - pad_y - size
        for ln in lines:
            self._emit(
                _DrawOp(
                    kind="text",
                    x=bx + pad_x,
                    y=ty,
                    text=ln,
                    size=size,
                    color=fg,
                )
            )
            ty -= leading
        if time:
            self._emit(
                _DrawOp(
                    kind="text",
                    x=tx if user else tx,
                    y=by + bubble_h / 2 - 3,
                    text=time,
                    size=7.5,
                    color=COL_MUTED,
                )
            )
        self._y = by - 12

    def add_tools(
        self,
        title: str,
        badge: str,
        rows: list[dict],
        *,
        time: str = "",
        tone: str = "done",
    ) -> None:
        """Mirror ``.tool-group``: summary (⚙ title badge time) + expanded row heads only."""
        # ~520px chat card → ~390pt
        card_w = min(self.content_w * 0.92, 390.0)
        pad_x = 12.0
        summary_h = 28.0
        row_h = 26.0
        list_pad_top = 6.0
        list_pad_bot = 8.0
        list_gap = 3.0
        n_rows = len(rows)
        list_h = (
            (list_pad_top + list_pad_bot + n_rows * row_h + max(0, n_rows - 1) * list_gap)
            if n_rows
            else 0.0
        )
        card_h = summary_h + (1.0 if n_rows else 0.0) + list_h
        self._ensure(card_h + 16)

        if tone == "error":
            fill, stroke = COL_TOOL_ERR_BG, COL_TOOL_ERR_BORDER
        elif tone == "running":
            fill, stroke = COL_TOOL_RUN_BG, COL_TOOL_RUN_BORDER
        else:
            fill, stroke = COL_TOOL_BG, COL_TOOL_DONE_BORDER

        cx = self.margin + (self.content_w - card_w) / 2
        cy = self._y - card_h
        self._emit(
            _DrawOp(
                kind="rect",
                x=cx,
                y=cy,
                w=card_w,
                h=card_h,
                radius=14,
                fill=fill,
                stroke=stroke,
                stroke_w=1.0,
            )
        )

        # —— summary row (like .tool-group-summary) ——
        sy = cy + card_h - 18
        ico = "⚙"
        self._emit(
            _DrawOp(
                kind="text",
                x=cx + pad_x,
                y=sy,
                text=ico,
                size=11,
                color=COL_TOOL_FG,
            )
        )
        title_x = cx + pad_x + 18
        self._emit(
            _DrawOp(
                kind="text",
                x=title_x,
                y=sy,
                text=title,
                size=10.5,
                bold=True,
                color=COL_TOOL_FG,
            )
        )
        # time flush right, badge just before it
        right = cx + card_w - pad_x
        if time:
            tw = self.text_width(time, 8)
            right -= tw
            self._emit(
                _DrawOp(
                    kind="text",
                    x=right,
                    y=sy,
                    text=time,
                    size=8,
                    color=COL_MUTED,
                )
            )
            right -= 8
        if badge:
            badge_u = badge.upper()
            bw = self.text_width(badge_u, 8)
            right -= bw
            self._emit(
                _DrawOp(
                    kind="text",
                    x=right,
                    y=sy,
                    text=badge_u,
                    size=8,
                    color=COL_DANGER if tone == "error" else COL_MUTED,
                )
            )

        # —— separator + list (like .tool-group-list open) ——
        if n_rows:
            sep_y = cy + card_h - summary_h
            self._emit(
                _DrawOp(
                    kind="rect",
                    x=cx + 6,
                    y=sep_y - 0.5,
                    w=card_w - 12,
                    h=0.7,
                    fill=COL_SEP_LINE,
                )
            )
            ry = sep_y - list_pad_top - row_h
            inner_x = cx + 8
            inner_w = card_w - 16
            for row in rows:
                # row pill
                self._emit(
                    _DrawOp(
                        kind="rect",
                        x=inner_x,
                        y=ry,
                        w=inner_w,
                        h=row_h,
                        radius=8,
                        fill=COL_TOOL_ROW_BG,
                    )
                )
                name = str(row.get("name") or "")
                st = str(row.get("status") or "").upper()
                rt = str(row.get("time") or "")
                err = str(row.get("state") or "") == "error"
                text_y = ry + 8
                self._emit(
                    _DrawOp(
                        kind="text",
                        x=inner_x + 8,
                        y=text_y,
                        text=name,
                        size=10,
                        bold=True,
                        color=COL_TITLE,
                    )
                )
                cursor = inner_x + inner_w - 8
                if rt:
                    rtw = self.text_width(rt, 8)
                    cursor -= rtw
                    self._emit(
                        _DrawOp(
                            kind="text",
                            x=cursor,
                            y=text_y,
                            text=rt,
                            size=8,
                            color=COL_MUTED,
                        )
                    )
                    cursor -= 8
                if st:
                    stw = self.text_width(st, 8)
                    cursor -= stw
                    self._emit(
                        _DrawOp(
                            kind="text",
                            x=cursor,
                            y=text_y,
                            text=st,
                            size=8,
                            color=COL_DANGER if err else COL_MUTED,
                        )
                    )
                ry -= row_h + list_gap

        self._y = cy - 12

    def add_card(self, label: str) -> None:
        size = 9.5
        pad_x, pad_y = 12.0, 10.0
        card_w = min(self.content_w * 0.85, 380.0)
        tw = self.text_width(label, size, bold=True)
        card_h = size + 2 * pad_y
        self._ensure(card_h + 14)
        cx = self.margin + (self.content_w - card_w) / 2
        cy = self._y - card_h
        self._emit(
            _DrawOp(
                kind="rect",
                x=cx,
                y=cy,
                w=card_w,
                h=card_h,
                radius=12,
                fill=COL_CARD_BG,
                stroke=COL_LINE,
                stroke_w=1.0,
            )
        )
        self._emit(
            _DrawOp(
                kind="text",
                x=cx + (card_w - tw) / 2,
                y=cy + pad_y,
                text=label,
                size=size,
                bold=True,
                color=COL_TOOL_FG,
            )
        )
        self._y = cy - 12

    def _encode(self, text: str, font: _Font, used: dict[int, int]) -> bytes:
        out = bytearray()
        for ch in text:
            cp = ord(ch)
            gid = font.cmap.get(cp)
            if gid is None:
                gid = font.cmap.get(ord("?")) or 0
                cp = ord("?")
            used[cp] = gid
            out.extend(struct.pack(">H", gid))
        return bytes(out)

    def _ops_to_stream(
        self, ops: list[_DrawOp], used_reg: dict[int, int], used_bold: dict[int, int]
    ) -> bytes:
        parts: list[str] = []
        for op in ops:
            if op.kind in ("rect", "bubble"):
                if op.fill:
                    r, g, b = _rgb(op.fill)
                    parts.append(f"{r:.3f} {g:.3f} {b:.3f} rg")
                if op.stroke:
                    r, g, b = _rgb(op.stroke)
                    parts.append(f"{r:.3f} {g:.3f} {b:.3f} RG")
                    parts.append(f"{op.stroke_w:.2f} w")
                # Tail corner: slightly sharper on one side via smaller radius overall
                rad = op.radius
                if op.kind == "bubble" and op.text == "user":
                    # draw as rounded rect (uniform) — close enough to CSS
                    pass
                parts.append(_round_rect_path(op.x, op.y, op.w, op.h, rad))
                if op.fill and op.stroke:
                    parts.append("B")
                elif op.fill:
                    parts.append("f")
                else:
                    parts.append("S")
            elif op.kind == "text":
                font = self.bold if op.bold else self.font
                used = used_bold if op.bold else used_reg
                enc = self._encode(op.text, font, used)
                r, g, b = _rgb(op.color)
                tag = "/F2" if op.bold else "/F1"
                parts.append("BT")
                parts.append(f"{r:.3f} {g:.3f} {b:.3f} rg")
                parts.append(f"1 0 0 1 {op.x:.2f} {op.y:.2f} Tm")
                parts.append(f"{tag} {op.size:.2f} Tf")
                parts.append(f"<{enc.hex().upper()}> Tj")
                parts.append("ET")
        return ("\n".join(parts) + "\n").encode("ascii")

    def build(self) -> bytes:
        used_reg: dict[int, int] = {}
        used_bold: dict[int, int] = {}
        # Pre-encode to collect glyph usage
        streams = [
            self._ops_to_stream(p.ops, used_reg, used_bold) for p in self._pages
        ]

        objects: list[bytes | None] = [None]

        def add_obj(body: bytes) -> int:
            objects.append(body)
            return len(objects) - 1

        def font_bundle(font: _Font, used: dict[int, int], base: str) -> int:
            if not used:
                used[ord(" ")] = font.cmap.get(ord(" ")) or 0
            ff = add_obj(
                b"<< /Length "
                + str(len(font.data)).encode()
                + b" /Length1 "
                + str(len(font.data)).encode()
                + b" >>\nstream\n"
                + font.data
                + b"\nendstream"
            )
            bbox = " ".join(str(x) for x in font.bbox)
            desc = add_obj(
                (
                    f"<< /Type /FontDescriptor /FontName /{_pdf_escape_name(base)} "
                    f"/Flags 32 /FontBBox [{bbox}] /ItalicAngle 0 "
                    f"/Ascent {font.ascent} /Descent {font.descent} "
                    f"/CapHeight {font.ascent} /StemV 80 /FontFile2 {ff} 0 R >>"
                ).encode("ascii")
            )
            w_parts = []
            for gid in sorted(set(used.values())):
                adv = font.advances[gid] if gid < len(font.advances) else font.units_per_em
                w = int(round(adv * 1000 / font.units_per_em))
                w_parts.append(f"{gid} [{w}]")
            w_arr = " ".join(w_parts) if w_parts else "0 [600]"
            cid = add_obj(
                (
                    f"<< /Type /Font /Subtype /CIDFontType2 "
                    f"/BaseFont /{_pdf_escape_name(base)} "
                    f"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
                    f"/FontDescriptor {desc} 0 R /DW 600 /W [{w_arr}] "
                    f"/CIDToGIDMap /Identity >>"
                ).encode("ascii")
            )
            touni_data = _to_unicode_cmap(used)
            touni = add_obj(
                b"<< /Length "
                + str(len(touni_data)).encode()
                + b" >>\nstream\n"
                + touni_data
                + b"\nendstream"
            )
            return add_obj(
                (
                    f"<< /Type /Font /Subtype /Type0 /BaseFont /{_pdf_escape_name(base)} "
                    f"/Encoding /Identity-H /DescendantFonts [{cid} 0 R] "
                    f"/ToUnicode {touni} 0 R >>"
                ).encode("ascii")
            )

        f1 = font_bundle(self.font, used_reg, self.font.name)
        f2 = font_bundle(self.bold, used_bold, self.bold.name)

        page_ids = []
        for stream in streams:
            cid = add_obj(
                b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
            )
            pid = add_obj(
                (
                    f"<< /Type /Page /Parent PAGES /MediaBox [0 0 {self.page_w:.0f} {self.page_h:.0f}] "
                    f"/Contents {cid} 0 R "
                    f"/Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> >> >>"
                ).encode("ascii")
            )
            page_ids.append(pid)

        kids = " ".join(f"{p} 0 R" for p in page_ids)
        pages_id = add_obj(
            f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")
        )
        for pid in page_ids:
            objects[pid] = objects[pid].replace(
                b"/Parent PAGES", f"/Parent {pages_id} 0 R".encode()
            )
        catalog_id = add_obj(
            f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii")
        )

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for i in range(1, len(objects)):
            offsets.append(len(out))
            out.extend(f"{i} 0 obj\n".encode("ascii"))
            out.extend(objects[i])
            out.extend(b"\nendobj\n")
        xref_pos = len(out)
        out.extend(f"xref\n0 {len(objects)}\n".encode("ascii"))
        out.extend(b"0000000000 65535 f \n")
        for i in range(1, len(objects)):
            out.extend(f"{offsets[i]:010d} 00000 n \n".encode("ascii"))
        out.extend(
            (
                f"trailer\n<< /Size {len(objects)} /Root {catalog_id} 0 R >>\n"
                f"startxref\n{xref_pos}\n%%EOF\n"
            ).encode("ascii")
        )
        return bytes(out)


_FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"


def load_default_fonts() -> tuple[_Font, _Font]:
    regular = _FONT_DIR / "DejaVuSans.ttf"
    bold = _FONT_DIR / "DejaVuSans-Bold.ttf"
    if not regular.is_file():
        raise FileNotFoundError(f"PDF font missing: {regular}")
    reg = _load_ttf(regular, "DejaVuSans")
    bld = _load_ttf(bold, "DejaVuSans-Bold") if bold.is_file() else reg
    return reg, bld


def build_discussion_pdf(
    *,
    title: str,
    subtitle: str,
    blocks: list[dict],
) -> bytes:
    """blocks: day | bubble | tools | card dicts."""
    reg, bold = load_default_fonts()
    pdf = ChatPdf(reg, bold=bold)
    pdf.add_header(title, subtitle)
    for b in blocks:
        kind = b.get("kind")
        if kind == "day":
            pdf.add_day(b.get("label") or "")
        elif kind == "bubble":
            pdf.add_bubble(
                b.get("role") or "assistant",
                b.get("text") or "",
                time=b.get("time") or "",
            )
        elif kind == "tools":
            pdf.add_tools(
                b.get("title") or "Outils",
                b.get("badge") or "",
                list(b.get("rows") or []),
                time=b.get("time") or "",
                tone=str(b.get("tone") or "done"),
            )
        elif kind == "card":
            pdf.add_card(b.get("label") or "")
    return pdf.build()


# Back-compat for older callers / tests
def build_text_pdf(lines: list[tuple[str, dict]], *, title: str = "") -> bytes:
    blocks: list[dict] = []
    buf: list[str] = []
    role = "assistant"

    def flush() -> None:
        nonlocal buf
        if buf:
            blocks.append({"kind": "bubble", "role": role, "text": "\n".join(buf)})
            buf = []

    for text, opts in lines:
        if opts.get("blank"):
            flush()
            continue
        if opts.get("bold") and not buf:
            # treat bold lines as start of a bubble labelled in text
            flush()
            buf.append(text)
            continue
        buf.append(text)
    flush()
    return build_discussion_pdf(title=title or "Discussion", subtitle="", blocks=blocks)
