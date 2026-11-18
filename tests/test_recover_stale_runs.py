"""Stale busy status after serve restart must be cleaned up."""

from __future__ import annotations

from autonomous.services import agent as agent_svc
from autonomous.services import approvals as approval_svc
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc


def test_recover_busy_auto_resumes_without_card(home, monkeypatch):
    bots_svc.create_bot("ghost", home=home)
    bots_svc.patch_bot("ghost", {"status": "busy"}, home=home)
    chat_svc.create_message("ghost", "Fais X", role="user", home=home)
    chat_svc.create_message(
        "ghost",
        "",
        role="assistant",
        meta={"streaming": True},
        home=home,
    )
    chat_svc.create_message(
        "ghost",
        "🔧 vm_look\nstatus: running\n{}",
        role="event",
        meta={"kind": "tool", "status": "running", "tool_name": "vm_look"},
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

    recovered = agent_svc.recover_stale_runs(home=home)
    assert recovered == ["ghost"]

    msgs = chat_svc.list_messages("ghost", home=home)
    streaming = [
        m
        for m in msgs
        if m["role"] == "assistant" and (m.get("meta") or {}).get("streaming")
    ]
    assert streaming == []
    tools = [m for m in msgs if (m.get("meta") or {}).get("kind") == "tool"]
    assert tools and tools[-1]["meta"]["status"] == "error"
    resume = [
        m
        for m in msgs
        if (m.get("meta") or {}).get("kind") == "agent_interrupted"
        and (m.get("meta") or {}).get("state") == "pending"
    ]
    assert resume == [], "must auto-resume — no manual Resume card"
    assert prompts and "Original task" in prompts[0]


def test_recover_busy_drains_queued_webhook_without_resume(home, monkeypatch):
    bots_svc.create_bot("hooked", home=home)
    bots_svc.patch_bot("hooked", {"status": "busy"}, home=home)
    queued = chat_svc.create_message(
        "hooked",
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

    recovered = agent_svc.recover_stale_runs(home=home)
    assert recovered == ["hooked"]
    assert bots_svc.get_bot("hooked", home=home)["status"] == "idle"
    assert started == ["confirm payload"]
    by_id = {m["id"]: m for m in chat_svc.list_messages("hooked", home=home)}
    assert not (by_id[queued["id"]].get("meta") or {}).get("queued")
    resume = [
        m
        for m in chat_svc.list_messages("hooked", home=home)
        if (m.get("meta") or {}).get("kind") == "agent_interrupted"
    ]
    assert resume == []


def test_recover_keeps_waiting_when_approval_pending(home):
    bots_svc.create_bot("waiter", home=home)
    approval_svc.create_request(
        "waiter",
        prompt="Continue?",
        title="OK?",
        home=home,
    )
    assert bots_svc.get_bot("waiter", home=home)["status"] == "waiting"

    recovered = agent_svc.recover_stale_runs(home=home)
    assert recovered == []
    assert bots_svc.get_bot("waiter", home=home)["status"] == "waiting"


def test_recover_orphan_waiting_without_pending(home):
    bots_svc.create_bot("orphan", home=home)
    bots_svc.patch_bot("orphan", {"status": "waiting"}, home=home)

    recovered = agent_svc.recover_stale_runs(home=home)
    assert recovered == ["orphan"]
    assert bots_svc.get_bot("orphan", home=home)["status"] == "idle"
