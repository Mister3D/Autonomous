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
def home(tmp_path):
    h = ensure_home(tmp_path / "data")
    migrate(h)
    settings_svc.ensure_defaults(h)
    # Tests stay offline from Pi RPC.
    settings_svc.set_many({"agent_backend": "null"}, home=h)
    auth_mod.write_token(h, "test-token")
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
    return client


@pytest.fixture()
def bearer_headers():
    return {"Authorization": "Bearer test-token"}
