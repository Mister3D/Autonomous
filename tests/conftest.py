"""Pytest fixtures."""

from __future__ import annotations

import os

import pytest

# Companion egress rules are host iptables. Tests must not install them.
os.environ["AUTONOMOUS_COMPANION_IPTABLES"] = "0"

from autonomous import auth as auth_mod
from autonomous.app import create_app
from autonomous.db import migrate
from autonomous.paths import ensure_home
from autonomous.services import settings as settings_svc


@pytest.fixture(autouse=True)
def _clear_rate_limits():
    from autonomous.services.ratelimit import HOOKS, LOGIN, PAIRING

    LOGIN.clear()
    HOOKS.clear()
    PAIRING.clear()


@pytest.fixture()
def pairing_on(home):
    """Pairing is off unless a test turns it on."""
    settings_svc.set_value("companions.enabled", True, home=home)
    return home


@pytest.fixture()
def home(tmp_path):
    h = ensure_home(tmp_path / "data")
    migrate(h)
    settings_svc.ensure_defaults(h)
    # Tests stay offline from Pi RPC.
    settings_svc.set_many({"agent_backend": "null"}, home=h)
    auth_mod.write_token(h, "test-token")
    auth_mod.write_session_secret(h, "test-session-secret")
    auth_mod.set_password(h, "secret")
    return h


@pytest.fixture()
def app(home):
    application = create_app(home)
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_client(client):
    r = client.post("/api/v1/auth/login", json={"password": "secret"})
    assert r.status_code == 200
    # Creating a bot via API requires a model; inject a fixture default when omitted
    # so existing tests keep working. Explicit "" / whitespace still rejected.
    orig_post = client.post

    def post(url, *args, **kwargs):
        path = str(url or "").split("?", 1)[0].rstrip("/")
        body = kwargs.get("json")
        # Only the create-bot collection (not …/household/bots).
        if path.rstrip("/").endswith("/api/v1/bots") and isinstance(body, dict) and "model" not in body:
            kwargs = {**kwargs, "json": {**body, "model": "test/provider:fixture"}}
        return orig_post(url, *args, **kwargs)

    client.post = post  # type: ignore[method-assign]
    return client


@pytest.fixture()
def bearer_headers():
    return {"Authorization": "Bearer test-token"}
