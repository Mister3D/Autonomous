"""Per-bot notebook: orders, open lines, notes, prompt trailer."""

from __future__ import annotations

import pytest

from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services import notebook as notebook_svc
from autonomous.services import settings as settings_svc
from autonomous.services import vault as vault_svc
from autonomous.services.chat_export import transcript_blocks
from autonomous.services.errors import ValidationError


def test_order_and_open_are_in_the_prompt_note_body_is_not(home):
    bots_svc.create_bot("ada", label="Ada", home=home)
    order = notebook_svc.remember(
        "ada",
        kind="order",
        title="proxy",
        body="Always verify the proxy is enabled.",
        home=home,
    )
    notebook_svc.remember(
        "ada",
        kind="open",
        title="server",
        body="Server: the nginx update is still to do.",
        home=home,
    )
    note = notebook_svc.remember(
        "ada",
        kind="note",
        title="push-server",
        body="tinyproxy on port 8888, decided in November.",
        home=home,
    )
    prompt = notebook_svc.attach_prompt("Il restait des choses à faire.", "ada", home=home)
    assert prompt.startswith("Il restait des choses à faire.")
    assert "Always verify the proxy is enabled." in prompt
    assert "nginx update is still to do" in prompt
    assert "push-server" in prompt
    assert "tinyproxy" not in prompt
    assert order["id"] in prompt
    full = notebook_svc.get_entry("ada", note["id"], home=home)
    assert "tinyproxy" in full["body"]


def test_same_title_updates_and_unchanged_is_quiet(home):
    bots_svc.create_bot("ada", label="Ada", home=home)
    settings_svc.set_value("locale", "fr", home=home)
    first = notebook_svc.remember(
        "ada",
        kind="order",
        title="proxy",
        body="Vérifie le proxy.",
        home=home,
    )
    second = notebook_svc.remember(
        "ada",
        kind="order",
        title="proxy",
        body="Vérifie toujours que le proxy est activé.",
        home=home,
    )
    assert second["id"] == first["id"]
    assert len(notebook_svc.list_entries("ada", home=home)) == 1
    quiet = notebook_svc.remember(
        "ada",
        kind="order",
        title="proxy",
        body="Vérifie toujours que le proxy est activé.",
        home=home,
    )
    assert quiet["id"] == first["id"]
    notices = [
        m
        for m in chat_svc.list_messages("ada", home=home)
        if (m.get("meta") or {}).get("kind") == "notebook"
    ]
    assert len(notices) == 2
    assert notices[-1]["content"].startswith("Mémorisé")
    assert "activé" in notices[-1]["content"]


def test_close_drops_the_open_line(home):
    bots_svc.create_bot("ada", label="Ada", home=home)
    row = notebook_svc.remember(
        "ada",
        kind="open",
        title="server",
        body="Server: nginx still to do.",
        home=home,
    )
    notebook_svc.close_entry("ada", row["id"], home=home)
    assert notebook_svc.prompt_trailer("ada", home=home) == ""
    assert notebook_svc.list_entries("ada", home=home) == []


def test_other_bot_does_not_see_it(home):
    bots_svc.create_bot("ada", label="Ada", home=home)
    bots_svc.create_bot("bea", label="Bea", home=home)
    notebook_svc.remember(
        "ada",
        kind="order",
        title="proxy",
        body="Always verify the proxy is enabled.",
        home=home,
    )
    assert notebook_svc.attach_prompt("hello", "bea", home=home) == "hello"
    assert "proxy" not in notebook_svc.prompt_trailer("bea", home=home)


def test_cap_and_vault_secret(home):
    bots_svc.create_bot("ada", label="Ada", home=home)
    for i in range(12):
        notebook_svc.remember(
            "ada",
            kind="order",
            title=f"rule-{i}",
            body=f"Rule number {i}.",
            home=home,
        )
    with pytest.raises(ValidationError) as raised:
        notebook_svc.remember(
            "ada",
            kind="order",
            title="rule-extra",
            body="One rule too many.",
            home=home,
        )
    assert raised.value.code == "notebook_full"
    vault_svc.create_entry(label="proxy", kind="secret", secret="s3cret-proxy", home=home)
    with pytest.raises(ValidationError) as secret:
        notebook_svc.remember(
            "ada",
            kind="note",
            title="proxy-pass",
            body="the proxy password is s3cret-proxy",
            home=home,
        )
    assert secret.value.code == "notebook_secret"


def test_api_round_trip_and_delete_bot(home, auth_client):
    bots_svc.create_bot("ada", label="Ada", home=home)
    saved = auth_client.post(
        "/api/v1/bots/ada/notebook",
        json={"kind": "open", "title": "server", "body": "nginx still to do"},
    )
    assert saved.status_code == 200
    entry_id = saved.get_json()["id"]
    listed = auth_client.get("/api/v1/bots/ada/notebook")
    assert listed.status_code == 200
    assert listed.get_json()[0]["body"] == "nginx still to do"
    one = auth_client.get(f"/api/v1/bots/ada/notebook/{entry_id}")
    assert one.status_code == 200
    assert one.get_json()["title"] == "server"
    gone = auth_client.delete(f"/api/v1/bots/ada/notebook/{entry_id}")
    assert gone.status_code == 200
    assert auth_client.get("/api/v1/bots/ada/notebook").get_json() == []

    notebook_svc.remember(
        "ada", kind="note", title="keep", body="details", home=home
    )
    bots_svc.delete_bot("ada", home=home, destroy_desk=False)
    bots_svc.create_bot("ada", label="Ada", home=home)
    assert notebook_svc.list_entries("ada", home=home) == []


def test_notebook_tools_stay_out_of_the_export(home):
    blocks = transcript_blocks(
        [
            {
                "id": "1",
                "role": "event",
                "content": "notebook_remember",
                "created_at": "2026-11-15T12:00:00+00:00",
                "meta": {
                    "kind": "tool",
                    "tool_name": "notebook_remember",
                    "status": "done",
                },
                "attachments": [],
            },
            {
                "id": "2",
                "role": "system",
                "content": "Still to do: nginx",
                "created_at": "2026-11-15T12:00:01+00:00",
                "meta": {"kind": "notebook", "action": "set", "tier": "open"},
                "attachments": [],
            },
        ]
    )
    flat = " ".join(str(b) for b in blocks)
    assert "notebook_remember" not in flat
    assert "Still to do: nginx" in flat
