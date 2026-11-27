"""Companion pending inbox — vault / approval / clarify / desk / delete cards."""

from __future__ import annotations

from autonomous.services import agent as agent_svc
from autonomous.services import approvals as approval_svc
from autonomous.services import bots as bots_svc
from autonomous.services import clarifies as clarify_svc
from autonomous.services import vault as vault_svc


def test_list_pending_human_waits_collects_cards(home, pairing_on, client, auth_client):
    bots_svc.create_bot("inbox", home=home)
    approval_svc.create_request("inbox", prompt="OK to send?", title="Send?", home=home)
    clarifies_svc = clarify_svc
    clarifies_svc.create_request(
        "inbox",
        prompt="Which one?",
        title="Pick",
        choices=["A", "B"],
        home=home,
    )
    vault_svc.create_request(
        "inbox",
        kind="secret",
        reason="Need the API key",
        label="API key",
        home=home,
    )

    items = agent_svc.list_pending_human_waits(home=home)
    kinds = {i["kind"] for i in items}
    assert "approval_request" in kinds
    assert "clarify_request" in kinds
    assert "vault_request" in kinds
    assert all(i["bot"] == "inbox" for i in items)
    assert all(i["path"] == "/b/inbox/discussion" for i in items)

    started = client.post(
        "/api/v1/devices/pair",
        json={"name": "PC", "platform": "linux"},
    )
    assert started.status_code == 200
    body = started.get_json()
    assert auth_client.post(f"/api/v1/devices/pair/{body['pair_id']}/approve").status_code == 200
    polled = client.post(
        "/api/v1/devices/pair-poll",
        json={"pair_id": body["pair_id"], "poll_secret": body["poll_secret"]},
    )
    token = polled.get_json()["device_token"]
    pending = client.get(
        "/api/v1/devices/me/pending",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pending.status_code == 200, pending.data
    assert len(pending.get_json()["items"]) >= 3


def test_has_pending_human_wait_matches_list(home):
    bots_svc.create_bot("flag", home=home)
    assert not agent_svc.has_pending_human_wait("flag", home=home)
    approval_svc.create_request("flag", prompt="Go?", home=home)
    assert agent_svc.has_pending_human_wait("flag", home=home)
    assert agent_svc.list_pending_human_waits_for_bot("flag", home=home)
