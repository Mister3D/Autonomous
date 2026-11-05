"""Desk auto-sleep after idle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from autonomous.services import bots as bots_svc
from autonomous.services import desk as desk_svc


def test_create_bot_auto_sleep_default(home):
    bot = bots_svc.create_bot("sleepy", home=home)
    assert bot["auto_sleep"] is True


def test_patch_auto_sleep(auth_client, home):
    auth_client.post("/api/v1/bots", json={"name": "nosleep"})
    r = auth_client.patch(
        "/api/v1/bots/nosleep",
        json={"auto_sleep": False},
    )
    assert r.status_code == 200
    assert r.json["auto_sleep"] is False


def test_tick_sleeps_idle_desk(home):
    bots_svc.create_bot("idlebot", home=home)
    past = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    bots_svc.patch_bot(
        "idlebot",
        {
            "capability": "terminal",
            "desk": {
                "state": "running",
                "container_id": "x",
                "created_at": past,
            },
            "desk_last_active_at": past,
            "auto_sleep": True,
            "status": "idle",
        },
        home=home,
    )

    fake_c = MagicMock()
    fake_c.status = "running"
    fake_client = MagicMock()
    fake_client.containers.get.return_value = fake_c

    with patch("autonomous.services.desk._docker", return_value=fake_client):
        n = desk_svc.tick_auto_sleep(home=home)
    assert n == 1
    fake_c.stop.assert_called_once()
    desk = bots_svc.get_bot("idlebot", home=home)["desk"]
    assert desk["state"] == "sleeping"


def test_tick_skips_when_disabled(home):
    bots_svc.create_bot("keepup", home=home)
    past = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    bots_svc.patch_bot(
        "keepup",
        {
            "capability": "terminal",
            "desk": {"state": "running", "created_at": past},
            "desk_last_active_at": past,
            "auto_sleep": False,
            "status": "idle",
        },
        home=home,
    )
    with patch("autonomous.services.desk._docker") as d:
        n = desk_svc.tick_auto_sleep(home=home)
    assert n == 0
    d.assert_not_called()


def test_tick_skips_busy(home):
    bots_svc.create_bot("busybot2", home=home)
    past = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    bots_svc.patch_bot(
        "busybot2",
        {
            "capability": "terminal",
            "desk": {"state": "running", "created_at": past},
            "desk_last_active_at": past,
            "auto_sleep": True,
            "status": "busy",
        },
        home=home,
    )
    with patch("autonomous.services.desk._docker") as d:
        n = desk_svc.tick_auto_sleep(home=home)
    assert n == 0
    d.assert_not_called()


def test_wake_from_sleep(home):
    bots_svc.create_bot("wakebot", home=home)
    bots_svc.patch_bot(
        "wakebot",
        {
            "capability": "terminal",
            "desk": {"state": "sleeping", "slept_at": "2026-01-01T00:00:00Z"},
        },
        home=home,
    )
    fake_c = MagicMock()
    fake_c.status = "exited"

    def _reload():
        fake_c.status = "running"

    fake_c.reload.side_effect = _reload
    fake_client = MagicMock()
    fake_client.containers.get.return_value = fake_c

    with patch("autonomous.services.desk._docker", return_value=fake_client):
        desk = desk_svc.ensure_awake("wakebot", home=home)
    assert desk["state"] == "running"
    fake_c.start.assert_called_once()


def test_api_desk_wake(auth_client, home):
    auth_client.post("/api/v1/bots", json={"name": "apiwake"})
    bots_svc.patch_bot(
        "apiwake",
        {
            "capability": "screen",
            "desk": {
                "state": "sleeping",
                "slept_at": "2026-01-01T00:00:00Z",
                "mode": "screen",
                "vnc_port": 15999,
            },
        },
        home=home,
    )
    fake_c = MagicMock()
    fake_c.status = "exited"

    def _reload():
        fake_c.status = "running"

    fake_c.reload.side_effect = _reload
    fake_client = MagicMock()
    fake_client.containers.get.return_value = fake_c

    with patch("autonomous.services.desk._docker", return_value=fake_client):
        with patch("autonomous.services.desk.sync_desktop_scripts"):
            with patch("autonomous.services.desk.restart_bot_chrome"):
                with patch("autonomous.services.desk.sync_host_api_env"):
                    with patch("subprocess.run") as run:
                        run.return_value = MagicMock(stdout="200")
                        r = auth_client.post("/api/v1/bots/apiwake/desk/wake")
    assert r.status_code == 200
    assert r.json["state"] == "running"
    fake_c.start.assert_called_once()
