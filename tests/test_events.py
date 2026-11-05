"""Cron schedules + inbound webhooks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from autonomous.services import bot_events as events_svc
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services import scheduler as scheduler_svc
from autonomous.services.cronutil import next_run_after, shift_cron, validate_cron


def test_cron_validate_and_next():
    assert validate_cron("*/5 * * * *") == "*/5 * * * *"
    after = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    nxt = next_run_after("0 13 * * *", after)
    assert nxt == datetime(2026, 10, 28, 13, 0, tzinfo=timezone.utc)


def test_shift_cron_local_utc():
    assert shift_cron("0 9 * * 1-5", -120) == "0 7 * * 1-5"
    assert shift_cron("0 7 * * 1-5", 120) == "0 9 * * 1-5"
    assert shift_cron("0 1 * * 1", -120) == "0 23 * * 0"
    assert shift_cron("0 23 * * 0", 120) == "0 1 * * 1"
    assert shift_cron("*/15 * * * *", 60) == "*/15 * * * *"
    assert shift_cron("0 * * * *", -120) == "0 * * * *"
    assert shift_cron("0 9 * * *", 0) == "0 9 * * *"
    assert shift_cron("0 9 * * 1-5", -330) == "30 3 * * 1-5"


def test_schedule_crud(auth_client, home):
    auth_client.post("/api/v1/bots", json={"name": "cronbot"})
    r = auth_client.post(
        "/api/v1/bots/cronbot/schedules",
        json={
            "name": "morning",
            "cron": "0 9 * * 1-5",
            "instruction": "Dis bonjour",
            "recurring": True,
        },
    )
    assert r.status_code == 201, r.data
    row = r.json
    assert row["name"] == "morning"
    assert row["cron"] == "0 9 * * 1-5"
    assert row["timezone"]
    assert row["cron_utc"]
    assert str(row["next_run_at"]).endswith("Z")
    assert row["enabled"] is True
    sid = row["id"]

    listed = auth_client.get("/api/v1/bots/cronbot/schedules").json
    assert any(s["id"] == sid for s in listed)

    patched = auth_client.patch(
        f"/api/v1/bots/cronbot/schedules/{sid}",
        json={"enabled": False},
    )
    assert patched.status_code == 200
    assert patched.json["enabled"] is False

    deleted = auth_client.delete(f"/api/v1/bots/cronbot/schedules/{sid}")
    assert deleted.status_code == 200
    assert auth_client.get("/api/v1/bots/cronbot/schedules").json == []


def test_schedule_local_stored_as_utc(auth_client, monkeypatch):
    monkeypatch.setattr(
        "autonomous.services.cronutil.host_offset_minutes",
        lambda at=None: 120,
    )
    cleared = auth_client.put("/api/v1/settings", json={"timezone": ""})
    assert cleared.status_code == 200
    auth_client.post("/api/v1/bots", json={"name": "tzbot"})
    r = auth_client.post(
        "/api/v1/bots/tzbot/schedules",
        json={"name": "morning", "cron": "0 9 * * 1-5", "instruction": "Hi"},
    )
    assert r.status_code == 201, r.data
    row = r.json
    assert row["cron"] == "0 9 * * 1-5"
    assert row["cron_utc"] == "0 7 * * 1-5"
    assert row["utc_offset"] == "+02:00"
    patched = auth_client.patch(
        f"/api/v1/bots/tzbot/schedules/{row['id']}",
        json={"enabled": False},
    )
    assert patched.status_code == 200
    assert patched.json["enabled"] is False
    assert patched.json["cron_utc"] == "0 7 * * 1-5"
    assert patched.json["cron"] == "0 9 * * 1-5"


def test_clock(auth_client):
    r = auth_client.get("/api/v1/clock")
    assert r.status_code == 200
    body = r.json
    assert body["timezone"]
    assert body["utc_offset"][0] in "+-"
    assert len(body["now"]) == 16


def test_oneshot_already_passed_is_rejected(auth_client):
    auth_client.post("/api/v1/bots", json={"name": "latebot"})
    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=1)
    cron = f"{past.minute} {past.hour} * * *"
    r = auth_client.post(
        "/api/v1/bots/latebot/schedules",
        json={"name": "late", "cron": cron, "recurring": False},
    )
    assert r.status_code == 400, r.data
    body = r.json
    assert body.get("error_code") == "oneshot_too_far" or "already passed" in str(body)
    assert auth_client.get("/api/v1/bots/latebot/schedules").json == []

    tomorrow = now + timedelta(days=1)
    pinned = f"{past.minute} {past.hour} {tomorrow.day} {tomorrow.month} *"
    ok = auth_client.post(
        "/api/v1/bots/latebot/schedules",
        json={"name": "tomorrow", "cron": pinned, "recurring": False},
    )
    assert ok.status_code == 201, ok.data
    assert ok.json["next_run_local"]
    assert ok.json["now_local"]


def test_user_timezone_shifts_display_only(auth_client):
    auth_client.put("/api/v1/settings", json={"timezone": "Africa/Lagos"})
    auth_client.post("/api/v1/bots", json={"name": "lagosbot"})
    r = auth_client.post(
        "/api/v1/bots/lagosbot/schedules",
        json={"name": "morning", "cron": "0 9 * * 1-5", "instruction": "Hi"},
    )
    assert r.status_code == 201, r.data
    row = r.json
    assert row["timezone"] == "Africa/Lagos"
    assert row["utc_offset"] == "+01:00"
    assert row["cron"] == "0 9 * * 1-5"
    assert row["cron_utc"] == "0 8 * * 1-5"
    clock = auth_client.get("/api/v1/clock").json
    assert clock["timezone"] == "Africa/Lagos"
    assert clock["utc_offset"] == "+01:00"

    switched = auth_client.put("/api/v1/settings", json={"timezone": "Africa/Abidjan"})
    assert switched.status_code == 200
    listed = auth_client.get("/api/v1/bots/lagosbot/schedules").json
    shown = next(s for s in listed if s["id"] == row["id"])
    assert shown["cron_utc"] == "0 8 * * 1-5"
    assert shown["cron"] == "0 8 * * 1-5"
    assert shown["timezone"] == "Africa/Abidjan"
    assert shown["utc_offset"] == "+00:00"

    bad = auth_client.put("/api/v1/settings", json={"timezone": "Not/AZone"})
    assert bad.status_code == 400


def test_webhook_crud_and_public_fire(auth_client, home):
    auth_client.post("/api/v1/bots", json={"name": "hookbot"})
    r = auth_client.post(
        "/api/v1/bots/hookbot/webhooks",
        json={"name": "ingress", "instruction": "Traite l’événement"},
    )
    assert r.status_code == 201, r.data
    wh = r.json
    assert wh["token"]
    assert wh["url_path"] == "/api/v1/hooks"
    assert wh.get("url", "").endswith("/api/v1/hooks")
    assert "url_path_legacy" not in wh

    # Bearer header (token not in the URL)
    fire = auth_client.post(
        "/api/v1/hooks",
        json={"hello": "world"},
        headers={"Authorization": f"Bearer {wh['token']}"},
    )
    assert fire.status_code == 200, fire.data
    assert fire.json["ok"] is True
    assert fire.json["bot"] == "hookbot"
    assert fire.json["queued"] is False

    msgs = chat_svc.list_messages("hookbot", home=home)
    hit = [
        m
        for m in msgs
        if m["role"] == "user" and (m.get("meta") or {}).get("kind") == "webhook"
    ]
    assert hit, msgs
    assert hit[-1]["meta"].get("has_payload") is True
    assert hit[-1]["meta"].get("payload") == {"hello": "world"}
    assert "Traite" in hit[-1]["content"]

    # Token-in-path is gone
    legacy = auth_client.post(f"/api/v1/hooks/{wh['token']}", json={"legacy": True})
    assert legacy.status_code in (404, 401, 405)


def test_webhook_bearer_required(auth_client, home):
    bots_svc.create_bot("bearbot", home=home)
    wh = events_svc.create_webhook("bearbot", name="b", home=home)
    missing = auth_client.post("/api/v1/hooks", json={})
    assert missing.status_code == 401
    bad = auth_client.post(
        "/api/v1/hooks",
        json={},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert bad.status_code == 404
    ok = auth_client.post(
        "/api/v1/hooks",
        json={},
        headers={"Authorization": f"Bearer {wh['token']}"},
    )
    assert ok.status_code == 200, ok.data
    # GET must not fire (POST only) — Flask may answer 405 or 404 without a get().
    get_r = auth_client.get(
        "/api/v1/hooks",
        headers={"Authorization": f"Bearer {wh['token']}"},
    )
    assert get_r.status_code in (404, 405)


def test_webhook_queues_when_busy(auth_client, home):
    bots_svc.create_bot("busybot", home=home)
    wh = events_svc.create_webhook("busybot", name="q", home=home)
    bots_svc.patch_bot("busybot", {"status": "busy"}, home=home)
    msg = events_svc.fire_webhook(wh["token"], payload={"x": 1}, home=home)
    assert msg["meta"].get("queued") is True
    assert msg["meta"]["kind"] == "webhook"


def test_webhook_unknown_404(auth_client):
    r = auth_client.post(
        "/api/v1/hooks",
        json={},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert r.status_code == 404


def test_oneshot_deleted_after_fire(home):
    bots_svc.create_bot("oncebot", home=home)
    past = (datetime.now(timezone.utc) - timedelta(minutes=2)).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")
    sched = events_svc.create_schedule(
        "oncebot",
        name="once",
        cron="* * * * *",
        instruction="Fais une fois",
        recurring=False,
        home=home,
    )
    # A single far slot: the following match is not part of a short burst.
    from autonomous.db import get_db

    with get_db(home) as conn:
        conn.execute(
            "UPDATE bot_schedules SET cron = ?, next_run_at = ? WHERE id = ?",
            ("0 0 1 1 *", past, sched["id"]),
        )
    due = events_svc.due_schedules(home=home)
    assert any(s["id"] == sched["id"] for s in due)
    events_svc.fire_schedule(
        events_svc.get_schedule("oncebot", sched["id"], home=home),
        home=home,
    )
    assert events_svc.list_schedules("oncebot", home=home) == []
    msgs = chat_svc.list_messages("oncebot", home=home)
    assert any((m.get("meta") or {}).get("kind") == "schedule" for m in msgs)


def test_oneshot_keeps_a_short_burst(home):
    bots_svc.create_bot("burstbot", home=home)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")
    sched = events_svc.create_schedule(
        "burstbot",
        name="burst",
        cron="*/5 * * * *",
        instruction="Encore",
        recurring=False,
        home=home,
    )
    from autonomous.db import get_db

    with get_db(home) as conn:
        conn.execute(
            "UPDATE bot_schedules SET next_run_at = ? WHERE id = ?",
            (past, sched["id"]),
        )
    events_svc.fire_schedule(
        events_svc.get_schedule("burstbot", sched["id"], home=home),
        home=home,
    )
    left = events_svc.list_schedules("burstbot", home=home)
    assert len(left) == 1
    assert left[0]["id"] == sched["id"]
    assert left[0]["next_run_at"] > past


def test_catchup_advances_next_run(home):
    bots_svc.create_bot("catchbot", home=home)
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")
    sched = events_svc.create_schedule(
        "catchbot",
        name="hourly",
        cron="0 * * * *",
        instruction="Tick",
        recurring=True,
        home=home,
    )
    from autonomous.db import get_db

    with get_db(home) as conn:
        conn.execute(
            "UPDATE bot_schedules SET next_run_at = ? WHERE id = ?",
            (past, sched["id"]),
        )
    before = events_svc.get_schedule("catchbot", sched["id"], home=home)
    assert before["next_run_at"] == past
    n = scheduler_svc.tick_once(home=home)
    assert n >= 1
    after = events_svc.get_schedule("catchbot", sched["id"], home=home)
    assert after["next_run_at"] > past
    assert after.get("last_run_at")
