"""Host bash permission (allow_host_shell) — default off; VM exec unaffected."""

from __future__ import annotations

import pytest

from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services import terminal as term_svc
from autonomous.services.errors import AutonomousError


def test_vm_exec_does_not_need_host_shell(home, monkeypatch):
    bots_svc.create_bot("VmFree", slug="vmfree", home=home)
    bots_svc.patch_bot(
        "vmfree",
        {
            "capability": "terminal",
            "allow_host_shell": False,
            "desk": {"state": "running", "container_name": "autonomous-test"},
        },
        home=home,
    )

    def fake_run(*_a, **_k):
        class R:
            returncode = 0
            stdout = "ok\n"
            stderr = ""

        return R()

    monkeypatch.setattr(term_svc.subprocess, "run", fake_run)
    entry = term_svc.exec_command("vmfree", "echo ok", home=home)
    assert entry["exit_code"] == 0


def test_vm_exec_still_needs_capability(home):
    bots_svc.create_bot("NoCap", slug="nocap", home=home)
    with pytest.raises(AutonomousError) as exc:
        term_svc.exec_command("nocap", "echo hi", home=home)
    assert exc.value.code == "no_capability"


def test_host_shell_request_card_and_approve(home):
    bots_svc.create_bot("Hostcard", slug="hostcard", home=home)
    out = term_svc.request_shell_authorization(
        "hostcard", reason="need host uname", home=home
    )
    assert out["state"] == "pending"
    assert out["message_id"]
    msgs = chat_svc.list_messages("hostcard", limit=10, home=home)
    assert any(
        (m.get("meta") or {}).get("kind") == "host_shell_request"
        and (m.get("meta") or {}).get("state") == "pending"
        for m in msgs
    )
    st = term_svc.set_allow_host_shell("hostcard", True, home=home)
    assert st["allow_host_shell"] is True
    assert st["pending_request_id"] is None
    assert bots_svc.get_bot("hostcard", home=home)["allow_host_shell"] is True


def test_approve_resumes_a_running_host_shell_tool(home, monkeypatch):
    bots_svc.create_bot("Hoststuck", slug="hoststuck", home=home)
    bots_svc.patch_bot("hoststuck", {"status": "busy", "allow_host_shell": False}, home=home)
    chat_svc.create_message(
        "hoststuck",
        "🔧 host_request_shell\nstatus: running\n{}",
        role="event",
        meta={
            "kind": "tool",
            "status": "running",
            "tool_name": "host_request_shell",
        },
        home=home,
    )
    resumed = {}

    def fake_resume(bot, home=None):
        resumed["bot"] = bot
        bots_svc.patch_bot(bot, {"status": "busy"}, home=home)
        return {"ok": True}

    monkeypatch.setattr(chat_svc, "resume_run", fake_resume)
    term_svc.set_allow_host_shell("hoststuck", True, home=home)
    msgs = chat_svc.list_messages("hoststuck", limit=10, home=home)
    tool = next(m for m in msgs if (m.get("meta") or {}).get("tool_name") == "host_request_shell")
    assert tool["meta"]["status"] == "done"
    assert "bash" in tool["content"]
    assert resumed["bot"] == "hoststuck"
    assert bots_svc.get_bot("hoststuck", home=home)["status"] == "busy"


def test_revoke_host_shell(home):
    bots_svc.create_bot("Hostrev", slug="hostrev", home=home)
    bots_svc.patch_bot("hostrev", {"allow_host_shell": True}, home=home)
    assert bots_svc.get_bot("hostrev", home=home)["allow_host_shell"] is True
    bots_svc.patch_bot("hostrev", {"allow_host_shell": False}, home=home)
    assert bots_svc.get_bot("hostrev", home=home)["allow_host_shell"] is False


def test_shell_api(home, auth_client):
    bots_svc.create_bot("Hostapi", slug="hostapi", home=home)
    r = auth_client.get("/api/v1/bots/hostapi/shell")
    assert r.status_code == 200
    assert r.get_json()["allow_host_shell"] is False
    r2 = auth_client.post(
        "/api/v1/bots/hostapi/shell/request",
        json={"reason": "test"},
    )
    assert r2.status_code == 200
    assert r2.get_json()["state"] == "pending"
    r3 = auth_client.post(
        "/api/v1/bots/hostapi/shell/request/resolve",
        json={"action": "approve"},
    )
    assert r3.status_code == 200
    assert r3.get_json()["allow_host_shell"] is True
