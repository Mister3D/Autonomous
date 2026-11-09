"""DOM-before-eyes gate for vm_look / screen describe."""

from __future__ import annotations

from autonomous.services import observe_gate as gate


def setup_function(_fn=None):
    gate.reset_for_tests()


def test_refuse_when_screen_desk_up_and_no_dom_observe(monkeypatch):
    monkeypatch.setattr(gate, "_screen_desk_up", lambda bot, home=None: True)
    msg = gate.refuse_vm_look_message("b1")
    assert msg and "browser_snapshot" in msg


def test_allow_when_no_screen_desk_without_dom(monkeypatch):
    monkeypatch.setattr(gate, "_screen_desk_up", lambda bot, home=None: False)
    assert gate.refuse_vm_look_message("b1") is None


def test_allow_after_dom_then_refuse_back_to_back(monkeypatch):
    monkeypatch.setattr(gate, "_screen_desk_up", lambda bot, home=None: True)
    gate.mark_dom_observe("b1")
    assert gate.refuse_vm_look_message("b1") is None
    gate.note_vm_look("b1")
    msg = gate.refuse_vm_look_message("b1")
    assert msg and "back-to-back" in msg
    gate.mark_dom_observe("b1")
    assert gate.refuse_vm_look_message("b1") is None


def test_describe_screen_soft_refuse(home, monkeypatch):
    from autonomous.services import bots as bots_svc
    from autonomous.services import grounding as ground_svc

    bots_svc.create_bot("lookgate", home=home)
    monkeypatch.setattr(
        "autonomous.services.observe_gate._screen_desk_up",
        lambda bot, home=None: True,
    )
    gate.reset_for_tests()
    out = ground_svc.describe_screen("lookgate", home=home)
    assert out["ok"] is False
    assert out.get("code") == "dom_observe_required"
    assert "browser_snapshot" in (out.get("text") or "")
