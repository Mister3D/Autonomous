"""Home-page Pi and plugin update check."""

from __future__ import annotations

import json

import pytest

from autonomous.services import pi_packages as svc
from autonomous.services.errors import ValidationError


def _agent(tmp_path):
    agent = tmp_path / "agent"
    pkg = agent / "npm" / "node_modules" / "pi-web-access"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text(json.dumps({"version": "0.45.0"}), encoding="utf-8")
    (agent / "install").mkdir()
    (agent / "install" / "current-version").write_text("1.4.0\n", encoding="utf-8")
    (agent / "settings.json").write_text(
        json.dumps({"packages": ["npm:pi-web-access", "git:example/skip"]}),
        encoding="utf-8",
    )
    return agent


def test_is_newer():
    assert svc.is_newer("1.5.2", "1.4.0")
    assert svc.is_newer("0.47.0", "0.45.0")
    assert not svc.is_newer("1.4.0", "1.4.0")
    assert not svc.is_newer("1.4.0", "1.5.2")


def test_check_lists_pi_and_npm_plugin(home, tmp_path, monkeypatch):
    agent = _agent(tmp_path)
    monkeypatch.setattr(svc, "_latest_pi", lambda: "1.5.2")
    monkeypatch.setattr(svc, "_npm_latest", lambda spec: "0.47.0" if spec == "pi-web-access" else "")
    out = svc.check(home=home, force=True, agent=agent)
    by_id = {row["id"]: row for row in out["items"]}
    assert by_id["pi"]["update"] is True
    assert by_id["pi"]["latest"] == "1.5.2"
    assert by_id["npm:pi-web-access"]["update"] is True
    assert by_id["npm:pi-web-access"]["current"] == "0.45.0"
    assert "git:example/skip" not in by_id
    cached = svc.check(home=home, force=False, agent=agent)
    assert cached["cached"] is True


def test_check_up_to_date_hides_nothing_behind(home, tmp_path, monkeypatch):
    agent = _agent(tmp_path)
    monkeypatch.setattr(svc, "_latest_pi", lambda: "1.4.0")
    monkeypatch.setattr(svc, "_npm_latest", lambda spec: "0.45.0")
    out = svc.check(home=home, force=True, agent=agent)
    assert out["updates"] == 0


def test_apply_rejects_unknown_and_empty(home, tmp_path, monkeypatch):
    agent = _agent(tmp_path)
    monkeypatch.setattr(svc.shutil, "which", lambda name: "/usr/bin/pi" if name == "pi" else None)
    with pytest.raises(ValidationError) as empty:
        svc.start_apply([], home=home, agent=agent)
    assert empty.value.code == "nothing_selected"
    with pytest.raises(ValidationError) as unknown:
        svc.start_apply(["npm:not-installed"], home=home, agent=agent)
    assert unknown.value.code == "unknown_package"
    assert svc._apply_running is False


def test_apply_starts_only_checked_argv(home, tmp_path, monkeypatch):
    agent = _agent(tmp_path)
    monkeypatch.setattr(svc.shutil, "which", lambda name: "/usr/bin/pi" if name == "pi" else None)
    launched = {}

    class _Thread:
        def __init__(self, target, name, daemon):
            launched["target"] = target

        def start(self):
            launched["started"] = True

    monkeypatch.setattr(svc.threading, "Thread", _Thread)
    try:
        job = svc.start_apply(["pi", "npm:pi-web-access"], home=home, agent=agent)
    finally:
        svc._apply_running = False
    assert job["id"]
    assert launched["started"] is True
    calls = []
    monkeypatch.setattr(svc, "_agent_dir", lambda: agent)

    def _stream(job_id, argv, home):
        calls.append(argv)
        return 0

    import autonomous.services.setup as setup_svc

    monkeypatch.setattr(setup_svc, "_stream", _stream)
    launched["target"]()
    assert calls == [
        ["/usr/bin/pi", "update", "--self"],
        ["/usr/bin/pi", "update", "npm:pi-web-access"],
    ]


def test_api_lists_updates(home, auth_client, tmp_path, monkeypatch):
    agent = _agent(tmp_path)
    monkeypatch.setattr(svc, "_agent_dir", lambda: agent)
    monkeypatch.setattr(svc, "_latest_pi", lambda: "1.5.2")
    monkeypatch.setattr(svc, "_npm_latest", lambda spec: "0.47.0")
    res = auth_client.get("/api/v1/setup/pi-packages?force=1")
    assert res.status_code == 200
    body = res.get_json()
    ids = [row["id"] for row in body["items"] if row["update"]]
    assert ids == ["pi", "npm:pi-web-access"]
