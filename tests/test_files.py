"""Path traversal + agent text read/write + share/attach under ~/shared."""

from pathlib import Path

import pytest

from autonomous.services import bots as bots_svc
from autonomous.services import files as files_svc
from autonomous.services.errors import AutonomousError, Forbidden, NotFound


def test_path_traversal(home):
    bots_svc.create_bot("f1", home=home)
    root = home / "bots" / "f1" / "home"
    (root / "ok.txt").write_text("x")
    entries = files_svc.list_dir("f1", ".", home=home)
    assert any(e["name"] == "ok.txt" for e in entries)
    try:
        files_svc.resolve("f1", "../f1/../../etc/passwd", home=home)
        assert False, "should have raised"
    except Forbidden:
        pass
    p = files_svc.resolve("f1", "ok.txt", home=home)
    assert p == (root / "ok.txt").resolve()


def test_read_write_text(home):
    bots_svc.create_bot("fw", slug="fw", home=home)
    written = files_svc.write_text(
        "fw", "notes/hello.txt", "bonjour\n", home=home
    )
    assert written["path"] == "notes/hello.txt"
    assert written["is_dir"] is False
    got = files_svc.read_text("fw", "notes/hello.txt", home=home)
    assert got["content"] == "bonjour\n"
    assert got["encoding"] == "utf-8"


def test_write_publishes_files_changed(home):
    from autonomous.services.events import BUS

    bots_svc.create_bot("fev", slug="fev", home=home)
    q = BUS.subscribe("*")
    try:
        files_svc.write_text("fev", "live.txt", "x", home=home)
        files_svc.mkdir("fev", ".", "docs", home=home)
        files_svc.delete_path("fev", "live.txt", home=home)
        seen = []
        while True:
            try:
                seen.append(q.get_nowait())
            except Exception:
                break
    finally:
        BUS.unsubscribe("*", q)
    changed = [e for e in seen if e.name == "files.changed" and e.data.get("bot") == "fev"]
    ops = [e.data.get("op") for e in changed]
    assert "write" in ops
    assert "mkdir" in ops
    assert "delete" in ops


def test_read_missing(home):
    bots_svc.create_bot("fm", slug="fm", home=home)
    with pytest.raises(NotFound):
        files_svc.read_text("fm", "nope.txt", home=home)


def test_binary_rejected(home):
    bots_svc.create_bot("fb", slug="fb", home=home)
    root = home / "bots" / "fb" / "home"
    (root / "bin.dat").write_bytes(b"abc\x00def")
    with pytest.raises(AutonomousError) as exc:
        files_svc.read_text("fb", "bin.dat", home=home)
    assert exc.value.code == "binary_file"


def test_files_content_api(home, auth_client):
    bots_svc.create_bot("fapi", slug="fapi", home=home)
    r = auth_client.put(
        "/api/v1/bots/fapi/files/content",
        json={"path": "a.txt", "content": "hi"},
    )
    assert r.status_code == 200
    assert r.get_json()["path"] == "a.txt"
    r2 = auth_client.get("/api/v1/bots/fapi/files/content?path=a.txt")
    assert r2.status_code == 200
    assert r2.get_json()["content"] == "hi"
    r3 = auth_client.get("/api/v1/bots/fapi/files?path=.")
    assert r3.status_code == 200
    assert any(e["name"] == "a.txt" for e in r3.get_json())


def test_share_image_returns_markdown(home, auth_client):
    bots_svc.create_bot("fshare", slug="fshare", home=home)
    root = home / "bots" / "fshare" / "home"
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (root / "pic.png").write_bytes(png)
    out = files_svc.share_image("fshare", "pic.png", caption="un crabe", home=home)
    assert out["ok"] is True
    assert out["embedded"] is True
    assert out["markdown"].startswith("![un crabe](")
    assert "/files/raw?path=" in out["markdown"]
    assert "message_id" not in out
    r = auth_client.get("/api/v1/bots/fshare/files/raw?path=pic.png")
    assert r.status_code == 200
    assert r.content_type.startswith("image/png")


def test_attach_file_on_assistant_bubble(home, auth_client):
    bots_svc.create_bot("fatt", slug="fatt", home=home)
    root = home / "bots" / "fatt" / "home"
    (root / "doc.pdf").write_bytes(b"%PDF-1.4 fake")
    out = files_svc.attach_file("fatt", "doc.pdf", home=home)
    assert out["ok"] is True
    assert out["attached"] is True
    assert out["name"] == "doc.pdf"
    from autonomous.services import chat as chat_svc

    bubble = next(
        m
        for m in chat_svc.list_messages("fatt", limit=10, home=home)
        if m["id"] == out["message_id"]
    )
    assert bubble["role"] == "assistant"
    assert len(bubble["attachments"]) == 1
    assert bubble["attachments"][0]["path"] == "doc.pdf"
    # Images must not go through attach.
    (root / "x.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    with pytest.raises(AutonomousError) as exc:
        files_svc.attach_file("fatt", "x.png", home=home)
    assert exc.value.code == "use_share_image"
    r = auth_client.post(
        "/api/v1/bots/fatt/files/attach",
        json={"path": "doc.pdf"},
    )
    assert r.status_code == 200


def test_write_refuses_overwrite_image(home):
    bots_svc.create_bot("fow", slug="fow", home=home)
    root = home / "bots" / "fow" / "home"
    (root / "x.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    with pytest.raises(AutonomousError) as exc:
        files_svc.write_text("fow", "x.png", "oops", home=home)
    assert exc.value.code == "refuse_overwrite_binary"
