"""Per-model gate for concurrent large LLM provider calls."""

from __future__ import annotations

import json
import threading
import time

import pytest

from autonomous.services import llm_heavy_gate as gate
from autonomous.services import setup_config as cfg
from autonomous.services.errors import AutonomousError


@pytest.fixture(autouse=True)
def _clean_gate():
    gate.reset_for_tests()
    yield
    gate.reset_for_tests()


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    (h / ".pi" / "agent").mkdir(parents=True)
    return h


def _enable_heavy(fake_home, *, provider="mine", model_id="heavy", max_c=2, thresh=10000):
    cfg.save_llm(
        {
            "provider": provider,
            "base_url": "http://llm.test/v1",
            "api_key": "sk",
            "model": model_id,
            "model_name": "Heavy",
            "images": True,
            "heavy_gate_enabled": True,
            "heavy_max_concurrent": max_c,
            "heavy_token_threshold": thresh,
        }
    )
    raw = json.loads((fake_home / ".pi" / "agent" / "models.json").read_text())
    entry = raw["providers"][provider]["models"][0]
    assert entry["autonomous"]["heavyGate"]["enabled"] is True
    return f"{provider}/{model_id}"


def test_estimate_tokens_ignores_data_url_bloat():
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hello world"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + ("A" * 50000)},
                    },
                ],
            }
        ]
    }
    n = gate.estimate_tokens(payload)
    assert 200 < n < 5000


def test_save_llm_persists_heavy_gate(fake_home):
    ref = _enable_heavy(fake_home, max_c=3, thresh=8000)
    pub = cfg.llm_view()["providers"][0]["models"][0]
    assert pub["heavy_gate_enabled"] is True
    assert pub["heavy_max_concurrent"] == 3
    assert pub["heavy_token_threshold"] == 8000
    assert gate.gate_config_for_model("mine", "heavy")["enabled"] is True
    assert ref == "mine/heavy"


def test_unset_model_never_blocks(fake_home):
    cfg.save_llm(
        {
            "provider": "mine",
            "base_url": "http://llm.test/v1",
            "api_key": "sk",
            "model": "plain",
            "images": True,
        }
    )
    out = gate.acquire("bot-a", 100_000, model="mine/plain", wait_sec=0.2)
    assert out["heavy"] is False


def test_light_request_skips_lease(fake_home):
    _enable_heavy(fake_home)
    out = gate.acquire("bot-a", 500, model="mine/heavy")
    assert out["heavy"] is False
    assert out["lease_id"] is None
    assert gate.snapshot()["active"] == 0


def test_heavy_requests_cap_per_model(fake_home):
    _enable_heavy(fake_home, max_c=2)
    a = gate.acquire("bot-a", 50_000, model="mine/heavy", wait_sec=1)
    b = gate.acquire("bot-b", 50_000, model="mine/heavy", wait_sec=1)
    assert a["heavy"] and b["heavy"]
    assert a["pool"] == "mine/heavy"
    assert gate.snapshot()["by_pool"]["mine/heavy"] == 2

    timed_out = {"ok": False}

    def try_third():
        try:
            gate.acquire("bot-c", 50_000, model="mine/heavy", wait_sec=0.4)
        except AutonomousError as exc:
            timed_out["ok"] = exc.code == "llm_heavy_gate_timeout"

    t = threading.Thread(target=try_third)
    t.start()
    t.join(timeout=2)
    assert timed_out["ok"] is True

    gate.release(a["lease_id"])
    c = gate.acquire("bot-c", 50_000, model="mine/heavy", wait_sec=2)
    assert c["heavy"] is True
    gate.release(b["lease_id"])
    gate.release(c["lease_id"])
    assert gate.snapshot()["active"] == 0


def test_two_models_have_independent_pools(fake_home):
    _enable_heavy(fake_home, model_id="a", max_c=1)
    cfg.save_llm(
        {
            "provider": "mine",
            "base_url": "http://llm.test/v1",
            "model": "b",
            "model_name": "B",
            "images": True,
            "heavy_gate_enabled": True,
            "heavy_max_concurrent": 1,
            "heavy_token_threshold": 10000,
        }
    )
    a = gate.acquire("bot-a", 50_000, model="mine/a", wait_sec=1)
    b = gate.acquire("bot-b", 50_000, model="mine/b", wait_sec=1)
    assert a["heavy"] and b["heavy"]
    assert a["pool"] != b["pool"]
    assert gate.snapshot()["active"] == 2
    gate.release(a["lease_id"])
    gate.release(b["lease_id"])


def test_disabled_on_model_never_blocks(fake_home):
    _enable_heavy(fake_home)
    cfg.save_llm(
        {
            "provider": "mine",
            "base_url": "http://llm.test/v1",
            "model": "heavy",
            "heavy_gate_enabled": False,
            "heavy_max_concurrent": 2,
            "heavy_token_threshold": 10000,
        }
    )
    for i in range(5):
        out = gate.acquire(f"bot-{i}", 100_000, model="mine/heavy", wait_sec=0.2)
        assert out["heavy"] is False


