"""Generic user approval cards (Accept / Refuse)."""

from __future__ import annotations

from autonomous.services import approvals as approval_svc
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc


def test_create_and_approve(home, auth_client):
    bots_svc.create_bot("alice", label="Alice", home=home)
    req = approval_svc.create_request(
        "alice",
        prompt="Lancer la commande rm -rf /tmp/x ?",
        title="Commande",
        home=home,
    )
    assert req["state"] == "pending"
    assert bots_svc.get_bot("alice", home=home)["status"] == "waiting"

    msgs = chat_svc.list_messages("alice", home=home)
    card = next(m for m in msgs if m["meta"].get("kind") == "approval_request")
    assert card["meta"]["request_id"] == req["id"]
    assert "rm -rf" in card["meta"]["prompt"]

    out = approval_svc.resolve_request(req["id"], action="approve", home=home)
    assert out["state"] == "approved"
    assert out["result"]["approved"] is True


def test_deny_and_chat_cancel(home, auth_client):
    bots_svc.create_bot("bob", label="Bob", home=home)
    req = approval_svc.create_request(
        "bob", prompt="Installer un paquet ?", home=home
    )
    denied = approval_svc.resolve_request(req["id"], action="deny", home=home)
    assert denied["state"] == "denied"

    req2 = approval_svc.create_request(
        "bob", prompt="Encore ?", home=home
    )
    cancelled = approval_svc.cancel_pending_for_human_message(
        "bob", "fais-le sans sudo", home=home
    )
    assert len(cancelled) == 1
    assert cancelled[0]["state"] == "cancelled"
    assert cancelled[0]["result"]["human_redirect"] is True
    assert approval_svc.get_request(req2["id"], home=home)["state"] == "cancelled"


def test_api_flow(home, auth_client):
    bots_svc.create_bot("cara", label="Cara", home=home)
    r = auth_client.post(
        "/api/v1/approvals/requests",
        json={"bot": "cara", "prompt": "OK pour continuer ?", "title": "Test"},
    )
    assert r.status_code == 201
    body = r.get_json()
    assert body["state"] == "pending"

    g = auth_client.get(f"/api/v1/approvals/requests/{body['id']}")
    assert g.status_code == 200

    done = auth_client.post(
        f"/api/v1/approvals/requests/{body['id']}/resolve",
        json={"action": "approve"},
    )
    assert done.status_code == 200
    assert done.get_json()["state"] == "approved"
