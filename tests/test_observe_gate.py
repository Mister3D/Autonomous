"""vm_look is allowed without a prior DOM read."""

from __future__ import annotations

from autonomous.services import observe_gate as gate


def setup_function(_fn=None):
    gate.reset_for_tests()


def test_look_allowed_with_no_dom_observe():
    assert gate.refuse_vm_look_message("b1") is None


def test_look_allowed_back_to_back():
    gate.mark_dom_observe("b1")
    gate.note_vm_look("b1")
    assert gate.refuse_vm_look_message("b1") is None
    gate.note_vm_look("b1")
    assert gate.refuse_vm_look_message("b1") is None
