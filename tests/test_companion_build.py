"""Companion build status exposes a live build.log tail for the UI."""

from __future__ import annotations

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


def test_docker_run_uses_stdbuf_for_live_log():
    argv = build_svc.docker_run_argv(Path("/src"), Path("/wd"), build_svc.LINUX_GNU, "img:tag")
    script = argv[argv.index("sh") + 2]
    assert "stdbuf -oL -eL cargo build" in script
