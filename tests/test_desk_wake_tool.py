"""A chat turn must not wake the VM. A VM tool does, and shows that wait."""

from __future__ import annotations

import inspect
import subprocess
import threading

import pytest

from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services import desk as desk_svc
from autonomous.services.agent import PiAgent
from autonomous.services.errors import AutonomousError


def _sleeping(name: str, *, home) -> None:
    bots_svc.create_bot(name, slug=name, home=home)
    bots_svc.patch_bot(
        name,
        {"capability": "terminal", "desk": {"state": "sleeping", "vnc_port": 1}},
        home=home,
    )


def _patch_wake(monkeypatch, *, fail: bool = False) -> dict:
    calls = {"n": 0}

    def fake_wake(bot, *, home=None):
        calls["n"] += 1
        if fail:
            raise AutonomousError("Desk wake timed out", code="desk_wake_timeout")
        bots_svc.patch_bot(
            bot,
            {"desk": {"state": "running", "vnc_port": 1}},
            home=home,
        )
        return {"state": "running"}

    monkeypatch.setattr(desk_svc, "wake_desk", fake_wake)
    return calls


def _wake_cards(bot: str, *, home) -> list[dict]:
    return [
        m
        for m in chat_svc.list_messages(bot, home=home)
        if (m.get("meta") or {}).get("tool_name") == "vm_wake"
    ]


def test_start_run_does_not_wake_the_desk():
    src = inspect.getsource(PiAgent.start_run)
    assert "ensure_awake" not in src


def test_sleeping_tool_posts_one_wake_card(home, monkeypatch):
    _sleeping("wakeonce", home=home)
    calls = _patch_wake(monkeypatch)
    desk_svc.ensure_awake_for_tool("wakeonce", home=home)
    cards = _wake_cards("wakeonce", home=home)
    assert calls["n"] == 1
    assert len(cards) == 1
    assert cards[0]["meta"]["status"] == "done"
    assert cards[0]["meta"]["counts_as_action"] is False
    assert "démarrée" in cards[0]["content"]
    desk_svc.ensure_awake_for_tool("wakeonce", home=home)
    assert len(_wake_cards("wakeonce", home=home)) == 1
    assert calls["n"] == 1


def test_second_caller_waits_and_does_not_post_another_card(home, monkeypatch):
    _sleeping("waketwo", home=home)
    entered = threading.Event()
    release = threading.Event()
    calls = {"n": 0}

    def fake_wake(bot, *, home=None):
        calls["n"] += 1
        entered.set()
        assert release.wait(3)
        bots_svc.patch_bot(
            bot,
            {"desk": {"state": "running", "vnc_port": 1}},
            home=home,
        )
        return {"state": "running"}

    monkeypatch.setattr(desk_svc, "wake_desk", fake_wake)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            desk_svc.ensure_awake_for_tool("waketwo", home=home)
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=run)
    second = threading.Thread(target=run)
    first.start()
    assert entered.wait(2)
    second.start()
    release.set()
    first.join(timeout=3)
    second.join(timeout=3)
    assert not errors
    assert calls["n"] == 1
    assert len(_wake_cards("waketwo", home=home)) == 1


def test_failed_wake_marks_the_card_as_error(home, monkeypatch):
    _sleeping("wakefail", home=home)
    _patch_wake(monkeypatch, fail=True)
    with pytest.raises(AutonomousError):
        desk_svc.ensure_awake_for_tool("wakefail", home=home)
    cards = _wake_cards("wakefail", home=home)
    assert len(cards) == 1
    assert cards[0]["meta"]["status"] == "error"


def test_status_tool_does_not_wake(home, monkeypatch):
    _sleeping("wakestatus", home=home)
    calls = _patch_wake(monkeypatch)
    desk_svc.prepare_vm_tool("wakestatus", "vm_desk_status", home=home)
    desk_svc.prepare_vm_tool("wakestatus", "vm_request_desk", home=home)
    assert calls["n"] == 0
    assert _wake_cards("wakestatus", home=home) == []


def test_prepare_wakes_before_a_vm_tool(home, monkeypatch):
    _sleeping("wakeprep", home=home)
    calls = _patch_wake(monkeypatch)
    desk_svc.prepare_vm_tool("wakeprep", "vm_click", home=home)
    assert calls["n"] == 1
    assert len(_wake_cards("wakeprep", home=home)) == 1
    desk_svc.prepare_vm_tool("wakeprep", "vm_terminal_exec", home=home)
    assert calls["n"] == 1


def test_wake_card_does_not_count_as_an_action(home):
    bots_svc.create_bot("wakecount", slug="wakecount", home=home)
    chat_svc.create_message("wakecount", "go", role="user", home=home)
    chat_svc.create_message(
        "wakecount",
        "🔧 vm_wake\nstatus: done",
        role="event",
        meta={"kind": "tool", "tool_name": "vm_wake", "counts_as_action": False},
        home=home,
    )
    chat_svc.create_message(
        "wakecount",
        "🔧 vm_click\nstatus: done",
        role="event",
        meta={"kind": "tool", "tool_name": "vm_click"},
        home=home,
    )
    assert chat_svc.count_tools_since_last_user("wakecount", home=home) == 1


def test_terminal_exec_on_a_sleeping_desk_shows_the_wake_card(home, monkeypatch):
    _sleeping("waketerm", home=home)
    calls = _patch_wake(monkeypatch)
    monkeypatch.setattr(desk_svc, "container_name", lambda *a, **k: "unused")
    real_popen = subprocess.Popen

    def fake_popen(cmd, **kwargs):
        return real_popen(
            ["echo", "hi"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )

    monkeypatch.setattr(
        "autonomous.services.terminal.subprocess.Popen",
        fake_popen,
    )
    from autonomous.services import terminal as term_svc

    out = term_svc.exec_command("waketerm", "echo hi", home=home)
    assert out["exit_code"] == 0
    assert calls["n"] == 1
    cards = _wake_cards("waketerm", home=home)
    assert len(cards) == 1
    assert cards[0]["meta"]["status"] == "done"
