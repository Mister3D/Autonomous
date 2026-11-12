"""Manager household: create bots + confirmed multi-bot delete."""

from __future__ import annotations

import pytest

from autonomous.services import bots as bots_svc
from autonomous.services import household as household_svc
from autonomous.services import settings as settings_svc
from autonomous.services.errors import Forbidden, ValidationError


@pytest.fixture
def manager(home):
    settings_svc.set_value("bots.default_model", "test/provider:fixture", home=home)
    return bots_svc.create_bot("Assistant", is_manager=True, home=home)


def test_create_bots_uses_settings_default_only(manager, home):
    created = household_svc.create_bots(
        "assistant",
        [
            {"name": "Alpha"},
            {"name": "Beta", "model": "other/not-the-default"},
        ],
        home=home,
    )
    assert {c["name"] for c in created} == {"alpha", "beta"}
    assert bots_svc.get_bot("alpha", home=home)["model"] == "test/provider:fixture"
    assert bots_svc.get_bot("beta", home=home)["model"] == "test/provider:fixture"


def test_create_requires_manager(home):
    settings_svc.set_value("bots.default_model", "test/provider:fixture", home=home)
    bots_svc.create_bot("Worker", home=home)
    with pytest.raises(Forbidden) as exc:
        household_svc.create_bots("worker", [{"name": "Nope"}], home=home)
    assert exc.value.code == "manager_required"


def test_create_requires_model(home):
    bots_svc.create_bot("Assistant", is_manager=True, home=home)
    with pytest.raises(ValidationError) as exc:
        household_svc.create_bots("assistant", [{"name": "Nope"}], home=home)
    assert exc.value.code == "model_required"


def test_delete_card_confirm_and_skip_self(manager, home):
    bots_svc.create_bot("Temp A", home=home)
    bots_svc.create_bot("Temp B", home=home)
    with pytest.raises(ValidationError) as exc:
        household_svc.create_delete_request(
            "assistant", bots=["assistant", "temp-a"], home=home
        )
    assert exc.value.code == "cannot_delete_self"

    req = household_svc.create_delete_request(
        "assistant",
        bots=["temp-a", "temp-b"],
        prompt="Cleanup smoke bots",
        home=home,
    )
    assert req["state"] == "pending"
    assert all(b["selected"] for b in req["bots"])
    assert bots_svc.get_bot("assistant", home=home)["status"] == "waiting"

    out = household_svc.resolve_delete_request(
        req["id"],
        action="confirm",
        selected=["temp-a"],
        home=home,
    )
    assert out["state"] == "confirmed"
    assert out["result"]["deleted"] == ["temp-a"]
    with pytest.raises(Exception):
        bots_svc.get_bot("temp-a", home=home)
    assert bots_svc.get_bot("temp-b", home=home)["name"] == "temp-b"


def test_household_api(auth_client, home):
    settings_svc.set_value("bots.default_model", "test/provider:fixture", home=home)
    assert auth_client.post("/api/v1/bots", json={"name": "Mgr", "is_manager": True}).status_code == 201
    r = auth_client.post(
        "/api/v1/bots/mgr/household/bots",
        json={
            "bots": [
                {"name": "Worker One"},
                {"name": "Worker Two", "model": "other/not-the-default"},
            ]
        },
    )
    assert r.status_code == 200, r.data
    assert {c["name"] for c in r.json["created"]} == {"worker-one", "worker-two"}
    by_name = {c["name"]: c for c in r.json["created"]}
    assert by_name["worker-two"]["model"] == "test/provider:fixture"

    d = auth_client.post(
        "/api/v1/bots/mgr/household/delete-requests",
        json={"bots": ["worker-one", "worker-two"], "prompt": "Remove workers"},
    )
    assert d.status_code == 200, d.data
    rid = d.json["id"]
    conf = auth_client.post(
        f"/api/v1/bots/mgr/household/delete-requests/{rid}",
        json={"action": "confirm", "bots": ["worker-one", "worker-two"]},
    )
    assert conf.status_code == 200, conf.data
    assert set(conf.json["result"]["deleted"]) == {"worker-one", "worker-two"}
