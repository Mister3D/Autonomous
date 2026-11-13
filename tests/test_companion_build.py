"""Companion build status exposes a live build.log tail for the UI."""

from __future__ import annotations

import hashlib
from pathlib import Path

from autonomous.services import companion_build as build_svc


def test_read_log_tails_and_truncates_lines(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("AUTONOMOUS_HOME", str(home))
    log = build_svc.work_dir(home) / "build.log"
    log.write_text("\n".join(f"line-{i}" for i in range(300)) + "\n" + ("x" * 600), encoding="utf-8")
    lines = build_svc.read_log(home, max_lines=10)
    assert len(lines) == 10
    assert lines[0] == "line-291"
    assert lines[-1] == "x" * 500


def test_status_includes_log(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("AUTONOMOUS_HOME", str(home))
    monkeypatch.setenv("AUTONOMOUS_COMPANION_DOCKER", "0")
    (build_svc.work_dir(home) / "build.log").write_text("=== cargo\nok\n", encoding="utf-8")
    st = build_svc.status(home)
    assert st["log"] == ["=== cargo", "ok"]


def test_download_filename_follows_autonomous_and_drops_the_triple():
    from autonomous import __version__

    windows = build_svc.download_filename(__version__, windows=True)
    linux = build_svc.download_filename(__version__, windows=False)
    assert windows == f"autonomous-companion-{__version__}.exe"
    assert linux == f"autonomous-companion-{__version__}"
    assert "windows" not in windows
    assert "gnu" not in linux
    assert build_svc.download_filename("../0.1.20", windows=True) == "autonomous-companion-0.1.20.exe"


def test_download_response_uses_the_short_name(auth_client, home):
    from autonomous import __version__

    digest = "abc123"
    triple = build_svc.WINDOWS_GNU
    dest = build_svc.work_dir(home) / "dist" / digest / triple
    dest.mkdir(parents=True)
    exe = dest / "autonomous-companion.exe"
    exe.write_bytes(b"MZ")
    build_svc._write_status(home, {
        "state": "ready",
        "hash": digest,
        "host": triple,
        "artifacts": [{
            "target": triple,
            "platform": "windows",
            "filename": exe.name,
        }],
    })
    status = auth_client.get("/api/v1/companion/build")
    assert status.status_code == 200
    body = status.get_json()
    assert body["version"] == __version__
    assert body["artifacts"][0]["download_name"] == f"autonomous-companion-{__version__}.exe"
    downloaded = auth_client.get(f"/api/v1/companion/download/{triple}")
    assert downloaded.status_code == 200
    disposition = downloaded.headers["Content-Disposition"]
    assert f"autonomous-companion-{__version__}.exe" in disposition
    assert "x86_64" not in disposition


def test_paired_device_downloads_its_own_platform(auth_client, client, pairing_on, home):
    started = client.post(
        "/api/v1/devices/pair",
        json={"name": "Bureau", "platform": "windows"},
    )
    assert started.status_code == 200
    body = started.get_json()
    assert auth_client.post(f"/api/v1/devices/pair/{body['pair_id']}/approve").status_code == 200
    polled = client.post(
        "/api/v1/devices/pair-poll",
        json={"pair_id": body["pair_id"], "poll_secret": body["poll_secret"]},
    )
    token = polled.get_json()["device_token"]
    digest = build_svc.source_hash()
    triple = build_svc.WINDOWS_GNU
    dest = build_svc.work_dir(home) / "dist" / digest / triple
    dest.mkdir(parents=True)
    payload = b"new-companion"
    exe = dest / "autonomous-companion.exe"
    exe.write_bytes(payload)
    build_svc._write_status(home, {
        "state": "ready",
        "hash": digest,
        "artifacts": [{"target": triple, "platform": "windows", "filename": exe.name}],
    })
    headers = {"Authorization": f"Bearer {token}"}
    info = client.get("/api/v1/devices/me/update", headers=headers)
    assert info.status_code == 200
    offer = info.get_json()
    assert offer["state"] == "ready"
    assert offer["sha256"] == hashlib.sha256(payload).hexdigest()
    assert offer["size"] == len(payload)
    assert offer["platform"] == "windows"
    binary = client.get("/api/v1/devices/me/update/binary", headers=headers)
    assert binary.status_code == 200
    assert binary.data == payload
    assert auth_client.get("/api/v1/devices/me/update").status_code == 401

    linux = client.post(
        "/api/v1/devices/pair",
        json={"name": "Portable", "platform": "linux"},
    )
    linux_body = linux.get_json()
    auth_client.post(f"/api/v1/devices/pair/{linux_body['pair_id']}/approve")
    linux_token = client.post(
        "/api/v1/devices/pair-poll",
        json={"pair_id": linux_body["pair_id"], "poll_secret": linux_body["poll_secret"]},
    ).get_json()["device_token"]
    missing = client.get(
        "/api/v1/devices/me/update",
        headers={"Authorization": f"Bearer {linux_token}"},
    )
    assert missing.status_code == 404


def test_update_waits_until_the_compile_finishes():
    assert build_svc._update_pending({"state": "building"}) is True
    waiting = {"stale": True, "enabled": True, "toolchain": True}
    assert build_svc._update_pending({"state": "ready", **waiting}) is True
    assert build_svc._update_pending({"state": "interrupted", **waiting}) is True
    assert build_svc._update_pending({"state": "failed", **waiting}) is False
    assert build_svc._update_pending({
        "state": "ready", "stale": True, "enabled": False, "toolchain": True,
    }) is False
    assert build_svc._update_pending({
        "state": "ready", "stale": False, "enabled": True, "toolchain": True,
    }) is False


def test_stale_binary_is_not_offered_while_a_build_can_catch_up(home):
    digest = "not-the-source"
    triple = build_svc.WINDOWS_GNU
    dest = build_svc.work_dir(home) / "dist" / digest / triple
    dest.mkdir(parents=True)
    exe = dest / "autonomous-companion.exe"
    exe.write_bytes(b"previous")
    build_svc._write_status(home, {
        "state": "ready",
        "hash": digest,
        "artifacts": [{"target": triple, "platform": "windows", "filename": exe.name}],
    })
    offer = build_svc.update_offer("windows", home)
    assert build_svc.status(home)["stale"] is True
    assert offer["state"] == "building"
    assert "sha256" not in offer


def test_device_update_refuses_the_old_binary_while_compiling(
    auth_client, client, pairing_on, home,
):
    started = client.post(
        "/api/v1/devices/pair",
        json={"name": "Bureau", "platform": "windows"},
    )
    body = started.get_json()
    auth_client.post(f"/api/v1/devices/pair/{body['pair_id']}/approve")
    token = client.post(
        "/api/v1/devices/pair-poll",
        json={"pair_id": body["pair_id"], "poll_secret": body["poll_secret"]},
    ).get_json()["device_token"]
    digest = "not-the-source"
    triple = build_svc.WINDOWS_GNU
    dest = build_svc.work_dir(home) / "dist" / digest / triple
    dest.mkdir(parents=True)
    exe = dest / "autonomous-companion.exe"
    exe.write_bytes(b"previous")
    build_svc._write_status(home, {
        "state": "ready",
        "hash": digest,
        "artifacts": [{"target": triple, "platform": "windows", "filename": exe.name}],
    })
    headers = {"Authorization": f"Bearer {token}"}
    info = client.get("/api/v1/devices/me/update", headers=headers)
    assert info.status_code == 200
    assert info.get_json()["state"] == "building"
    binary = client.get("/api/v1/devices/me/update/binary", headers=headers)
    assert binary.status_code == 409


def test_docker_run_uses_stdbuf_for_live_log():
    argv = build_svc.docker_run_argv(Path("/src"), Path("/wd"), build_svc.LINUX_GNU, "img:tag")
    script = argv[argv.index("sh") + 2]
    assert "stdbuf -oL -eL cargo build" in script
