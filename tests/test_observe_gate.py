"""Snapshot points answer a ground; vision stays for an empty read."""

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


def test_drag_hint_is_not_shortcut():
    gate.remember_browser_read(
        "b1",
        {"elements": [_button("Glisser", 300, 400)]},
    )
    assert gate.shortcut_ground("b1", "slider handle", action_hint="drag") is None
