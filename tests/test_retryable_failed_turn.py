"""Server auto-retry selects recoverable failures, not user stops."""

from __future__ import annotations

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


def test_prompt_ack_timeout_is_generous():
    import inspect

    from autonomous.services.pi_rpc import PiRpcSession

    src = inspect.getsource(PiRpcSession.prompt)
    assert "timeout=300" in src or "timeout: float = 300" in src
