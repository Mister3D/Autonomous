"""Chat + OpenAPI smoke."""

import base64


def test_messages_roundtrip(auth_client):
    auth_client.post("/api/v1/bots", json={"name": "c1"})
    r = auth_client.post("/api/v1/bots/c1/messages", json={"content": "Hello"})
    assert r.status_code == 201
    assert r.json["role"] == "user"
    r = auth_client.get("/api/v1/bots/c1/messages")
    assert len(r.json) == 1
    r = auth_client.delete("/api/v1/bots/c1/messages")
    assert r.status_code == 200
    assert auth_client.get("/api/v1/bots/c1/messages").json == []


def test_message_with_pasted_image(auth_client, home):
    auth_client.post("/api/v1/bots", json={"name": "img1"})
    # 1×1 PNG
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    r = auth_client.post(
        "/api/v1/bots/img1/messages",
        json={"content": "", "attachments": [data_url]},
    )
    assert r.status_code == 201, r.data
    body = r.json
    assert body["attachments"]
    assert body["attachments"][0].startswith("/api/v1/bots/img1/chat/attachments/")
    att = body["attachments"][0].rsplit("/", 1)[-1]
    g = auth_client.get(f"/api/v1/bots/img1/chat/attachments/{att}")
    assert g.status_code == 200
    assert g.data == png


