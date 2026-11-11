"""Server auto-retry selects recoverable failures, not user stops."""

from __future__ import annotations

import threading
import time

from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc


def test_retryable_after_rpc_timeout(home):
    bots_svc.create_bot("to", home=home)
    chat_svc.create_message("to", "Fais X", role="user", home=home)
    chat_svc.create_message(
        "to",
        "⚠️ Pi RPC timeout on prompt",
        role="assistant",
        meta={"error": "Pi RPC timeout on prompt"},
        home=home,
    )
    assert chat_svc.retryable_failed_turn("to", home=home) is not None


def test_not_retryable_after_user_stop(home):
    bots_svc.create_bot("st", home=home)
    chat_svc.create_message("st", "Fais X", role="user", home=home)
    chat_svc.create_message(
        "st",
        "⏹ Stopped.",
        role="assistant",
        meta={"aborted": True},
        home=home,
    )
    assert chat_svc.retryable_failed_turn("st", home=home) is None


def test_silent_busy_retries_idle_timeout(home, monkeypatch):
    from autonomous.services import agent as agent_svc

    with agent_svc._PROGRESS_LOCK:
        agent_svc._LAST_PROGRESS.clear()
        agent_svc._LAST_SILENT_RETRY.clear()
    with agent_svc._ACTIVE_LOCK:
        agent_svc._ACTIVE_RUNS.clear()

    bots_svc.create_bot("idleto", home=home)
    chat_svc.create_message("idleto", "Continue", role="user", home=home)
    chat_svc.create_message(
        "idleto",
        "⚠️ Pi RPC timeout on prompt",
        role="assistant",
        meta={"error": "Pi RPC timeout on prompt"},
        home=home,
    )
    called: list[str] = []
    monkeypatch.setattr(
        chat_svc,
        "retry_unprocessed",
        lambda bot, *, home=None: called.append(bot)
        or {"ok": True, "action": "resumed"},
    )
    assert agent_svc.recover_silent_busy_runs(home=home, grace_sec=0.0) == [
        "idleto"
    ]
    assert called == ["idleto"]


def test_prompt_ack_has_no_deadline():
    import inspect

    from autonomous.services.pi_rpc import PiRpcSession

    timeout = inspect.signature(PiRpcSession.prompt).parameters["timeout"]
    assert timeout.default is None

    session = PiRpcSession.__new__(PiRpcSession)
    seen: dict = {}

    def request(command_type, timeout=30.0, **fields):
        seen["type"] = command_type
        seen["timeout"] = timeout
        seen["message"] = fields.get("message")
        return {"success": True}

    session.request = request  # type: ignore[method-assign]
    out = session.prompt("fais un outil")
    assert out["success"] is True
    assert seen == {
        "type": "prompt",
        "timeout": None,
        "message": "fais un outil",
    }


def test_turn_open_when_tools_follow_assistant(home):
    bots_svc.create_bot("mid", home=home)
    chat_svc.create_message("mid", "Continue", role="user", home=home)
    chat_svc.create_message("mid", "Je relance la recherche.", role="assistant", home=home)
    chat_svc.create_message(
        "mid",
        "status: error\n---\nOutil interrompu (relance).",
        role="event",
        meta={
            "kind": "tool",
            "tool_name": "vm_terminal_exec",
            "status": "error",
            "error": "Outil interrompu (relance).",
        },
        home=home,
    )
    assert chat_svc.turn_ended_on_tool("mid", home=home) is not None
    assert chat_svc.unfinished_user_turn("mid", home=home) is not None


def test_silent_busy_does_not_stop_live_pi_on_a_long_tool(home, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from autonomous.db import get_db
    from autonomous.services import agent as agent_svc

    with agent_svc._PROGRESS_LOCK:
        agent_svc._LAST_PROGRESS.clear()
        agent_svc._LAST_SILENT_RETRY.clear()
    with agent_svc._ACTIVE_LOCK:
        agent_svc._ACTIVE_RUNS.clear()

    bots_svc.create_bot("long", home=home)
    bots_svc.patch_bot("long", {"status": "busy"}, home=home)
    settled = threading.Event()
    assert agent_svc._register_run("long", settled)
    msg = chat_svc.create_message(
        "long",
        "status: running",
        role="event",
        meta={
            "kind": "tool",
            "tool_name": "vm_terminal_exec",
            "status": "running",
            "args": {"timeout": 5},
        },
        home=home,
    )
    # Command timeout already passed. That must not make the watchdog stop Pi.
    old = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    with get_db(home) as conn:
        conn.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            (old, msg["id"]),
        )
    with agent_svc._PROGRESS_LOCK:
        agent_svc._LAST_PROGRESS["long"] = time.monotonic() - 120.0
    called: list[str] = []
    monkeypatch.setattr(
        chat_svc,
        "retry_unprocessed",
        lambda *a, **k: called.append("x") or {"ok": True, "action": "noop"},
    )
    assert agent_svc.recover_silent_busy_runs(home=home, grace_sec=30.0) == []
    assert called == []
    settled.set()
    agent_svc.clear_active_run("long")
