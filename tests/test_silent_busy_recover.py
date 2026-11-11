"""Server-side silent-busy watchdog (no browser tab required)."""

from __future__ import annotations

import threading
import time

from autonomous.services import agent as agent_svc
from autonomous.services import approvals as approval_svc
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc


def _reset_watchdog() -> None:
    with agent_svc._PROGRESS_LOCK:
        agent_svc._LAST_PROGRESS.clear()
        agent_svc._LAST_SILENT_RETRY.clear()
    with agent_svc._ACTIVE_LOCK:
        agent_svc._ACTIVE_RUNS.clear()


def test_silent_busy_zombie_retries_without_live_worker(home, monkeypatch):
    _reset_watchdog()
    bots_svc.create_bot("zombie", home=home)
    bots_svc.patch_bot("zombie", {"status": "busy"}, home=home)
    chat_svc.create_message("zombie", "Fais X", role="user", home=home)
    called: list[str] = []

    def fake_retry(bot, *, home=None):
        called.append(bot)
        bots_svc.patch_bot(bot, {"status": "idle"}, home=home)
        return {"ok": True, "action": "resumed"}

    monkeypatch.setattr(chat_svc, "retry_unprocessed", fake_retry)

    recovered = agent_svc.recover_silent_busy_runs(home=home, grace_sec=1.0)
    assert recovered == ["zombie"]
    assert called == ["zombie"]


def test_silent_busy_live_worker_respects_grace(home, monkeypatch):
    _reset_watchdog()
    bots_svc.create_bot("live", home=home)
    bots_svc.patch_bot("live", {"status": "busy"}, home=home)
    settled = threading.Event()
    assert agent_svc._register_run("live", settled)
    agent_svc.touch_run_progress("live")
    called: list[str] = []

    monkeypatch.setattr(
        chat_svc,
        "retry_unprocessed",
        lambda *a, **k: called.append("x") or {"ok": True, "action": "noop"},
    )

    assert agent_svc.recover_silent_busy_runs(home=home, grace_sec=30.0) == []
    assert called == []

    # Three hours of silence still must not stop a live Pi.
    with agent_svc._PROGRESS_LOCK:
        agent_svc._LAST_PROGRESS["live"] = time.monotonic() - 3 * 3600
    assert agent_svc.recover_silent_busy_runs(home=home, grace_sec=30.0) == []
    assert called == []
    settled.set()
    agent_svc.clear_active_run("live")


def test_silent_busy_skips_human_wait(home, monkeypatch):
    _reset_watchdog()
    bots_svc.create_bot("wait", home=home)
    approval_svc.create_request(
        "wait", prompt="OK?", title="Check", home=home
    )
    # Force busy so the watchdog would otherwise fire (approval leaves waiting).
    bots_svc.patch_bot("wait", {"status": "busy"}, home=home)
    called: list[str] = []
    monkeypatch.setattr(
        chat_svc,
        "retry_unprocessed",
        lambda *a, **k: called.append("x") or {"ok": True, "action": "noop"},
    )
    assert agent_svc.recover_silent_busy_runs(home=home, grace_sec=0.0) == []
    assert called == []


def test_silent_busy_cooldown(home, monkeypatch):
    _reset_watchdog()
    bots_svc.create_bot("cool", home=home)
    bots_svc.patch_bot("cool", {"status": "busy"}, home=home)
    n = {"c": 0}

    def fake_retry(bot, *, home=None):
        n["c"] += 1
        bots_svc.patch_bot(bot, {"status": "busy"}, home=home)
        return {"ok": True, "action": "noop"}

    monkeypatch.setattr(chat_svc, "retry_unprocessed", fake_retry)
    assert agent_svc.recover_silent_busy_runs(home=home, grace_sec=0.0) == ["cool"]
    bots_svc.patch_bot("cool", {"status": "busy"}, home=home)
    assert agent_svc.recover_silent_busy_runs(home=home, grace_sec=0.0) == []
    assert n["c"] == 1


def test_silent_busy_resumes_pending_interrupt_card(home, monkeypatch):
    _reset_watchdog()
    bots_svc.create_bot("card", home=home)
    chat_svc.post_agent_interrupted(
        "card",
        reason="The agent was interrupted by a server restart.",
        home=home,
    )
    called: list[str] = []

    def fake_retry(bot, *, home=None):
        called.append(bot)
        chat_svc._mark_resume_cards(bot, state="resumed", home=home)
        return {"ok": True, "action": "resumed"}

    monkeypatch.setattr(chat_svc, "retry_unprocessed", fake_retry)
    assert agent_svc.recover_silent_busy_runs(home=home, grace_sec=0.0) == ["card"]
    assert called == ["card"]
