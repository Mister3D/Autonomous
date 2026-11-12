"""Server-side terminal exec (agent / CLI / API) — no browser required."""

from __future__ import annotations

import subprocess
import threading
import time

import pytest

from autonomous.services import bots as bots_svc
from autonomous.services import terminal as term_svc
from autonomous.services.errors import AutonomousError


def test_sleep_is_not_executed(home):
    bots_svc.create_bot("Termsleep", slug="termsleep", home=home)
    out = term_svc.exec_command("termsleep", "sleep 5 && echo ok", home=home)
    assert out["exit_code"] == 0
    assert "browser_snapshot" in out["output"]
    assert "ok" not in out["output"].split()


def test_exec_requires_capability(home):
    bots_svc.create_bot("Termbot", slug="termbot", home=home)
    with pytest.raises(AutonomousError) as exc:
        term_svc.exec_command("termbot", "echo hi", home=home)
    assert exc.value.code == "no_capability"


def test_exec_requires_running_desk(home):
    bots_svc.create_bot("Termbot2", slug="termbot2", home=home)
    bots_svc.patch_bot(
        "termbot2",
        {"capability": "terminal", "desk": {"state": "stopped"}},
        home=home,
    )
    with pytest.raises(AutonomousError) as exc:
        term_svc.exec_command("termbot2", "echo hi", home=home)
    assert exc.value.code == "desk_not_running"


def test_exec_rejects_empty_command(home):
    bots_svc.create_bot("Termbot3", slug="termbot3", home=home)
    bots_svc.patch_bot(
        "termbot3",
        {"capability": "terminal", "desk": {"state": "running"}},
        home=home,
    )
    with pytest.raises(AutonomousError):
        term_svc.exec_command("termbot3", "  ", home=home)


def test_cancel_stops_inflight_command(home, monkeypatch):
    from autonomous.services import desk as desk_svc

    bots_svc.create_bot("Cancelbot", slug="cancelbot", home=home)
    bots_svc.patch_bot(
        "cancelbot",
        {"capability": "terminal", "desk": {"state": "running"}},
        home=home,
    )
    monkeypatch.setattr(desk_svc, "ensure_awake", lambda *a, **k: None)
    monkeypatch.setattr(desk_svc, "container_name", lambda *a, **k: "unused")

    real_popen = subprocess.Popen

    def fake_popen(cmd, **kwargs):
        return real_popen(
            ["sleep", "30"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

    monkeypatch.setattr(term_svc.subprocess, "Popen", fake_popen)
    box: dict = {}

    def run() -> None:
        box["entry"] = term_svc.exec_command(
            "cancelbot", "sleep 30", timeout=20, home=home
        )

    worker = threading.Thread(target=run)
    worker.start()
    cancelled = False
    for _ in range(50):
        if term_svc.cancel_running_command("cancelbot"):
            cancelled = True
            break
        time.sleep(0.05)
    worker.join(timeout=5)
    assert cancelled
    assert not worker.is_alive()
    assert box["entry"]["exit_code"] == 130
    assert "[stopped]" in box["entry"]["output"]
    assert term_svc.cancel_running_command("cancelbot") is False


def test_terminal_exec_api_auth(home, auth_client):
    bots_svc.create_bot("ApiTerm", slug="api-term", home=home)
    r = auth_client.post(
        "/api/v1/bots/api-term/terminal/exec",
        json={"command": "echo hi", "timeout": 5},
    )
    assert r.status_code == 400
    body = r.get_json()
    msg = (body.get("message") or "").lower()
    assert (
        body.get("error_code") == "no_capability"
        or body.get("code") in ("no_capability", 400)
        or "capability" in msg
        or "error" in body
    )
