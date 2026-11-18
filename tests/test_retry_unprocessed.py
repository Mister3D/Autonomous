"""Retry unfinished work after LLM outage without wiping chat / Pi session."""

from __future__ import annotations

from autonomous.services import approvals as approval_svc
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services.errors import Conflict


def test_retry_drains_queued_without_new_user_bubble(home, monkeypatch):
    bots_svc.create_bot("retry-q", home=home)
    bots_svc.patch_bot("retry-q", {"status": "busy"}, home=home)
    chat_svc.create_message(
        "retry-q",
        "Webhook déclenché",
        role="user",
        meta={"kind": "webhook", "queued": True, "agent_prompt": "confirm payload"},
        home=home,
    )
    started: list[str] = []

    def fake_start(bot, content, attachments, *, home=None, message_id=None):
        started.append(content)
        return ""

    monkeypatch.setattr(
        "autonomous.services.chat._start_agent_for_user_message",
        fake_start,
    )

    out = chat_svc.retry_unprocessed("retry-q", home=home)
    assert out["ok"] is True
    assert out["action"] == "drained"
    assert started == ["confirm payload"]
    assert bots_svc.get_bot("retry-q", home=home)["status"] == "idle"
    users = [
        m
        for m in chat_svc.list_messages("retry-q", home=home)
        if m["role"] == "user"
    ]
    assert len(users) == 1
    assert not (users[0].get("meta") or {}).get("queued")


def test_retry_resumes_failed_turn_same_session(home, monkeypatch):
    bot = bots_svc.create_bot("retry-f", home=home)
    session = bot["pi_session_id"]
    chat_svc.create_message("retry-f", "Fais X", role="user", home=home)
    chat_svc.create_message(
        "retry-f",
        "⚠️ provider unavailable",
        role="assistant",
        meta={"error": "provider unavailable"},
        home=home,
    )
    prompts: list[str] = []

    class FakeAgent:
        def start_run(self, name, message, *, home=None, images=None):
            prompts.append(message)
            return ""

        def stop_run(self, name, *, home=None):
            return None

    monkeypatch.setattr(
        "autonomous.services.agent.get_agent",
        lambda *a, **k: FakeAgent(),
    )

    out = chat_svc.retry_unprocessed("retry-f", home=home)
    assert out["action"] == "resumed"
    assert prompts and "Original task" in prompts[0]
    assert "Fais X" in prompts[0]
    assert bots_svc.get_bot("retry-f", home=home)["pi_session_id"] == session


def test_retry_refuses_real_human_wait(home):
    bots_svc.create_bot("retry-w", home=home)
    approval_svc.create_request(
        "retry-w", prompt="OK?", title="Check", home=home
    )
    assert bots_svc.get_bot("retry-w", home=home)["status"] == "waiting"
    try:
        chat_svc.retry_unprocessed("retry-w", home=home)
        assert False, "expected Conflict"
    except Conflict as exc:
        assert exc.code == "waiting_for_user"


def test_retry_does_not_cut_a_live_pi(home, monkeypatch):
    import threading

    from autonomous.services import agent as agent_svc
    from autonomous.services.pi_rpc import MANAGER

    bots_svc.create_bot("retry-live", home=home)
    bots_svc.patch_bot("retry-live", {"status": "busy"}, home=home)
    settled = threading.Event()
    assert agent_svc._register_run("retry-live", settled)
    stopped: list[str] = []
    monkeypatch.setattr(MANAGER, "abort", lambda *a, **k: stopped.append("abort"))
    monkeypatch.setattr(MANAGER, "stop", lambda *a, **k: stopped.append("stop"))
    try:
        out = chat_svc.retry_unprocessed("retry-live", home=home)
        assert out == {"ok": True, "action": "live"}
        assert stopped == []
        assert bots_svc.get_bot("retry-live", home=home)["status"] == "busy"
    finally:
        settled.set()
        agent_svc.clear_active_run("retry-live")


def test_retry_noop_when_turn_complete(home, monkeypatch):
    bots_svc.create_bot("retry-ok", home=home)
    chat_svc.create_message("retry-ok", "Salut", role="user", home=home)
    chat_svc.create_message(
        "retry-ok", "Bonjour !", role="assistant", home=home
    )
    called = []

    monkeypatch.setattr(
        "autonomous.services.agent.get_agent",
        lambda *a, **k: type(
            "A",
            (),
            {
                "start_run": lambda *x, **y: called.append(1) or "",
                "stop_run": lambda *x, **y: None,
            },
        )(),
    )

    out = chat_svc.retry_unprocessed("retry-ok", home=home)
    assert out == {"ok": True, "action": "noop"}
    assert called == []
