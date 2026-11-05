"""Grounding parsers / image helpers (no network)."""

from __future__ import annotations

from autonomous.services.grounding_image import (
    draw_hollow_cross,
    fit_size,
    png_bytes,
    read_png,
    resize_nn,
    write_png,
)
from autonomous.services.grounding_parse import parse_action


def test_parse_click():
    p = parse_action("click(start_box='(1160,736)')")
    assert p == {"action": "click", "x": 1160, "y": 736}


def test_parse_drag():
    p = parse_action("drag(start_box='(10,20)', end_box='(30,40)')")
    assert p["action"] == "drag"
    assert (p["x"], p["y"], p["x2"], p["y2"]) == (10, 20, 30, 40)


def test_parse_finished():
    assert parse_action("finished()").get("action") == "finished"


def test_fit_and_resize_roundtrip(tmp_path):
    w, h = 128, 64
    rgb = bytearray([0, 0, 0] * (w * h))
    # white pixel at (10, 5)
    i = (5 * w + 10) * 3
    rgb[i : i + 3] = bytes([255, 255, 255])
    path = tmp_path / "t.png"
    write_png(path, w, h, rgb)
    rw, rh, rrgb = read_png(path)
    assert (rw, rh) == (w, h)
    assert rrgb[i : i + 3] == bytearray([255, 255, 255])
    nw, nh = fit_size(1280, 720, max_side=560, multiple=28)
    assert nw % 28 == 0 and nh % 28 == 0
    out = resize_nn(w, h, rgb, nw, nh)
    assert len(out) == nw * nh * 3
    marked = draw_hollow_cross(w, h, rgb, 10, 5)
    assert len(marked) == len(rgb)
    assert len(png_bytes(w, h, marked)) > 100
