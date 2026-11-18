"""Bot package disk footprint (Details panel)."""

from pathlib import Path

from autonomous.services import bots as bots_svc
from autonomous.services import bot_package as package_svc
from autonomous.services import chat as chat_svc
from autonomous.services import files as files_svc


def test_package_usage_counts_files_and_chat(home):
    bots_svc.create_bot("pkg", slug="pkg", home=home)
    files_svc.write_text("pkg", "notes/hello.txt", "x" * 1000, home=home)
    shot_dir = home / "bots" / "pkg" / "home" / ".autonomous" / "screenshots"
    shot_dir.mkdir(parents=True)
    (shot_dir / "a.png").write_bytes(b"\x89PNG" + b"0" * 500)
    chat_svc.create_message("pkg", "bonjour package", role="user", home=home)

    usage = package_svc.package_usage("pkg", home=home)
    assert usage["bot"] == "pkg"
    assert usage["files_bytes"] >= 1000
    assert usage["screenshots_bytes"] >= 500
    assert usage["chat_bytes"] > 0
    assert usage["messages"] >= 1
    assert usage["shared_bytes"] >= usage["files_bytes"] + usage["screenshots_bytes"]
    assert usage["total_bytes"] >= usage["host_bytes"]
    assert usage["vm_state"] == "absent"
    assert usage["vm_bytes"] is None


def test_package_api(home, auth_client):
    bots_svc.create_bot("pkgapi", slug="pkgapi", home=home)
    root = Path(home) / "bots" / "pkgapi" / "home"
    (root / "blob.bin").write_bytes(b"abc" * 200)
    r = auth_client.get("/api/v1/bots/pkgapi/package")
    assert r.status_code == 200
    data = r.get_json()
    assert data["bot"] == "pkgapi"
    assert data["files_bytes"] >= 600
    assert data["total_bytes"] >= data["files_bytes"]


def test_container_names_match():
    assert package_svc._container_names_match(
        ["/autonomous-abc"], "autonomous-abc"
    )
    assert package_svc._container_names_match(
        ["autonomous-abc"], "autonomous-abc"
    )
    assert not package_svc._container_names_match(
        ["/autonomous-other"], "autonomous-abc"
    )
