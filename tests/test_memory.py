"""Shared household memory: core vs browse, proposals, opt-out."""

from __future__ import annotations

from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services import memory as memory_svc
from autonomous.services.errors import ValidationError


def test_upsert_core_and_browse(home):
    core = memory_svc.upsert_entry(
        key="preferred_name",
        value="Alex",
        label="Prénom",
        tier="core",
        home=home,
    )
    assert core["tier"] == "core"
    browse = memory_svc.upsert_entry(
        key="address",
        value="12 rue Example",
        label="Adresse",
        tier="browse",
        home=home,
    )
    assert browse["tier"] == "browse"
    listed = memory_svc.list_entries(home=home)
    assert {e["key"] for e in listed} == {"preferred_name", "address"}
    assert memory_svc.list_entries(tier="core", home=home)[0]["value"] == "Alex"
    hits = memory_svc.search_entries("rue", home=home)
    assert hits[0]["key"] == "address"


def test_core_block_once_per_conversation_respects_access(home):
    """Core facts are for system prompt at conversation start, not every message."""
    memory_svc.upsert_entry(
        key="preferred_name",
        value="Alex",
        tier="core",
        home=home,
    )
    bots_svc.create_bot("alice", label="Alice", home=home)
    bots_svc.create_bot("lone", label="Lone", memory_access=False, home=home)
    prefix = memory_svc.prompt_prefix_for_bot("alice", home=home)
    assert "Alex" in prefix
    assert "preferred_name" in prefix
    assert memory_svc.prompt_prefix_for_bot("lone", home=home) == ""


def test_count_pending_proposals(home, auth_client):
    assert memory_svc.count_proposals(home=home) == 0
    bots_svc.create_bot("bob", label="Bob", home=home)
    memory_svc.propose(
        "bob",
        action="set",
        key="preferred_name",
        value="Alex",
        home=home,
    )
    assert memory_svc.count_proposals(home=home) == 1
    listed = auth_client.get("/api/v1/memory/proposals/count")
    assert listed.status_code == 200
    assert listed.get_json()["count"] == 1


def test_propose_non_blocking_and_resolve(home, auth_client):
    bots_svc.create_bot("bob", label="Bob", home=home)
    prop = memory_svc.propose(
        "bob",
        action="set",
        key="preferred_name",
        value="Alex",
        label="Prénom",
        tier="core",
        reason="He said: call me Alex",
        home=home,
    )
    assert prop["state"] == "pending"
    bot = bots_svc.get_bot("bob", home=home)
    assert bot["status"] != "waiting"

    msgs = chat_svc.list_messages("bob", home=home)
    card = next(m for m in msgs if m["meta"].get("kind") == "memory_proposal")
    assert card["meta"]["proposal_id"] == prop["id"]
    assert "Alex" in card["content"]

    resolved = memory_svc.resolve_proposal(prop["id"], action="approve", home=home)
    assert resolved["state"] == "approved"
    entry = memory_svc.get_entry("preferred_name", home=home)
    assert entry["value"] == "Alex"
    assert entry["tier"] == "core"

    denied = memory_svc.propose(
        "bob",
        action="set",
        key="nickname",
        value="Pete",
        tier="browse",
        home=home,
    )
    memory_svc.resolve_proposal(denied["id"], action="deny", home=home)
    try:
        memory_svc.get_entry("nickname", home=home)
        assert False, "nickname should not exist"
    except Exception as exc:
        assert getattr(exc, "code", None) == "memory_missing" or "not found" in str(exc).lower()


def test_opt_out_blocks_tools(home, auth_client):
    bots_svc.create_bot("closed", label="Closed", memory_access=False, home=home)
    memory_svc.upsert_entry(key="preferred_name", value="Alex", tier="core", home=home)
    try:
        memory_svc.propose(
            "closed",
            action="set",
            key="x",
            value="y",
            home=home,
        )
        assert False, "expected deny"
    except ValidationError as exc:
        assert exc.code == "memory_denied"

    r = auth_client.get("/api/v1/memory/entries?bot=closed")
    assert r.status_code == 400
    assert r.get_json().get("code") == "memory_denied" or "memory" in str(r.get_json()).lower()


def test_api_crud_and_create_bot_flag(home, auth_client):
    r = auth_client.post(
        "/api/v1/memory/entries",
        json={
            "key": "preferred_name",
            "value": "Alex",
            "label": "Prénom",
            "tier": "core",
        },
    )
    assert r.status_code == 201
    assert r.get_json()["value"] == "Alex"

    listed = auth_client.get("/api/v1/memory/entries")
    assert listed.status_code == 200
    assert any(e["key"] == "preferred_name" for e in listed.get_json())

    created = auth_client.post(
        "/api/v1/bots",
        json={"name": "MemBot", "memory_access": False},
    )
    assert created.status_code == 201
    body = created.get_json()
    assert body["memory_access"] is False

    patched = auth_client.patch(
        f"/api/v1/bots/{body['name']}",
        json={"memory_access": True},
    )
    assert patched.status_code == 200
    assert patched.get_json()["memory_access"] is True
