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


def test_openapi_generated(auth_client):
    r = auth_client.get("/api/openapi.json")
    assert r.status_code == 200
    paths = r.json["paths"]
    assert "/api/v1/bots" in paths
    assert "/api/v1/events" in paths
    assert "/api/v1/bots/{name}/chat/files" in paths
