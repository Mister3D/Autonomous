"""VM desktop screenshot (server-side, no browser)."""

from __future__ import annotations

import pytest

from autonomous.services import bots as bots_svc
from autonomous.services import screenshot as shot_svc
from autonomous.services.errors import AutonomousError


def test_screenshot_requires_capability(home):
    bots_svc.create_bot("Shot", slug="shotbot", home=home)
    with pytest.raises(AutonomousError) as exc:
        shot_svc.capture("shotbot", home=home)
    assert exc.value.code == "no_capability"


def test_screenshot_requires_running_desk(home):
    bots_svc.create_bot("Shot2", slug="shotbot2", home=home)
    bots_svc.patch_bot(
        "shotbot2",
        {"capability": "screen", "desk": {"state": "stopped"}},
        home=home,
    )
    with pytest.raises(AutonomousError) as exc:
        shot_svc.capture("shotbot2", home=home)
    assert exc.value.code == "desk_not_running"


def test_screenshot_api_no_capability(home, auth_client):
    bots_svc.create_bot("Shot API", slug="shot-api", home=home)
    r = auth_client.post(
        "/api/v1/bots/shot-api/screen/screenshot",
        json={"show_in_chat": True},
    )
    assert r.status_code == 400
