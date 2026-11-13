"""Session secret ≠ Bearer, grounder TOKEN fallback gone, XFF trust, companion pre-101."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from autonomous import auth as auth_mod
from autonomous.app import create_app
from autonomous.services import grounding
from autonomous.services.client_ip import client_ip
from autonomous.wsproxy import MuxServer


def test_session_secret_distinct_from_api_token(home):
    assert auth_mod.read_token(home) == "test-token"
    assert auth_mod.read_session_secret(home) == "test-session-secret"
    app = create_app(home)
    assert app.config["SECRET_KEY"] == "test-session-secret"
    assert app.config["SECRET_KEY"] != auth_mod.read_token(home)


def test_refuse_secret_equal_to_bearer(home, monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_SECRET", "test-token")
    with pytest.raises(RuntimeError, match="must not equal"):
        create_app(home)


def test_ensure_session_secret_creates_file(tmp_path):
    from autonomous.db import migrate
    from autonomous.paths import ensure_home, secret_path
    from autonomous.services import settings as settings_svc

    h = ensure_home(tmp_path / "data")
    migrate(h)
    settings_svc.ensure_defaults(h)
    auth_mod.write_token(h, "api-only")
    assert not secret_path(h).exists()
    got = auth_mod.ensure_session_secret(h)
    assert secret_path(h).is_file()
    assert got and got != "api-only"
    assert auth_mod.ensure_session_secret(h) == got


def test_grounder_ignores_TOKEN_file(home, monkeypatch, tmp_path):
    monkeypatch.delenv("AUTONOMOUS_GROUNDER_TOKEN", raising=False)
    monkeypatch.delenv("GROUNDER_API_KEY", raising=False)
    monkeypatch.delenv("GROUNDER_TOKEN", raising=False)
    # Plant a TOKEN that looks like the admin Bearer — must not be picked up.
    (home / "TOKEN").write_text("test-token\n", encoding="utf-8")
    cfg = grounding.grounder_config(home, ignore_enabled=True)
    assert cfg["api_key"] == ""


def test_client_ip_ignores_xff_by_default(app, monkeypatch):
    monkeypatch.delenv("AUTONOMOUS_TRUST_PROXY", raising=False)
    with app.test_request_context(
        "/",
        environ_base={"REMOTE_ADDR": "10.1.2.3"},
        headers={"X-Forwarded-For": "9.9.9.9"},
    ):
        from flask import request

        assert client_ip(request) == "10.1.2.3"


def test_client_ip_trusts_xff_when_enabled(app, monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_TRUST_PROXY", "1")
    with app.test_request_context(
        "/",
        environ_base={"REMOTE_ADDR": "10.1.2.3"},
        headers={"X-Forwarded-For": "9.9.9.9, 10.1.2.3"},
    ):
        from flask import request

        assert client_ip(request) == "9.9.9.9"


def test_pair_poll_rate_limited(client):
    from autonomous.services.ratelimit import PAIRING

    PAIRING.clear()
    codes = []
    for i in range(65):
        r = client.post(
            "/api/v1/devices/pair-poll",
            json={"pair_id": f"id-{i % 3}", "poll_secret": "x" * 32},
        )
        codes.append(r.status_code)
    assert 429 in codes


def test_pairing_off_by_default(client, home):
    from autonomous.services import settings as settings_svc

    assert settings_svc.get("companions.enabled", home=home) is False
    r = client.post(
        "/api/v1/devices/pair",
        json={"name": "No", "platform": "linux"},
    )
    assert r.status_code == 403


def test_pairing_disabled_setting(client, auth_client, home):
    from autonomous.services import settings as settings_svc

    settings_svc.set_value("companions.enabled", False, home=home)
    r = client.post(
        "/api/v1/devices/pair",
        json={"name": "No", "platform": "linux"},
    )
    assert r.status_code == 403
    poll = client.post(
        "/api/v1/devices/pair-poll",
        json={"pair_id": "x", "poll_secret": "y" * 32},
    )
    assert poll.status_code == 403
    settings_svc.set_value("companions.enabled", True, home=home)
    ok = client.post(
        "/api/v1/devices/pair",
        json={"name": "Yes", "platform": "linux"},
    )
    assert ok.status_code == 200


def test_companion_token_ok_before_upgrade(client, auth_client, home, pairing_on):
    started = client.post(
        "/api/v1/devices/pair",
        json={"name": "Desk", "platform": "linux"},
    )
    assert started.status_code == 200
    body = started.get_json()
    assert auth_client.post(f"/api/v1/devices/pair/{body['pair_id']}/approve").status_code == 200
    polled = client.post(
        "/api/v1/devices/pair-poll",
        json={"pair_id": body["pair_id"], "poll_secret": body["poll_secret"]},
    )
    token = polled.get_json()["device_token"]
    mux = MuxServer("127.0.0.1", 0, None, lambda _bot: None, home=home)
    assert not mux._companion_token_ok("")
    assert not mux._companion_token_ok("adc_notreal")
    assert mux._companion_token_ok(token)
