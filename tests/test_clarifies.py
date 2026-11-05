"""Structured clarify cards (choices / short text)."""

from __future__ import annotations

from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services import clarifies as clarify_svc


def test_choice_and_text(home):
    bots_svc.create_bot("alice", label="Alice", home=home)
    req = clarify_svc.create_request(
        "alice",
        prompt="Quel format ?",
        title="Format",
        choices=["PDF", "Markdown"],
        home=home,
    )
    assert req["state"] == "pending"
    assert req["allow_text"] is False
    assert bots_svc.get_bot("alice", home=home)["status"] == "waiting"

    msgs = chat_svc.list_messages("alice", home=home)
    card = next(m for m in msgs if m["meta"].get("kind") == "clarify_request")
    assert card["meta"]["choices"] == ["PDF", "Markdown"]

    out = clarify_svc.resolve_request(req["id"], choice="PDF", home=home)
    assert out["state"] == "answered"
    assert out["result"]["answer"] == "PDF"
    assert out["result"]["via"] == "choice"

    text_req = clarify_svc.create_request(
        "alice",
        prompt="Quel nom ?",
        home=home,
    )
    assert text_req["allow_text"] is True
    assert text_req["choices"] == []
    answered = clarify_svc.resolve_request(
        text_req["id"], text="Nora", home=home
    )
    assert answered["result"]["via"] == "text"
    assert answered["result"]["answer"] == "Nora"


def test_chat_cancels(home):
    bots_svc.create_bot("bob", label="Bob", home=home)
    req = clarify_svc.create_request(
        "bob",
        prompt="Encore ?",
        choices=["Oui", "Non"],
        allow_text=True,
        home=home,
    )
    assert req["allow_text"] is True
    chat_svc.send_message("bob", "fais les deux", home=home)
    cancelled = clarify_svc.get_request(req["id"], home=home)
    assert cancelled["state"] == "cancelled"
    assert cancelled["result"]["human_redirect"] is True
    assert "deux" in cancelled["result"]["message"]


def test_api_flow(auth_client, home):
    bots_svc.create_bot("cara", label="Cara", home=home)
    r = auth_client.post(
        "/api/v1/clarifies/requests",
        json={
            "bot": "cara",
            "prompt": "Quel canal ?",
            "title": "Canal",
            "choices": ["Mail", "Chat"],
        },
    )
    assert r.status_code == 201, r.data
    body = r.get_json()
    assert body["state"] == "pending"

    bad = auth_client.post(
        f"/api/v1/clarifies/requests/{body['id']}/resolve",
        json={"choice": "SMS"},
    )
    assert bad.status_code == 400

    done = auth_client.post(
        f"/api/v1/clarifies/requests/{body['id']}/resolve",
        json={"choice": "Chat"},
    )
    assert done.status_code == 200
    assert done.get_json()["state"] == "answered"
    assert done.get_json()["result"]["answer"] == "Chat"
