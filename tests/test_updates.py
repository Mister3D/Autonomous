"""Self-update status, channel guards, apply gates."""

from __future__ import annotations

import json

import pytest

from autonomous.services import settings as settings_svc
from autonomous.services import updates as updates_svc
from autonomous.services.errors import ValidationError


@pytest.fixture(autouse=True)
def _clean_cache(home):
    updates_svc.invalidate_cache(home)
    yield
    updates_svc.invalidate_cache(home)


def test_default_channel_is_main(home):
    assert updates_svc.channel(home) == "main"


def test_set_channel_requires_confirm_dev(home, monkeypatch):
    monkeypatch.setattr(updates_svc, "git_available", lambda: True)
    monkeypatch.setattr(updates_svc, "can_switch_to", lambda *a, **k: {"ok": True, "channel": "dev"})
    with pytest.raises(ValidationError) as exc:
        updates_svc.set_channel("dev", home=home, confirm_dev=False)
    assert exc.value.code == "confirm_dev_required"
    out = updates_svc.set_channel("dev", home=home, confirm_dev=True)
    assert out["channel"] == "dev"
    assert settings_svc.get("update.channel", home=home) == "dev"


def test_settings_put_rejects_channel_change(auth_client, home):
    settings_svc.set_value("update.channel", "main", home=home)
    r = auth_client.put("/api/v1/settings", json={"update.channel": "dev"})
    assert r.status_code == 400
    assert settings_svc.get("update.channel", home=home) == "main"


def test_status_endpoint_cached(auth_client, home, monkeypatch):
    calls = {"n": 0}

    def fake_check(*, home=None, force=False):
        calls["n"] += 1
        return {
            "ok": True,
            "available": False,
            "channel": "main",
            "cached": False,
            "checked_at_epoch": 1e12,
            "local_sha": "abc",
            "remote_sha": "abc",
            "behind": 0,
            "dirty": False,
            "git": True,
            "service_restart": None,
        }

    monkeypatch.setattr(updates_svc, "check", fake_check)
    monkeypatch.setattr(updates_svc, "can_switch_to", lambda *a, **k: {"ok": True})
    r = auth_client.get("/api/v1/setup/update")
    assert r.status_code == 200
    body = r.get_json()
    assert body["channel"] == "main"
    assert "channels" in body
    assert calls["n"] == 1


def test_check_endpoint_forces(auth_client, monkeypatch):
    seen = []

    def fake_check(*, home=None, force=False):
        seen.append(force)
        return {
            "ok": True,
            "available": True,
            "channel": "main",
            "behind": 2,
            "git": True,
            "dirty": False,
            "checked_at_epoch": 0,
        }

    monkeypatch.setattr(updates_svc, "check", fake_check)
    monkeypatch.setattr(updates_svc, "can_switch_to", lambda *a, **k: {"ok": True})
    r = auth_client.post("/api/v1/setup/update/check", json={})
    assert r.status_code == 200
    assert seen == [True]
    assert r.get_json()["available"] is True


def test_apply_refuses_dirty(auth_client, monkeypatch):
    monkeypatch.setattr(updates_svc, "git_available", lambda: True)
    monkeypatch.setattr(updates_svc, "_dirty", lambda: True)
    r = auth_client.post("/api/v1/setup/update/apply", json={})
    assert r.status_code == 400
    msg = (r.get_json().get("message") or "").lower()
    assert "local changes" in msg or r.get_json().get("error_code") == "dirty"


def test_migrations_ahead_blocks_main(home, monkeypatch, tmp_path):
    monkeypatch.setattr(updates_svc, "git_available", lambda: True)
    monkeypatch.setattr(updates_svc, "_rev_parse", lambda ref: "deadbeef" if ref else None)
    monkeypatch.setattr(updates_svc, "_git", lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    settings_svc.set_value("update.channel", "dev", home=home)

    # Pretend DB has migration 999 not on main tree.
    from autonomous.db import get_db

    with get_db(home) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (999)"
        )

    monkeypatch.setattr(
        updates_svc,
        "_migration_versions_in_tree",
        lambda ref=None: {1, 2, 3},
    )
    gate = updates_svc.can_switch_to("main", home=home)
    assert gate["ok"] is False
    assert gate["code"] == "migrations_ahead"
    with pytest.raises(ValidationError) as exc:
        updates_svc.set_channel("main", home=home)
    assert exc.value.code == "migrations_ahead"


def test_cache_roundtrip(home, monkeypatch):
    payload = {
        "ok": True,
        "available": False,
        "channel": "main",
        "checked_at_epoch": 9_999_999_999,
        "git": True,
        "behind": 0,
        "dirty": False,
        "local_sha": "aaa",
        "remote_sha": "aaa",
    }
    path = updates_svc._cache_path(home)
    path.write_text(json.dumps(payload), encoding="utf-8")

    def boom(*, home=None, force=False):
        raise AssertionError("should use cache")

    # Bypass check's network by calling status's inner path via check with force=False
    monkeypatch.setattr(updates_svc, "git_available", lambda: True)
    out = updates_svc.check(home=home, force=False)
    assert out["cached"] is True
    assert out["local_sha"] == "aaa"