def test_chat_file_upload_and_message(auth_client, home):
    from io import BytesIO
    from pathlib import Path

    auth_client.post("/api/v1/bots", json={"name": "filebot"})
    data = b"hello chat file"
    r = auth_client.post(
        "/api/v1/bots/filebot/chat/files",
        data={"file": (BytesIO(data), "rapport.pdf")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 201, r.data
    att = r.json
    assert att["type"] == "file"
    assert att["name"] == "rapport.pdf"
    assert att["path"].startswith("upload/")
    assert att["path"].endswith("/rapport.pdf")
    # On disk under bot home (=~/shared)
    disk = Path(home) / "bots" / "filebot" / "home" / att["path"]
    assert disk.is_file()
    assert disk.read_bytes() == data

    # Second same name → different uuid folder
    r2 = auth_client.post(
        "/api/v1/bots/filebot/chat/files",
        data={"file": (BytesIO(b"other"), "rapport.pdf")},
        content_type="multipart/form-data",
    )
    assert r2.status_code == 201
    assert r2.json["name"] == "rapport.pdf"
    assert r2.json["path"] != att["path"]

    msg = auth_client.post(
        "/api/v1/bots/filebot/messages",
        json={"content": "voici le doc", "attachments": [att]},
    )
    assert msg.status_code == 201, msg.data
    assert msg.json["attachments"][0]["name"] == "rapport.pdf"
    assert msg.json["attachments"][0]["path"] == att["path"]


def test_message_queued_while_busy(auth_client, home):
    from autonomous.services import bots as bots_svc
    from autonomous.services import chat as chat_svc

    auth_client.post("/api/v1/bots", json={"name": "qbot"})
    bots_svc.patch_bot("qbot", {"status": "busy"}, home=home)
    r = auth_client.post(
        "/api/v1/bots/qbot/messages",
        json={"content": "en attente"},
    )
    assert r.status_code == 201, r.data
    assert r.json["meta"].get("queued") is True
    assert bots_svc.get_bot("qbot", home=home)["status"] == "busy"

    before = r.json["created_at"]
    bots_svc.patch_bot("qbot", {"status": "idle"}, home=home)
    started = chat_svc.drain_queued_user_messages("qbot", home=home)
    # null agent backend in tests → drain clears queue without staying busy
    assert started is True
    msgs = auth_client.get("/api/v1/bots/qbot/messages").json
    queued = [m for m in msgs if m["role"] == "user" and m.get("meta", {}).get("queued")]
    assert queued == []
    sent = [m for m in msgs if m["role"] == "user" and "en attente" in (m.get("content") or "")]
    assert sent and sent[-1]["created_at"] >= before
    # After drain the stamp moves forward (or stays equal if same second).
    assert "queued" not in (sent[-1].get("meta") or {})


def test_queued_stamped_on_create_event(auth_client, home):
    """Busy send must publish message.created already with meta.queued (no blue flash)."""
    from autonomous.services import bots as bots_svc
    from autonomous.services.events import BUS

    auth_client.post("/api/v1/bots", json={"name": "qflash"})
    bots_svc.patch_bot("qflash", {"status": "busy"}, home=home)
    q = BUS.subscribe("qflash")
    try:
        r = auth_client.post(
            "/api/v1/bots/qflash/messages",
            json={"content": "déjà en file"},
        )
        assert r.status_code == 201, r.data
        assert r.json["meta"].get("queued") is True
        created = []
        while True:
            try:
                created.append(q.get_nowait())
            except Exception:
                break
    finally:
        BUS.unsubscribe("qflash", q)
    first_created = next(
        (e for e in created if e.name == "message.created"),
        None,
    )
    assert first_created is not None
    assert first_created.data["message"]["meta"].get("queued") is True


def test_busy_composer_never_mid_run_steers(auth_client, home, monkeypatch):
    """Composer sends while busy always FIFO-queue — never mid-run jump."""
    from autonomous.services import bots as bots_svc
    from autonomous.services import chat as chat_svc

    auth_client.post("/api/v1/bots", json={"name": "qfifo"})
    bots_svc.patch_bot("qfifo", {"status": "busy"}, home=home)

    steered = {"n": 0}

    def fake_steer(bot, prompt, *, home=None):
        steered["n"] += 1
        return True

    monkeypatch.setattr(
        "autonomous.services.agent.steer_mid_run", fake_steer
    )

    first = auth_client.post(
        "/api/v1/bots/qfifo/messages",
        json={"content": "premier"},
    )
    assert first.status_code == 201, first.data
    assert first.json["meta"].get("queued") is True
    assert first.json["meta"].get("mid_run") is not True

    second = auth_client.post(
        "/api/v1/bots/qfifo/messages",
        json={"content": "deuxième"},
    )
    assert second.status_code == 201, second.data
    assert second.json["meta"].get("queued") is True
    assert second.json["meta"].get("mid_run") is not True
    assert steered["n"] == 0

    queued = chat_svc.list_queued_user_messages("qfifo", home=home)
    assert [m["content"] for m in queued] == ["premier", "deuxième"]

    bots_svc.patch_bot("qfifo", {"status": "idle"}, home=home)
    assert chat_svc.drain_queued_user_messages("qfifo", home=home) is True
    left = chat_svc.list_queued_user_messages("qfifo", home=home)
    assert [m["content"] for m in left] == ["deuxième"]


def test_delete_queued_message(auth_client, home):
    from autonomous.services import bots as bots_svc
    from autonomous.services import chat as chat_svc

    auth_client.post("/api/v1/bots", json={"name": "qdel"})
    bots_svc.patch_bot("qdel", {"status": "busy"}, home=home)
    queued = auth_client.post(
        "/api/v1/bots/qdel/messages",
        json={"content": "à annuler"},
    )
    assert queued.status_code == 201, queued.data
    assert queued.json["meta"].get("queued") is True
    msg_id = queued.json["id"]

    gone = auth_client.delete(f"/api/v1/bots/qdel/messages/{msg_id}")
    assert gone.status_code == 200, gone.data
    assert chat_svc.list_queued_user_messages("qdel", home=home) == []
    msgs = auth_client.get("/api/v1/bots/qdel/messages").json
    assert not any(m["id"] == msg_id for m in msgs)

    # Non-queued (or missing) → refuse.
    live = chat_svc.create_message("qdel", "déjà là", role="user", home=home)
    bad = auth_client.delete(f"/api/v1/bots/qdel/messages/{live['id']}")
    assert bad.status_code == 400
    assert bad.json.get("code") == "not_queued" or "queued" in str(bad.json).lower()


def test_message_queued_while_run_slot_held(auth_client, home):
    """A send that arrives while a run owns the slot is queued, even if status is still idle."""
    import threading

    from autonomous.services import agent as agent_svc
    from autonomous.services import chat as chat_svc

    auth_client.post("/api/v1/bots", json={"name": "qslot"})
    settled = threading.Event()
    assert agent_svc._register_run("qslot", settled)
    try:
        first = auth_client.post(
            "/api/v1/bots/qslot/messages", json={"content": "premier"}
        )
        second = auth_client.post(
            "/api/v1/bots/qslot/messages", json={"content": "deuxième"}
        )
        assert first.status_code == 201, first.data
        assert second.status_code == 201, second.data
        assert first.json["meta"].get("queued") is True
        assert second.json["meta"].get("queued") is True
        queued = chat_svc.list_queued_user_messages("qslot", home=home)
        assert [m["content"] for m in queued] == ["premier", "deuxième"]
    finally:
        agent_svc._release_run("qslot", settled)


def test_openapi_generated(auth_client):
    r = auth_client.get("/api/openapi.json")
    assert r.status_code == 200
    paths = r.json["paths"]
    assert "/api/v1/bots" in paths
    assert "/api/v1/events" in paths
    assert "/api/v1/bots/{name}/chat/files" in paths
