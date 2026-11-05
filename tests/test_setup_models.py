"""POST /setup/llm/models and /setup/grounding/models (HTTP mocked, key never echoed)."""

from __future__ import annotations

import json
import os

import pytest

from autonomous.services import setup as setup_svc
from autonomous.services import setup_config as cfg

STORED = "sk-stored-SECRET-key-9876"
TYPED = "sk-typed-SECRET-key-5555"


@pytest.fixture(autouse=True)
def fake_home(tmp_path, monkeypatch):
    h = tmp_path / "userhome"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    for k in list(os.environ):
        if k.startswith(("AUTONOMOUS_GROUNDER", "AUTONOMOUS_VERIFIER", "AUTONOMOUS_GROUNDING",
                         "GROUNDER_", "AUTONOMOUS_LLM_API_KEY", "MISTER3D_API_KEY")):
            monkeypatch.delenv(k, raising=False)
    p = h / ".pi" / "agent" / "models.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"providers": {"mine": {"baseUrl": "http://llm.test/v1", "apiKey": STORED,
                                                      "models": [{"id": "m1"}]}}}))
    setup_svc.invalidate()
    yield h


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake(url, key="", timeout=6.0):
        seen.append({"url": url, "key": key, "timeout": timeout})
        if key == "bad":
            return 401, None
        if "slow" in url:
            return 0, {"error": "timed out"}
        return 200, {"data": [{"id": "zeta"}, {"id": "alpha"}, {"id": "alpha"}]}

    monkeypatch.setattr(cfg, "http_get_json", fake)
    return seen


def _assert_no_secret(resp):
    text = resp.get_data(as_text=True)
    assert STORED not in text and TYPED not in text


@pytest.mark.parametrize("typed", ["", "…9876", "...9876"])
def test_llm_models_reuses_stored_key(auth_client, calls, typed):
    r = auth_client.post("/api/v1/setup/llm/models",
                         json={"provider": "mine", "base_url": "http://llm.test/v1/", "api_key": typed})
    assert r.status_code == 200
    assert r.get_json() == {"models": ["alpha", "zeta"]}
    assert calls[-1]["key"] == STORED
    assert calls[-1]["url"] == "http://llm.test/v1/models"
    assert calls[-1]["timeout"] == cfg.MODELS_TIMEOUT
    _assert_no_secret(r)


def test_llm_models_typed_key(auth_client, calls):
    r = auth_client.post("/api/v1/setup/llm/models",
                         json={"provider": "mine", "base_url": "http://llm.test/v1", "api_key": TYPED})
    assert r.status_code == 200 and calls[-1]["key"] == TYPED
    _assert_no_secret(r)


def test_llm_models_errors(auth_client, calls):
    r = auth_client.post("/api/v1/setup/llm/models", json={"base_url": "http://llm.test/v1", "api_key": "bad"})
    assert r.status_code == 502
    body = r.get_json()
    assert body["models"] == [] and body["code"] == "unauthorized" and "401" in body["message"]
    r = auth_client.post("/api/v1/setup/llm/models", json={"base_url": "http://slow.test/v1", "api_key": TYPED})
    assert r.status_code == 504 and r.get_json()["code"] == "timeout"
    _assert_no_secret(r)
    r = auth_client.post("/api/v1/setup/llm/models", json={"base_url": "ftp://x", "api_key": TYPED})
    assert r.status_code == 400 and r.get_json()["code"] == "invalid_url"


def test_grounding_models_stored_token(auth_client, calls):
    auth_client.put("/api/v1/setup/grounding", json={
        "enabled": True, "grounder_url": "http://tars.test/v1", "grounder_model": "ui-tars",
        "grounder_token": STORED})
    r = auth_client.post("/api/v1/setup/grounding/models", json={"kind": "grounder", "url": "", "token": "…9876"})
    assert r.status_code == 200 and r.get_json()["models"] == ["alpha", "zeta"]
    assert calls[-1]["key"] == STORED and calls[-1]["url"] == "http://tars.test/v1/models"
    _assert_no_secret(r)
    r = auth_client.post("/api/v1/setup/grounding/models", json={"kind": "verifier"})
    assert r.status_code == 400 and r.get_json()["code"] == "invalid_kind"
    r = auth_client.post("/api/v1/setup/grounding/models", json={"kind": "nope"})
    assert r.status_code == 400


def test_fresh_instance_grounding_disabled(auth_client):
    f = auth_client.get("/api/v1/setup/grounding").get_json()["fields"]
    assert f["enabled"]["value"] is False
    assert f["grounder_url"]["value"] == ""
    assert not any(k.startswith("verifier") for k in f)


def test_url_without_flag_stays_enabled(auth_client, home):
    (home / "grounder.env").write_text("AUTONOMOUS_GROUNDER_URL=http://tars.test/v1\n")
    f = auth_client.get("/api/v1/setup/grounding").get_json()["fields"]
    assert f["enabled"]["value"] is True


def test_verifier_uses_llm_config(fake_home, home):
    from autonomous.services import grounding as g_svc

    p = fake_home / ".pi" / "agent" / "models.json"
    p.write_text(json.dumps({"providers": {
        "main": {"baseUrl": "http://llm.test/v1/", "apiKey": STORED,
                 "models": [{"id": "text-only"}, {"id": "vision", "input": ["text", "image"]}]},
        "other": {"baseUrl": "http://other/v1", "apiKey": "x", "models": [{"id": "o"}]}}}))
    (home / "grounder.env").write_text(
        "AUTONOMOUS_VERIFIER_URL=http://old-verifier/v1\nAUTONOMOUS_VERIFIER_MODEL=old\n")
    v = g_svc.verifier_config(home)
    assert v == {"base_url": "http://llm.test/v1", "model": "vision", "api_key": STORED}


def test_verifier_empty_without_llm(fake_home, home):
    from autonomous.services import grounding as g_svc

    (fake_home / ".pi" / "agent" / "models.json").unlink()
    assert g_svc.verifier_config(home) == {"base_url": "", "model": "", "api_key": ""}
