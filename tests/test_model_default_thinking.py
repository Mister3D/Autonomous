"""Per-model default thinking level (models.json autonomous.defaultThinking)."""

from __future__ import annotations

import json

from autonomous.services import bots as bots_svc
from autonomous.services import setup_config as cfg


def test_save_llm_persists_default_thinking(tmp_path, monkeypatch):
    h = tmp_path / "home"
    (h / ".pi" / "agent").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(h))

    cfg.save_llm(
        {
            "provider": "mine",
            "base_url": "http://llm.test/v1",
            "api_key": "sk",
            "model": "qwen",
            "model_name": "Qwen",
            "images": True,
            "default_thinking": "high",
        }
    )
    raw = json.loads((h / ".pi" / "agent" / "models.json").read_text())
    entry = raw["providers"]["mine"]["models"][0]
    assert entry["autonomous"]["defaultThinking"] == "high"
    pub = cfg.llm_view()["providers"][0]["models"][0]
    assert pub["default_thinking"] == "high"
    assert bots_svc.thinking_default_for_model("mine/qwen") == "high"
    assert bots_svc.thinking_default_for_model("missing/x") == "medium"


def test_create_bot_inherits_model_default_thinking(tmp_path, monkeypatch, home):
    h = tmp_path / "pihome"
    (h / ".pi" / "agent").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(h))
    cfg.save_llm(
        {
            "provider": "mine",
            "base_url": "http://llm.test/v1",
            "api_key": "sk",
            "model": "qwen",
            "default_thinking": "low",
        }
    )
    bot = bots_svc.create_bot("Think From Model", model="mine/qwen", home=home)
    assert bot["thinking"] == "low"
