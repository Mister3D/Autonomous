"""Autonomous forces Pi idle timeout + disables auto-retry in settings.json."""

from __future__ import annotations

import json
from pathlib import Path

from autonomous.services import setup_config


def test_ensure_pi_runtime_settings_creates_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(setup_config, "pi_agent_dir", lambda: tmp_path / ".pi" / "agent")
    assert not setup_config.settings_json_path().exists()
    assert setup_config.ensure_pi_runtime_settings() is True
    data = json.loads(setup_config.settings_json_path().read_text(encoding="utf-8"))
    assert data["httpIdleTimeoutMs"] == setup_config.PI_HTTP_IDLE_TIMEOUT_MS
    assert data["retry"] == {"enabled": False}
    assert setup_config.ensure_pi_runtime_settings() is False


def test_ensure_pi_runtime_settings_merges_without_wiping(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(setup_config, "pi_agent_dir", lambda: tmp_path / ".pi" / "agent")
    path = setup_config.settings_json_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "packages": ["npm:pi-web-access"],
                "compaction": {"enabled": True, "reserveTokens": 49152},
                "httpIdleTimeoutMs": 300_000,
                "retry": {"enabled": True, "maxRetries": 3},
                "cacheWarming": "off",
            }
        ),
        encoding="utf-8",
    )
    assert setup_config.ensure_pi_runtime_settings() is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["packages"] == ["npm:pi-web-access"]
    assert data["compaction"]["reserveTokens"] == 49152
    assert data["cacheWarming"] == "off"
    assert data["httpIdleTimeoutMs"] == 600_000
    assert data["retry"]["enabled"] is False
    assert data["retry"]["maxRetries"] == 3


def test_ensure_pi_runtime_settings_fixes_non_dict_retry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(setup_config, "pi_agent_dir", lambda: tmp_path / ".pi" / "agent")
    path = setup_config.settings_json_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"retry": True}), encoding="utf-8")
    assert setup_config.ensure_pi_runtime_settings() is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["retry"] == {"enabled": False}
    assert data["httpIdleTimeoutMs"] == 600_000
