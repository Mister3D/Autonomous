"""Manager orchestrator: peer list + async delegate."""

from __future__ import annotations

import pytest

from autonomous.services import botmail as botmail_svc
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services.errors import Conflict, Forbidden


def test_create_manager_flag(home):
    m = bots_svc.create_bot("Chef", is_manager=True, home=home)
    assert m["is_manager"] is True
    w = bots_svc.create_bot("Ouvrier", home=home)
    assert w["is_manager"] is False


def test_only_one_manager(home):
    bots_svc.create_bot("Chef", is_manager=True, home=home)
    with pytest.raises(Conflict) as exc:
        bots_svc.create_bot("Autre Chef", is_manager=True, home=home)
    assert exc.value.code == "manager_exists"

    other = bots_svc.create_bot("Sous-fifre", home=home)
    with pytest.raises(Conflict) as exc2:
        bots_svc.patch_bot(other["name"], {"is_manager": True}, home=home)
    assert exc2.value.code == "manager_exists"

    # Demote then promote is allowed.
    bots_svc.patch_bot("chef", {"is_manager": False}, home=home)
    promoted = bots_svc.patch_bot(other["name"], {"is_manager": True}, home=home)
    assert promoted["is_manager"] is True
    assert bots_svc.get_manager(home=home)["name"] == other["name"]


def test_list_peers_requires_manager(home):
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    with pytest.raises(Forbidden) as exc:
        botmail_svc.list_peers("alice", home=home)
    assert exc.value.code == "manager_required"

    bots_svc.patch_bot("alice", {"is_manager": True}, home=home)
    peers = botmail_svc.list_peers("alice", home=home)
    names = {p["name"] for p in peers}
    assert "bob" in names
    assert "alice" not in names


def test_delegate_formats_relaunch_and_delivers(home):
    mgr = bots_svc.create_bot("Manager", is_manager=True, home=home)
    bots_svc.create_bot("Worker", home=home)
    content = botmail_svc.format_delegate_content(
        manager_slug=mgr["name"],
        task="Fetch tomorrow's weather.",
        expect_reply="the weather in one sentence",
    )
    assert "Tell @manager" in content
    assert "NOT waiting" in content
    assert "tomorrow's weather" in content

    botmail_svc.tell(mgr["name"], "worker", content, home=home, origin="test")
    msgs = chat_svc.list_messages("worker", home=home)
    assert any(
        m["role"] == "system"
        and m["meta"].get("mail_kind") == "tell"
        and "Tell @manager" in m["content"]
        for m in msgs
    )


def test_api_peers_and_delegate(auth_client, home):
    auth_client.post("/api/v1/bots", json={"name": "Mgr", "is_manager": True})
    auth_client.post("/api/v1/bots", json={"name": "Helper"})
    r = auth_client.get("/api/v1/bots/mgr/mail/peers")
    assert r.status_code == 200
    assert any(p["name"] == "helper" for p in r.json)

    deny = auth_client.get("/api/v1/bots/helper/mail/peers")
    assert deny.status_code == 403

    d = auth_client.post(
        "/api/v1/bots/mgr/mail/delegate",
        json={"to": "helper", "task": "Count up to 3."},
    )
    assert d.status_code == 201
    helper_msgs = auth_client.get("/api/v1/bots/helper/messages").json
    assert any(
        "Tell @mgr" in (m.get("content") or "")
        and "Count up to 3" in (m.get("content") or "")
        for m in helper_msgs
    )
