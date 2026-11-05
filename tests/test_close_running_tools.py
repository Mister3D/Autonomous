"""Orphan tool cards must not stay on status=running forever."""

from __future__ import annotations

from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc


def test_close_running_tools_marks_error(home):
    bots_svc.create_bot("stuck", home=home)
    running = chat_svc.create_message(
        "stuck",
        "🔧 vm_ground\nstatus: running\n{}",
        role="event",
        meta={
            "kind": "tool",
            "status": "running",
            "tool_name": "vm_ground",
            "tool_call_id": "call-1",
        },
        home=home,
    )
    done = chat_svc.create_message(
        "stuck",
        "🔧 vm_screenshot\nstatus: done",
        role="event",
        meta={"kind": "tool", "status": "done", "tool_name": "vm_screenshot"},
        home=home,
    )

    n = chat_svc.close_running_tools(
        "stuck",
        error="Outil interrompu (run terminé sans résultat).",
        home=home,
    )
    assert n == 1

    by_id = {m["id"]: m for m in chat_svc.list_messages("stuck", home=home)}
    updated = by_id[running["id"]]
    meta = updated["meta"]
    assert meta["status"] == "error"
    assert "interrompu" in (meta.get("error") or "")
    assert "status: error" in updated["content"]
    assert "Reprendre" not in updated["content"]

    still = by_id[done["id"]]
    assert still["meta"]["status"] == "done"


def test_deep_running_card_is_closed(home):
    """A stuck card buried under many grounding notes must still be swept."""
    bots_svc.create_bot("deep", home=home)
    stuck = chat_svc.create_message(
        "deep",
        "🔧 vm_ground\nstatus: running\n{}",
        role="event",
        meta={"kind": "tool", "status": "running", "tool_name": "vm_ground"},
        home=home,
    )
    for i in range(150):
        chat_svc.create_message(
            "deep", f"Grounding · note {i}", role="event", meta={"kind": "grounding"}, home=home
        )
    assert chat_svc.close_running_tools("deep", error="x", home=home) == 1
    by_id = {m["id"]: m for m in chat_svc.list_messages("deep", limit=400, home=home)}
    assert by_id[stuck["id"]]["meta"]["status"] == "error"


def test_late_tool_start_after_stop_is_swept(home):
    """Pi event read just after stop_run's sweep must not stay on « En cours »."""
    import time

    from autonomous.services import agent as agent_svc

    bots_svc.create_bot("late", home=home)
    agent_svc._sweep_tools_later("late", home=home)
    late = chat_svc.create_message(
        "late",
        "🔧 vault_type\nstatus: running\n{}",
        role="event",
        meta={"kind": "tool", "status": "running", "tool_name": "vault_type"},
        home=home,
    )
    deadline = time.time() + 5
    status = "running"
    while time.time() < deadline and status == "running":
        time.sleep(0.3)
        by_id = {m["id"]: m for m in chat_svc.list_messages("late", home=home)}
        status = by_id[late["id"]]["meta"]["status"]
    assert status == "error"