def test_release_is_idempotent(fake_home):
    _enable_heavy(fake_home)
    out = gate.acquire("bot-a", 20_000, model="mine/heavy")
    assert gate.release(out["lease_id"])["released"] is True
    assert gate.release(out["lease_id"])["released"] is False
    assert gate.release("")["released"] is False


def test_waiting_thread_wakes_on_release(fake_home):
    _enable_heavy(fake_home, max_c=1)
    first = gate.acquire("bot-a", 20_000, model="mine/heavy")
    got = {"lease": None}

    def waiter():
        got["lease"] = gate.acquire("bot-b", 20_000, model="mine/heavy", wait_sec=3)

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.15)
    gate.release(first["lease_id"])
    t.join(timeout=3)
    assert got["lease"] and got["lease"]["heavy"] is True
    gate.release(got["lease"]["lease_id"])


def test_parallel_gate_limits_any_size(fake_home):
    cfg.save_llm(
        {
            "provider": "mine",
            "base_url": "http://llm.test/v1",
            "api_key": "sk",
            "model": "all",
            "model_name": "All",
            "images": True,
            "parallel_gate_enabled": True,
            "max_parallel": 1,
            "heavy_gate_enabled": False,
        }
    )
    raw = json.loads((fake_home / ".pi" / "agent" / "models.json").read_text())
    assert raw["providers"]["mine"]["models"][0]["autonomous"]["parallelGate"]["enabled"] is True

    # Tiny prompts still take a slot.
    a = gate.acquire("bot-a", 50, model="mine/all", wait_sec=1)
    assert a["heavy"] is False
    assert a["lease_id"]
    timed_out = {"ok": False}

    def try_second():
        try:
            gate.acquire("bot-b", 50, model="mine/all", wait_sec=0.4)
        except AutonomousError as exc:
            timed_out["ok"] = exc.code == "llm_heavy_gate_timeout"

    t = threading.Thread(target=try_second)
    t.start()
    t.join(timeout=2)
    assert timed_out["ok"] is True
    gate.release(a["lease_id"])


def test_parallel_and_heavy_both_apply(fake_home):
    cfg.save_llm(
        {
            "provider": "mine",
            "base_url": "http://llm.test/v1",
            "api_key": "sk",
            "model": "both",
            "images": True,
            "parallel_gate_enabled": True,
            "max_parallel": 3,
            "heavy_gate_enabled": True,
            "heavy_max_concurrent": 1,
            "heavy_token_threshold": 10000,
        }
    )
    # Two small + one large OK under parallel=3 / heavy=1
    s1 = gate.acquire("a", 100, model="mine/both", wait_sec=1)
    s2 = gate.acquire("b", 100, model="mine/both", wait_sec=1)
    h1 = gate.acquire("c", 50_000, model="mine/both", wait_sec=1)
    assert s1["lease_id"] and s2["lease_id"] and h1["heavy"] is True

    blocked = {"ok": False}

    def try_heavy():
        try:
            gate.acquire("d", 50_000, model="mine/both", wait_sec=0.4)
        except AutonomousError as exc:
            blocked["ok"] = exc.code == "llm_heavy_gate_timeout"

    t = threading.Thread(target=try_heavy)
    t.start()
    t.join(timeout=2)
    assert blocked["ok"] is True
    gate.release(s1["lease_id"])
    gate.release(s2["lease_id"])
    gate.release(h1["lease_id"])


def test_http_acquire_release(auth_client, home, tmp_path, monkeypatch):
    h = tmp_path / "pihome"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    (h / ".pi" / "agent").mkdir(parents=True)
    _enable_heavy(h, provider="test", model_id="provider:fixture")

    r = auth_client.post(
        "/api/v1/bots",
        json={"name": "GateBot", "model": "test/provider:fixture"},
    )
    assert r.status_code == 201
    slug = r.get_json()["name"]

    light = auth_client.post(
        f"/api/v1/bots/{slug}/llm-heavy-gate/acquire",
        json={"tokens": 100},
    )
    assert light.status_code == 200
    assert light.get_json()["heavy"] is False

    heavy = auth_client.post(
        f"/api/v1/bots/{slug}/llm-heavy-gate/acquire",
        json={"tokens": 25000, "wait_sec": 2},
    )
    assert heavy.status_code == 200
    body = heavy.get_json()
    assert body["heavy"] is True
    assert body["pool"] == "test/provider:fixture"
    assert body["lease_id"]

    rel = auth_client.post(
        f"/api/v1/bots/{slug}/llm-heavy-gate/release",
        json={"lease_id": body["lease_id"]},
    )
    assert rel.status_code == 200
    assert rel.get_json()["released"] is True
