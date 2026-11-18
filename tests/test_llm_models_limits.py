"""Pi models.json is source of truth; Autonomous enforces image limits as overlay."""

from __future__ import annotations

import json

import pytest

from autonomous.services import chat_attachments as attach_svc
from autonomous.services import setup_config as cfg
from autonomous.services.errors import ValidationError


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    (h / ".pi" / "agent").mkdir(parents=True)
    return h


def _write_models(home, data):
    p = home / ".pi" / "agent" / "models.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_save_llm_models_list_merge_safe(fake_home):
    _write_models(
        fake_home,
        {
            "providers": {
                "mine": {
                    "baseUrl": "http://llm.test/v1",
                    "apiKey": "sk-old",
                    "api": "openai-completions",
                    "models": [
                        {
                            "id": "keep-me",
                            "name": "Keep",
                            "input": ["text", "image"],
                            "cost": {"input": 1, "output": 2, "cacheRead": 0, "cacheWrite": 0},
                            "reasoning": True,
                        }
                    ],
                }
            }
        },
    )
    out = cfg.save_llm(
        {
            "provider": "mine",
            "base_url": "http://llm.test/v1",
            "api_key": "",
            "models": [
                {
                    "id": "keep-me",
                    "name": "Keep Short",
                    "images": True,
                    "max_images": 3,
                    "context_window": 64000,
                    "max_tokens": 4096,
                },
                {
                    "id": "new-one",
                    "name": "New",
                    "images": False,
                    "max_images": 1,
                    "context_window": 8000,
                    "max_tokens": 1024,
                },
            ],
        }
    )
    raw = json.loads((fake_home / ".pi" / "agent" / "models.json").read_text())
    models = raw["providers"]["mine"]["models"]
    assert [m["id"] for m in models] == ["keep-me", "new-one"]
    keep = models[0]
    assert keep["name"] == "Keep Short"
    assert keep["cost"]["input"] == 1  # unknown field preserved
    assert keep["reasoning"] is True
    assert keep["contextWindow"] == 64000
    assert keep["maxTokens"] == 4096
    assert keep["inputLimits"]["images"]["maxPerRequest"] == 3
    assert "image" in keep["input"]
    new = models[1]
    assert new["input"] == ["text"]
    assert new["inputLimits"]["images"]["maxPerRequest"] == 1
    pub = out["providers"][0]["models"]
    assert pub[0]["max_images"] == 3
    assert pub[0]["context_window"] == 64000
    assert "docs" in out


def test_save_llm_provider_credentials_only(fake_home):
    out = cfg.save_llm(
        {
            "provider": "solo",
            "base_url": "http://llm.test/v1",
            "api_key": "sk-test",
        }
    )
    raw = json.loads((fake_home / ".pi" / "agent" / "models.json").read_text())
    conf = raw["providers"]["solo"]
    assert conf["baseUrl"] == "http://llm.test/v1"
    assert conf["apiKey"] == "sk-test"
    assert conf.get("models") == []
    assert out["providers"][0]["provider"] == "solo"

    # Later model upsert keeps credentials.
    cfg.save_llm(
        {
            "provider": "solo",
            "base_url": "http://llm.test/v1",
            "model": "m1",
            "model_name": "One",
            "images": True,
        }
    )
    raw2 = json.loads((fake_home / ".pi" / "agent" / "models.json").read_text())
    assert [m["id"] for m in raw2["providers"]["solo"]["models"]] == ["m1"]
    assert raw2["providers"]["solo"]["apiKey"] == "sk-test"


def test_delete_llm_provider_blocked_while_a_model_uses_it(fake_home):
    _write_models(
        fake_home,
        {
            "providers": {
                "mine": {
                    "baseUrl": "http://llm.test/v1",
                    "apiKey": "sk",
                    "models": [{"id": "m1"}],
                },
                "empty": {"baseUrl": "http://other.test/v1", "apiKey": "sk", "models": []},
            }
        },
    )
    with pytest.raises(ValidationError) as exc:
        cfg.delete_llm_provider("mine")
    assert exc.value.code == "provider_in_use"
    raw = json.loads((fake_home / ".pi" / "agent" / "models.json").read_text())
    assert "mine" in raw["providers"]
    out = cfg.delete_llm_provider("empty")
    raw = json.loads((fake_home / ".pi" / "agent" / "models.json").read_text())
    assert "empty" not in raw["providers"]
    assert "mine" in raw["providers"]
    assert [p["provider"] for p in out["providers"]] == ["mine"]


def test_resolve_and_enforce_max_images(fake_home, home):
    _write_models(
        fake_home,
        {
            "providers": {
                "mine": {
                    "baseUrl": "http://llm.test/v1",
                    "apiKey": "x",
                    "models": [
                        {
                            "id": "vision",
                            "input": ["text", "image"],
                            "inputLimits": {"images": {"maxPerRequest": 4}},
                        }
                    ],
                }
            }
        },
    )
    assert cfg.resolve_model_limits("mine/vision")["max_images"] == 4
    from autonomous.services import bots as bots_svc

    bots_svc.create_bot("limbot", home=home)
    bots_svc.patch_bot("limbot", {"model": "mine/vision"}, home=home)
    assert attach_svc.max_images_per_prompt(home=home, bot="limbot") == 4


def test_remember_model_image_limit(fake_home):
    _write_models(
        fake_home,
        {
            "providers": {
                "mine": {
                    "baseUrl": "http://llm.test/v1",
                    "apiKey": "x",
                    "models": [{"id": "m1", "input": ["text", "image"]}],
                }
            }
        },
    )
    cfg.remember_model_image_limit("mine/m1", 2)
    raw = json.loads((fake_home / ".pi" / "agent" / "models.json").read_text())
    assert raw["providers"]["mine"]["models"][0]["inputLimits"]["images"]["maxPerRequest"] == 2


def test_fallback_guard_when_no_pi_limit(fake_home, home):
    _write_models(
        fake_home,
        {
            "providers": {
                "mine": {
                    "baseUrl": "http://llm.test/v1",
                    "apiKey": "x",
                    "models": [{"id": "plain", "input": ["text"]}],
                }
            }
        },
    )
    from autonomous.services import bots as bots_svc
    from autonomous.services import settings as settings_svc

    bots_svc.create_bot("plainbot", home=home)
    bots_svc.patch_bot("plainbot", {"model": "mine/plain"}, home=home)
    settings_svc.set_value("guard.max_images_per_prompt", 2, home=home)
    assert attach_svc.max_images_per_prompt(home=home, bot="plainbot") == 2
    attach_svc.write_vision_cap("plainbot", 1, home=home)
    assert attach_svc.read_vision_cap("plainbot", home=home) == 1
    assert attach_svc.max_images_per_prompt(home=home, bot="plainbot") == 1


def test_parse_pi_model_list_keeps_capabilities():
    from autonomous.services.pi_status import parse_model_list

    text = """provider  model  context  max-out  thinking  images
openai    gpt-5.4  272K  128K  yes  yes
Mister3D  custom/id  128K  16K  no  yes
Use /login to add more
"""
    rows = parse_model_list(text)
    assert [(r["provider"], r["id"], r["context"], r["thinking"], r["images"]) for r in rows] == [
        ("openai", "gpt-5.4", "272K", True, True),
        ("Mister3D", "custom/id", "128K", False, True),
    ]
