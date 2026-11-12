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


def test_version_in_source():
    assert updates_svc.version_in_source('__version__ = "0.1.0"\n') == "0.1.0"
    assert updates_svc.version_in_source("no version here") == ""


def test_default_channel_is_main(home):
    assert updates_svc.channel(home) == "main"
    assert updates_svc.remote_url(home) == ""


def test_set_channel_requires_confirm_dev(home, monkeypatch):
    monkeypatch.setattr(updates_svc, "git_available", lambda: True)
    monkeypatch.setattr(updates_svc, "can_switch_to", lambda *a, **k: {"ok": True, "channel": "dev"})
    with pytest.raises(ValidationError) as exc:
        updates_svc.set_channel("dev", home=home, confirm_dev=False)
    assert exc.value.code == "confirm_dev_required"
    out = updates_svc.set_channel("dev", home=home, confirm_dev=True)
    assert out["channel"] == "dev"
    assert settings_svc.get("update.channel", home=home) == "dev"


def test_custom_branch_and_remote_url(home, monkeypatch):
    monkeypatch.setattr(updates_svc, "git_available", lambda: True)
    monkeypatch.setattr(updates_svc, "can_switch_to", lambda *a, **k: {"ok": True, "channel": "release/1.2"})
    monkeypatch.setattr(updates_svc, "_ensure_updates_remote", lambda url: None)
    monkeypatch.setattr(updates_svc, "origin_url", lambda: "https://github.com/orig/Autonomous.git")

    with pytest.raises(ValidationError) as exc:
        updates_svc.set_channel("release/1.2", home=home, confirm_dev=False)
    assert exc.value.code == "confirm_dev_required"

    out = updates_svc.configure(
        home=home,
        branch="release/1.2",
        remote_url_value="https://github.com/you/Autonomous.git",
        set_remote=True,
        confirm_dev=True,
    )
    assert out["channel"] == "release/1.2"
    assert out["remote_url"] == "https://github.com/you/Autonomous.git"
    assert settings_svc.get("update.remote_url", home=home) == "https://github.com/you/Autonomous.git"

    cleared = updates_svc.set_remote_url("", home=home)
    assert cleared["remote_url"] == ""


def test_invalid_remote_and_branch_rejected(home):
    with pytest.raises(ValidationError) as exc:
        updates_svc.normalize_remote_url("file:///etc/passwd")
    assert exc.value.code == "invalid_remote_url"
    for bad in (
        "http://github.com/you/Autonomous.git",
        "git://github.com/you/Autonomous.git",
        "ftp://example.com/repo.git",
    ):
        with pytest.raises(ValidationError) as exc:
            updates_svc.normalize_remote_url(bad)
        assert exc.value.code == "invalid_remote_url"
    assert updates_svc.normalize_remote_url("https://github.com/you/Autonomous.git").startswith("https://")
    assert updates_svc.normalize_remote_url("git@github.com:you/Autonomous.git").startswith("git@")
    with pytest.raises(ValidationError):
        updates_svc.normalize_branch("../evil")
    with pytest.raises(ValidationError):
        updates_svc.normalize_branch("branch;rm")


def test_settings_put_rejects_channel_change(auth_client, home):
    settings_svc.set_value("update.channel", "main", home=home)
    r = auth_client.put("/api/v1/settings", json={"update.channel": "dev"})
    assert r.status_code == 400
    assert settings_svc.get("update.channel", home=home) == "main"
    r2 = auth_client.put(
        "/api/v1/settings",
        json={"update.remote_url": "https://example.com/x.git"},
    )
    assert r2.status_code == 400
    assert settings_svc.get("update.remote_url", home=home) in ("", None)


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
    assert body["version"]
    assert body["latest_version"]
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


def test_force_sync_resets_to_remote_tip():
    steps = dict(updates_svc.sync_steps("origin", "dev_peter", force=True))
    assert steps["fetch"][-3:] == ["fetch", "origin", "dev_peter"]
    assert steps["clean"][-2:] == ["clean", "-fd"]
    assert "clean" in steps["clean"] and "-x" not in steps["clean"]
    assert steps["reset"][-4:] == ["-f", "-B", "dev_peter", "origin/dev_peter"]
    plain = dict(updates_svc.sync_steps("origin", "main", force=False))
    assert "ff-only" in plain
    assert plain["ff-only"][-2:] == ["--ff-only", "origin/main"]


def test_apply_force_accepts_dirty(auth_client, monkeypatch):
    monkeypatch.setattr(updates_svc, "git_available", lambda: True)
    monkeypatch.setattr(updates_svc, "_dirty", lambda: True)
    monkeypatch.setattr(updates_svc, "_fetch_remote_name", lambda home=None: "origin")
    started = {}

    class _Thread:
        def __init__(self, target=None, name=None, daemon=None):
            started["target"] = target

        def start(self):
            started["started"] = True

    monkeypatch.setattr(updates_svc.threading, "Thread", _Thread)
    try:
        r = auth_client.post("/api/v1/setup/update/apply", json={"force": True})
        assert r.status_code == 202
        assert started.get("started") is True
        assert r.get_json()["kind"] == "setup.self_update"
    finally:
        updates_svc._apply_running = False


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


def test_squashed_migration_numbers_do_not_block_switch(home, monkeypatch):
    monkeypatch.setattr(updates_svc, "git_available", lambda: True)
    monkeypatch.setattr(updates_svc, "_rev_parse", lambda ref: "deadbeef" if ref else None)
    monkeypatch.setattr(
        updates_svc,
        "_git",
        lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )
    settings_svc.set_value("update.channel", "main", home=home)
    from autonomous.db import get_db

    with get_db(home) as conn:
        for version in (2, 22, 23):
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))",
                (version,),
            )
    monkeypatch.setattr(
        updates_svc,
        "_migration_versions_in_tree",
        lambda ref=None: {1, 23, 24, 25},
    )
    gate = updates_svc.can_switch_to("dev_peter", home=home)
    assert gate["ok"] is True

    with get_db(home) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (25, datetime('now'))"
        )
    monkeypatch.setattr(
        updates_svc,
        "_migration_versions_in_tree",
        lambda ref=None: {1, 23},
    )
    blocked = updates_svc.can_switch_to("old", home=home)
    assert blocked["ok"] is False
    assert blocked["code"] == "migrations_ahead"


def test_cache_roundtrip(home, monkeypatch):
    payload = {
        "ok": True,
        "available": False,
        "channel": "main",
        "remote_url": "",
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
