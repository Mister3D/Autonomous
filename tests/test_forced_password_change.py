"""Generated install password must be changed before using the hub."""

from __future__ import annotations

from autonomous import auth as auth_mod
from autonomous.paths import initial_password_path, must_change_password_path


def test_status_reports_must_change_before_login(client, home):
    auth_mod.mark_password_must_change(home)
    r = client.get("/api/v1/auth/status")
    assert r.status_code == 200
    body = r.get_json()
    assert body["password_set"] is True
    assert body["must_change_password"] is True
    assert body["authenticated"] is False


def test_login_with_generated_password_gates_api(client, home):
    initial_password_path(home).write_text("secret\n", encoding="utf-8")
    auth_mod.mark_password_must_change(home)

    logged = client.post("/api/v1/auth/login", json={"password": "secret"})
    assert logged.status_code == 200
    assert logged.get_json()["must_change_password"] is True
    assert not initial_password_path(home).exists()
    assert must_change_password_path(home).exists()

    blocked = client.get("/api/v1/bots")
    assert blocked.status_code == 403
    assert blocked.get_json()["code"] == "password_change_required"

    status = client.get("/api/v1/auth/status").get_json()
    assert status["authenticated"] is True
    assert status["must_change_password"] is True


def test_change_password_unlocks_api(client, home):
    auth_mod.set_password(home, "generated-secret")
    auth_mod.mark_password_must_change(home)
    assert (
        client.post("/api/v1/auth/login", json={"password": "generated-secret"}).status_code
        == 200
    )

    same = client.post(
        "/api/v1/auth/password",
        json={
            "current_password": "generated-secret",
            "new_password": "generated-secret",
        },
    )
    assert same.status_code == 400

    short = client.post(
        "/api/v1/auth/password",
        json={"current_password": "generated-secret", "new_password": "short"},
    )
    assert short.status_code == 422

    ok = client.post(
        "/api/v1/auth/password",
        json={
            "current_password": "generated-secret",
            "new_password": "new-secret-ok",
        },
    )
    assert ok.status_code == 200
    assert not must_change_password_path(home).exists()

    status = client.get("/api/v1/auth/status").get_json()
    assert status["authenticated"] is True
    assert status["must_change_password"] is False
    assert client.get("/api/v1/bots").status_code == 200


def test_admin_bearer_bypasses_password_gate(client, home):
    auth_mod.mark_password_must_change(home)
    token = auth_mod.read_token(home)
    r = client.get("/api/v1/bots", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_init_must_change_flag(tmp_path):
    from autonomous.cli import cmd_init

    class Args:
        home = str(tmp_path)
        password = "generated-pw"
        must_change_password = True
        json = False

    assert cmd_init(Args()) == 0
    assert must_change_password_path(tmp_path).exists()
    assert auth_mod.verify_password(tmp_path, "generated-pw")
