"""Companion nudge after a bot stays in status=waiting."""

from __future__ import annotations

import threading
import time

from autonomous.services import bots as bots_svc


def test_waiting_nudge_fires_once_after_delay(home, monkeypatch):
    bots_svc.create_bot("waiter", home=home)
    monkeypatch.setattr(bots_svc, "WAITING_NUDGE_DELAY_S", 0.05)
    calls: list[dict] = []
    done = threading.Event()

    def fake_notify(title, body, bot="", *, home=None):
        calls.append({"title": title, "body": body, "bot": bot})
        done.set()
        return {"ok": True, "delivered": 1}

    monkeypatch.setattr(
        "autonomous.services.devices.notify_user",
        fake_notify,
    )

    bots_svc.patch_bot("waiter", {"status": "waiting"}, home=home)
    # Still waiting — re-patch must not reset / double-schedule.
    bots_svc.patch_bot("waiter", {"status": "waiting"}, home=home)

    assert done.wait(2.0), "nudge did not fire"
    # Give a tiny window for a duplicate timer (should not exist).
    time.sleep(0.15)
    assert len(calls) == 1
    assert calls[0]["bot"] == "waiter"
    assert "waiter" in calls[0]["body"].lower() or "Action" in calls[0]["title"]


def test_waiting_nudge_cancelled_when_leaving_waiting(home, monkeypatch):
    bots_svc.create_bot("quick", home=home)
    monkeypatch.setattr(bots_svc, "WAITING_NUDGE_DELAY_S", 0.4)
    calls: list[dict] = []

    monkeypatch.setattr(
        "autonomous.services.devices.notify_user",
        lambda *a, **k: calls.append({"a": a, "k": k}) or {"ok": True, "delivered": 1},
    )
    bots_svc.patch_bot("quick", {"status": "waiting"}, home=home)
    bots_svc.patch_bot("quick", {"status": "idle"}, home=home)
    time.sleep(0.55)
    assert calls == []


def test_waiting_nudge_skips_if_no_longer_waiting(home, monkeypatch):
    bots_svc.create_bot("gone", home=home)
    monkeypatch.setattr(bots_svc, "WAITING_NUDGE_DELAY_S", 30.0)
    calls: list[dict] = []
    monkeypatch.setattr(
        "autonomous.services.devices.notify_user",
        lambda *a, **k: calls.append(1) or {"ok": True, "delivered": 1},
    )
    bots_svc.patch_bot("gone", {"status": "waiting"}, home=home)
    # Direct fire after status cleared — should no-op.
    bots_svc.patch_bot("gone", {"status": "busy"}, home=home)
    bots_svc._fire_waiting_nudge("gone", home)
    assert calls == []
