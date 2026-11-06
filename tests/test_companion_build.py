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


def test_docker_run_uses_stdbuf_for_live_log():
    argv = build_svc.docker_run_argv(Path("/src"), Path("/wd"), build_svc.LINUX_GNU, "img:tag")
    script = argv[argv.index("sh") + 2]
    assert "stdbuf -oL -eL cargo build" in script
