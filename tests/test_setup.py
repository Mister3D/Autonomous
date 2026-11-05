"""Setup status, bot-create gate, secret masking, web config writers, job runner."""

from __future__ import annotations

import json
import os
import stat
import time

import pytest

from autonomous.services import settings as settings_svc
from autonomous.services import setup as setup_svc
from autonomous.services import setup_config as cfg

SECRET = "sk-test-SECRET-value-1234"


@pytest.fixture(autouse=True)
def fake_home(tmp_path, monkeypatch):
    """Never touch the real ~/.pi: HOME → tmp."""
    h = tmp_path / "userhome"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    for k in list(os.environ):
        if k.startswith(("AUTONOMOUS_GROUNDER", "AUTONOMOUS_VERIFIER", "AUTONOMOUS_GROUNDING",
                         "GROUNDER_", "AUTONOMOUS_LLM_API_KEY", "MISTER3D_API_KEY")):
            monkeypatch.delenv(k, raising=False)
    setup_svc.invalidate()
    yield h
    setup_svc.invalidate()


def _all_ok(monkeypatch, ready=True):
    def mk(cid, required=True, status="ok"):
        return lambda *a, **k: setup_svc._check(cid, required=required, status=status)
    monkeypatch.setattr(setup_svc, "check_pi", mk("pi"))
    monkeypatch.setattr(setup_svc, "check_llm", mk("llm", status="ok" if ready else "missing"))
    monkeypatch.setattr(setup_svc, "check_docker", mk("docker"))
    monkeypatch.setattr(setup_svc, "check_desk_image", lambda home, ok: setup_svc._check("desk_image", required=True, status="ok"))
    monkeypatch.setattr(setup_svc, "check_grounding", lambda home: [setup_svc._check("grounding", required=False, status="optional")])
    monkeypatch.setattr(setup_svc, "check_companion", lambda home: setup_svc._check("companion", required=False, status="error"))


def test_status_shape_and_ready(auth_client, monkeypatch):
    _all_ok(monkeypatch)
    r = auth_client.get("/api/v1/setup/status?force=1")
    assert r.status_code == 200
    d = r.get_json()
    assert d["ready"] is True  # optional errors don't block
    ids = {c["id"]: c for c in d["checks"]}
    assert ids["pi"]["required"] and not ids["companion"]["required"]
    for c in d["checks"]:
        assert set(c) >= {"id", "label", "status", "details", "required", "action"}


def test_status_requires_login(client):
    assert client.get("/api/v1/setup/status").status_code == 401


def test_create_bot_409_when_not_ready(auth_client, home, monkeypatch):
    settings_svc.set_many({"agent_backend": "pi"}, home=home)
    _all_ok(monkeypatch, ready=False)
    r = auth_client.post("/api/v1/bots", json={"name": "Gate"})
    assert r.status_code == 409
    body = r.get_json()
    assert "Setup is not finished" in body["message"]
    assert "llm" in body["message"]
    # Becomes allowed once ready (cache invalidated).
    _all_ok(monkeypatch, ready=True)
    setup_svc.invalidate()
    monkeypatch.setattr("autonomous.services.pi_status.list_models", lambda *a, **k: [])
    r = auth_client.post("/api/v1/bots", json={"name": "Gate"})
    assert r.status_code == 201, r.get_json()


def test_status_cached(home, monkeypatch):
    calls = []
    monkeypatch.setattr(setup_svc, "compute", lambda h=None: calls.append(1) or {"ready": True, "checks": []})
    setup_svc.status(home)
    setup_svc.status(home)
    assert len(calls) == 1
    setup_svc.status(home, force=True)
    assert len(calls) == 2


def test_mask():
    assert cfg.mask("") == {"set": False, "hint": ""}
    m = cfg.mask(SECRET)
    assert m["set"] and m["hint"] == "…1234"
    assert cfg.mask("short")["hint"] == ""


def test_llm_save_preserves_and_masks(auth_client, fake_home):
    path = fake_home / ".pi" / "agent" / "models.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"providers": {"other": {"baseUrl": "http://x/v1", "apiKey": "KEEP", "models": [{"id": "a"}]}}, "extra": 1}))
    r = auth_client.put("/api/v1/setup/llm", json={
        "provider": "mine", "base_url": "http://llm.test/v1/", "api_key": SECRET,
        "model": "m1", "images": True})
    assert r.status_code == 200, r.get_json()
    assert SECRET not in r.get_data(as_text=True)
    data = json.loads(path.read_text())
    assert data["extra"] == 1 and data["providers"]["other"]["apiKey"] == "KEEP"
    assert list(data["providers"])[0] == "mine"
    assert data["providers"]["mine"]["apiKey"] == SECRET
    assert data["providers"]["mine"]["models"][0]["input"] == ["text", "image"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # Empty key keeps the stored one.
    auth_client.put("/api/v1/setup/llm", json={"provider": "mine", "base_url": "http://llm.test/v1", "api_key": "", "model": "m1"})
    assert json.loads(path.read_text())["providers"]["mine"]["apiKey"] == SECRET
    g = auth_client.get("/api/v1/setup/llm")
    text = g.get_data(as_text=True)
    assert SECRET not in text and g.get_json()["primary"]["api_key"]["hint"] == "…1234"


def test_grounding_save_masks_and_env_readonly(auth_client, home, monkeypatch):
    r = auth_client.put("/api/v1/setup/grounding", json={
        "enabled": True, "grounder_url": "http://tars.test/v1", "grounder_model": "ui-tars",
        "grounder_token": SECRET})
    assert r.status_code == 200
    assert SECRET not in r.get_data(as_text=True)
    f = home / "grounder.env"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert f"AUTONOMOUS_GROUNDER_TOKEN={SECRET}" in f.read_text()
    from autonomous.services import grounding as g_svc
    assert g_svc.is_configured(home)
    # Toggle off keeps URL but disables grounding.
    auth_client.put("/api/v1/setup/grounding", json={"enabled": False, "grounder_token": ""})
    assert not g_svc.is_configured(home)
    assert SECRET in f.read_text() and "tars.test" in f.read_text()
    monkeypatch.setenv("AUTONOMOUS_GROUNDER_MODEL", "from-env")
    v = auth_client.get("/api/v1/setup/grounding").get_json()["fields"]
    assert v["grounder_model"] == {"value": "from-env", "source": "env", "readonly": True, "env": "AUTONOMOUS_GROUNDER_MODEL"}
    assert v["grounder_token"]["set"] and v["grounder_token"]["hint"] == "…1234"
    auth_client.put("/api/v1/setup/grounding", json={"grounder_model": "ignored"})
    assert "ignored" not in f.read_text()


def test_job_runner_fake_command(home, monkeypatch):
    from autonomous.services import jobs as jobs_svc
    monkeypatch.setitem(setup_svc.JOB_COMMANDS, "pi_install", lambda h: ["sh", "-c", "echo hello; echo world"])
    monkeypatch.setattr(setup_svc.shutil, "which", lambda n: "/usr/bin/" + n)
    job = setup_svc.start_job("pi_install", home)
    with pytest.raises(Exception):
        setup_svc.start_job("pi_install", home)  # one at a time
    for _ in range(100):
        j = jobs_svc.get_job(job["id"], home=home)
        if j["state"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert j["state"] == "done"
    assert "hello" in j["log"] and "world" in j["log"]
    assert "pi_install" not in setup_svc._running


def test_unknown_job_rejected(auth_client):
    r = auth_client.post("/api/v1/setup/jobs/rm-rf")
    assert r.status_code == 400
