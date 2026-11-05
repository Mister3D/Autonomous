"""Pointer tool meta (click/drag) preserved for chat overlays."""

from __future__ import annotations

from autonomous.services.agent import _pointer_fields, _screenshot_fields


def test_pointer_from_args_click():
    meta = _pointer_fields("vm_click", {"x": 10.2, "y": 20.8, "button": "left"}, "", None)
    assert meta["pointer"] is True
    assert meta["pointer_kind"] == "vm_click"
    assert meta["x"] == 10
    assert meta["y"] == 21
    assert meta["button"] == "left"


def test_pointer_from_result_text_when_args_empty():
    meta = _pointer_fields(
        "vm_drag",
        {},
        "Dragged (851,559) → (1073,559).",
        None,
    )
    assert meta["x"] == 851
    assert meta["y"] == 559
    assert meta["x2"] == 1073
    assert meta["y2"] == 559


def test_pointer_prefers_details_then_fills_from_text():
    meta = _pointer_fields(
        "vm_click",
        {},
        "Clicked right at (960,531).",
        {"ok": True},
    )
    assert meta["x"] == 960
    assert meta["y"] == 531
    assert meta["button"] == "right"


def test_non_pointer_tool_empty():
    assert _pointer_fields("bash", {"command": "ls"}, "ok", None) == {}


def test_scroll_from_text():
    meta = _pointer_fields("vm_scroll", {}, "Scrolled dy=400 at (100,200).", None)
    assert meta["dy"] == 400
    assert meta["x"] == 100
    assert meta["y"] == 200


def test_screenshot_fields_from_details():
    meta = _screenshot_fields(
        "vm_screenshot",
        "",
        {
            "screenshot_id": "abc-123",
            "url": "/api/v1/bots/x/screen/screenshots/abc-123.png",
        },
    )
    assert meta["screenshot_id"] == "abc-123"
    assert meta["screenshot_url"].endswith("abc-123.png")


def test_screenshot_fields_from_result_text():
    meta = _screenshot_fields(
        "vm_screenshot",
        "Screenshot captured 1920×1200.\nid: deadbeef-01\nurl: /api/v1/bots/b/screen/screenshots/deadbeef-01.png\n",
        None,
    )
    assert meta["screenshot_id"] == "deadbeef-01"
    assert "deadbeef-01.png" in meta["screenshot_url"]


def test_screenshot_fields_skip_other_tools():
    assert _screenshot_fields("bash", "id: nope", {"screenshot_id": "x"}) == {}
