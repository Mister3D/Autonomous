"""Server-side terminal exec (agent / CLI / API) — no browser required."""

from __future__ import annotations

import pytest

from autonomous.services import bots as bots_svc
from autonomous.services import terminal as term_svc
from autonomous.services.errors import AutonomousError


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
