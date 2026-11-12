"""Snapshot points answer a ground; a gesture can carry the next page."""

from __future__ import annotations

from autonomous.services import observe_gate as gate


def setup_function(_fn=None):
    gate.reset_for_tests()


def _button(text: str, x: int, y: int, **extra):
    el = {"tag": "button", "text": text, "screen": {"x": x, "y": y}, "in_viewport": True}
    el.update(extra)
    return el


def test_look_allowed_before_any_snapshot():
    assert gate.refuse_vm_look_message("b1") is None


def test_look_refused_when_snapshot_lists_controls():
    gate.remember_browser_read(
        "b1",
        {"elements": [_button("Connexion", 400, 300)]},
    )
    message = gate.refuse_vm_look_message("b1")
    assert message is not None
    assert "400,300" in message


def test_look_allowed_when_snapshot_is_empty():
    gate.remember_browser_read("b1", {"elements": []})
    assert gate.refuse_vm_look_message("b1") is None


def test_ground_asks_for_a_snapshot_first():
    early = gate.shortcut_ground("b1", "Connexion button")
    assert early is not None
    assert early["ok"] is False
    assert early["status"] == "no_snapshot"


def test_ground_returns_the_snapshot_point():
    gate.remember_browser_read(
        "b1",
        {"elements": [_button("Connexion", 410, 220), _button("Panier", 800, 40)]},
    )
    early = gate.shortcut_ground("b1", "Connexion button")
    assert early["ok"] is True
    assert early["source"] == "snapshot"
    assert (early["x"], early["y"]) == (410, 220)


def test_ground_after_a_click_is_stale():
    gate.remember_browser_read(
        "b1",
        {"elements": [_button("Connexion", 410, 220)]},
    )
    gate.note_gesture("b1")
    early = gate.shortcut_ground("b1", "Connexion button")
    assert early["status"] == "stale"
    assert early["ok"] is False


def test_overlay_is_listed_instead_of_the_page_button():
    gate.remember_browser_read(
        "b1",
        {
            "elements": [_button("Connexion", 410, 220)],
            "overlays": [
                {
                    "controls": [
                        {"tag": "button", "text": "Tout accepter", "screen": {"x": 700, "y": 500}},
                    ]
                }
            ],
        },
    )
    early = gate.shortcut_ground("b1", "Connexion button")
    assert early["ok"] is False
    assert early["status"] == "overlay"
    assert "700,500" in early["error"]


def test_password_field_is_the_only_password_input():
    gate.remember_browser_read(
        "b1",
        {
            "elements": [
                {"tag": "input", "type": "email", "name": "email", "text": "", "screen": {"x": 100, "y": 200}, "in_viewport": True},
                {"tag": "input", "type": "password", "name": "password", "text": "", "screen": {"x": 100, "y": 260}, "in_viewport": True},
            ]
        },
    )
    early = gate.shortcut_ground("b1", "password field")
    assert early["ok"] is True
    assert (early["x"], early["y"]) == (100, 260)


def test_page_did_change_skips_a_focus_click():
    from autonomous.services.browser import page_did_change

    same = {"url": "https://shop.example/", "title": "Shop", "ready": "complete"}
    assert page_did_change(same, dict(same)) is False
    assert page_did_change(same, {**same, "url": "https://shop.example/orders"}) is True
    assert page_did_change(same, {**same, "title": "Orders"}) is True
    assert page_did_change(same, {**same, "ready": "loading"}) is True
    assert page_did_change({}, same) is True
    assert page_did_change(same, {}) is True


def test_format_page_read_includes_the_point_and_the_text():
    from autonomous.services.browser import format_page_read

    text = format_page_read(
        {
            "ok": True,
            "url": "https://shop.example/",
            "title": "Shop",
            "elements": [
                {
                    "tag": "a",
                    "text": "Orders",
                    "in_viewport": True,
                    "screen": {"x": 10, "y": 20},
                }
            ],
            "text": "Total 12,00",
        }
    )
    assert "screen=10,20" in text
    assert "Total 12,00" in text
    assert "answer now" in text
    assert "browser_text" in text


def test_drag_hint_is_not_shortcut():
    gate.remember_browser_read(
        "b1",
        {"elements": [_button("Glisser", 300, 400)]},
    )
    assert gate.shortcut_ground("b1", "slider handle", action_hint="drag") is None
