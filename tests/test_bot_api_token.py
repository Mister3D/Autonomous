"""Per-bot API tokens (abt_…) for Pi — scoped, not admin Bearer."""

from __future__ import annotations

from autonomous import auth as auth_mod
from autonomous.services import bots as bots_svc
from autonomous.services import pi_rpc


def test_issue_bot_token_prefix_and_hash(home):
    bots_svc.create_bot("Alpha", home=home)
    raw = auth_mod.issue_bot_api_token("alpha", home=home)
    assert raw.startswith(auth_mod.BOT_TOKEN_PREFIX)
    digest = auth_mod.hash_bot_token(raw)
    from autonomous.db import get_db

    with get_db(home) as conn:
        row = conn.execute(
            "SELECT api_token_hash FROM bots WHERE name = ?", ("alpha",)
        ).fetchone()
    assert row["api_token_hash"] == digest


def test_pi_env_uses_bot_token_not_admin(home):
    bots_svc.create_bot("PiBot", home=home)
    env = pi_rpc._pi_session_env("pibot", home=home)
    assert env["AUTONOMOUS_TOKEN"].startswith(auth_mod.BOT_TOKEN_PREFIX)
    assert env["AUTONOMOUS_TOKEN"] != auth_mod.read_token(home)
    assert env["AUTONOMOUS_BOT"] == "pibot"
    assert env["AUTONOMOUS_MAX_IMAGES"] == "2"


def test_pi_env_uses_in_process_base_before_pid_file(home):
    bots_svc.create_bot("EarlyPi", home=home)
    pi_rpc.set_serve_api_base("http://127.0.0.1:8787/api/v1")
    try:
        env = pi_rpc._pi_session_env("earlypi", home=home)
    finally:
        pi_rpc.set_serve_api_base(None)
    assert env["AUTONOMOUS_API_BASE"] == "http://127.0.0.1:8787/api/v1"
    assert env["AUTONOMOUS_TOKEN"].startswith(auth_mod.BOT_TOKEN_PREFIX)
    assert env["AUTONOMOUS_BOT"] == "earlypi"


def test_bot_token_allows_own_bot_routes(app, home):
    bots_svc.create_bot("Worker", home=home)
    token = auth_mod.issue_bot_api_token("worker", home=home)
    client = app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/api/v1/bots/worker", headers=headers)
    assert r.status_code == 200
    assert r.json["name"] == "worker"

    r = client.get("/api/v1/bots/worker/files?path=", headers=headers)
    assert r.status_code == 200


def test_bot_token_denies_other_bot_and_admin(app, home):
    bots_svc.create_bot("A", home=home)
    bots_svc.create_bot("B", home=home)
    token = auth_mod.issue_bot_api_token("a", home=home)
    client = app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/bots/b", headers=headers).status_code == 403
    assert client.get("/api/v1/bots", headers=headers).status_code == 403
    assert client.delete("/api/v1/bots/a", headers=headers).status_code == 403
    assert client.get("/api/v1/settings", headers=headers).status_code == 403
    assert client.get("/api/openapi.json", headers=headers).status_code == 403


def test_bot_token_cannot_impersonate_in_vault(app, home):
    bots_svc.create_bot("VaultBot", home=home)
    bots_svc.create_bot("Other", home=home)
    token = auth_mod.issue_bot_api_token("vaultbot", home=home)
    client = app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/api/v1/vault/requests",
        headers=headers,
        json={"bot": "other", "kind": "secret", "reason": "nope"},
    )
    assert r.status_code == 403
    assert r.json["code"] == "bot_token_forbidden"


def test_bot_token_vault_request_for_self(app, home):
    bots_svc.create_bot("VaultSelf", home=home)
    token = auth_mod.issue_bot_api_token("vaultself", home=home)
    client = app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/api/v1/vault/requests",
        headers=headers,
        json={"bot": "vaultself", "kind": "secret", "reason": "need key", "label": "x"},
    )
    assert r.status_code == 201
    req_id = r.json["id"]
    assert client.get(f"/api/v1/vault/requests/{req_id}", headers=headers).status_code == 200
    # Resolve stays admin/session only
    assert (
        client.post(
            f"/api/v1/vault/requests/{req_id}/resolve",
            headers=headers,
            json={"action": "deny"},
        ).status_code
        == 403
    )


def test_admin_bearer_still_full_access(app, home, bearer_headers):
    bots_svc.create_bot("AdminPath", home=home)
    client = app.test_client()
    assert client.get("/api/v1/bots", headers=bearer_headers).status_code == 200
    assert client.get("/api/openapi.json", headers=bearer_headers).status_code == 200


def test_rotate_invalidates_old_token(app, home):
    bots_svc.create_bot("Rotate", home=home)
    old = auth_mod.issue_bot_api_token("rotate", home=home)
    new = auth_mod.issue_bot_api_token("rotate", home=home)
    assert old != new
    client = app.test_client()
    assert (
        client.get("/api/v1/bots/rotate", headers={"Authorization": f"Bearer {old}"}).status_code
        == 401
    )
    assert (
        client.get("/api/v1/bots/rotate", headers={"Authorization": f"Bearer {new}"}).status_code
        == 200
    )
