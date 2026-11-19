"""Manager household: create bots + confirmed multi-bot delete."""

from __future__ import annotations

import pytest

from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
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


def test_delete_card_confirm(manager, home):
    bots_svc.create_bot("Temp A", home=home)
    bots_svc.create_bot("Temp B", home=home)

    req = household_svc.create_delete_request(
        "assistant",
        bots=["temp-a", "temp-b"],
        prompt="Cleanup smoke bots",
        home=home,
    )
    assert req["state"] == "pending"
    assert all(b["selected"] for b in req["bots"])
    assert bots_svc.get_bot("assistant", home=home)["status"] == "waiting"
    queued = chat_svc.send_message("assistant", "supprime seulement A", home=home)
    assert (queued.get("meta") or {}).get("queued") is True
    assert household_svc.get_delete_request(req["id"], home=home)["state"] == "pending"
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


def test_delete_card_can_delete_manager_itself(manager, home):
    req = household_svc.create_delete_request(
        "assistant",
        bots=["assistant"],
        prompt="Setup is complete; remove this temporary assistant.",
        home=home,
    )

    out = household_svc.resolve_delete_request(
        req["id"],
        action="confirm",
        selected=["assistant"],
        home=home,
    )

    assert out["state"] == "confirmed"
    assert out["result"]["deleted"] == ["assistant"]
    with pytest.raises(Exception):
        bots_svc.get_bot("assistant", home=home)


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


def test_household_api_can_delete_manager_itself(auth_client, home):
    settings_svc.set_value("bots.default_model", "test/provider:fixture", home=home)
    created = auth_client.post(
        "/api/v1/bots",
        json={"name": "Setup Assistant", "is_manager": True},
    )
    assert created.status_code == 201
    name = created.json["name"]

    request = auth_client.post(
        f"/api/v1/bots/{name}/household/delete-requests",
        json={
            "bots": [name],
            "prompt": "Setup is complete; remove this temporary assistant.",
        },
    )
    assert request.status_code == 200

    confirmed = auth_client.post(
        f"/api/v1/bots/{name}/household/delete-requests/{request.json['id']}",
        json={"action": "confirm", "bots": [name]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json["result"]["deleted"] == [name]
    assert auth_client.get(f"/api/v1/bots/{name}").status_code == 404
