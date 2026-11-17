"""LLM-turn chat cards: open, finalize, full provider JSON on disk."""

from __future__ import annotations

import json

from autonomous.paths import bot_pi_dir
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services import llm_turns as llm_turns_svc


def test_summarize_assistant_message_includes_thinking_and_tools():
    detail = llm_turns_svc.summarize_assistant_message(
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "plan A"},
                {"type": "text", "text": "Hi"},
                {
                    "type": "toolCall",
                    "name": "notebook_list",
                    "arguments": {},
                },
            ],
        }
    )
    assert "[thinking]" in detail
    assert "Hi" in detail
    assert "[tool notebook_list]" in detail


def test_provider_request_file_and_response_json(home):
    bots_svc.create_bot("llmjson", home=home)
    turns = bot_pi_dir("llmjson", home) / "llm_turns"
    turns.mkdir(parents=True, exist_ok=True)
    pending = turns / "req_test.json"
    payload = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "hello JSON"}],
        "tools": [{"name": "vm_look"}],
    }
    pending.write_text(json.dumps(payload), encoding="utf-8")

    opened = llm_turns_svc.open_turn(
        "llmjson",
        request_file="llm_turns/req_test.json",
        request_kind="provider",
        home=home,
    )
    assert opened["meta"]["kind"] == "llm_turn"
    assert opened["meta"]["request_kind"] == "provider"
    assert opened["meta"]["request_file"].endswith("_request.json")
    stored = llm_turns_svc.get_payload(
        "llmjson", opened["id"], side="request", home=home
    )
    assert stored["model"] == "test-model"
    assert stored["messages"][0]["content"] == "hello JSON"

    assistant = {
        "role": "assistant",
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input": 10, "output": 2},
        "stopReason": "stop",
    }
    sealed = llm_turns_svc.finalize_turn(
        "llmjson",
        response="ok",
        response_json=assistant,
        tokens_in=10,
        tokens_out=2,
        home=home,
    )
    assert sealed["meta"]["response_file"].endswith("_response.json")
    got = llm_turns_svc.get_payload(
        "llmjson", sealed["id"], side="response", home=home
    )
    assert got["role"] == "assistant"
    assert got["content"][0]["text"] == "ok"


def test_seal_turn_for_tools_then_finalize_usage(home):
    bots_svc.create_bot("llmdesk", home=home)
    opened = llm_turns_svc.open_turn("llmdesk", home=home)
    sealed = llm_turns_svc.seal_turn_for_tools(
        "llmdesk", tool_name="vm_request_desk", home=home
    )
    assert sealed["id"] == opened["id"]
    assert sealed["meta"]["status"] == "done"
    assert sealed["meta"]["usage_pending"] is True

    final = llm_turns_svc.finalize_turn(
        "llmdesk",
        response="[tool vm_request_desk]",
        response_json={"role": "assistant", "content": []},
        tokens_in=900,
        tokens_out=12,
        home=home,
    )
    assert final["id"] == opened["id"]
    assert final["meta"]["tokens_in"] == 900
    assert final["meta"].get("usage_pending") is None


def test_close_running_turns(home):
    bots_svc.create_bot("llmstop", home=home)
    llm_turns_svc.open_turn("llmstop", home=home)
    n = llm_turns_svc.close_running_turns(
        "llmstop", home=home, error="stopped"
    )
    assert n == 1
    msgs = chat_svc.list_messages("llmstop", limit=5, home=home)
    card = next(m for m in msgs if (m.get("meta") or {}).get("kind") == "llm_turn")
    assert card["meta"]["status"] == "error"


def test_purge_on_clear(home):
    bots_svc.create_bot("llmpurge", home=home)
    turns = bot_pi_dir("llmpurge", home) / "llm_turns"
    turns.mkdir(parents=True, exist_ok=True)
    (turns / "junk.json").write_text("{}", encoding="utf-8")
    llm_turns_svc.purge_turn_files("llmpurge", home=home)
    assert not turns.exists()


def test_late_open_reuses_usage_pending(home):
    """Late llm_trace POST after seal must not create a second card under desk."""
    bots_svc.create_bot("llmlate", home=home)
    opened = llm_turns_svc.open_turn("llmlate", home=home)
    llm_turns_svc.seal_turn_for_tools(
        "llmlate", tool_name="vm_request_desk", home=home
    )
    turns = bot_pi_dir("llmlate", home) / "llm_turns"
    turns.mkdir(parents=True, exist_ok=True)
    pending = turns / "req_late.json"
    pending.write_text(
        json.dumps({"messages": [{"role": "user", "content": "late"}]}),
        encoding="utf-8",
    )
    again = llm_turns_svc.open_turn(
        "llmlate",
        request_file="llm_turns/req_late.json",
        request_kind="provider",
        home=home,
    )
    assert again["id"] == opened["id"]
    msgs = [
        m
        for m in chat_svc.list_messages("llmlate", limit=10, home=home)
        if (m.get("meta") or {}).get("kind") == "llm_turn"
    ]
    assert len(msgs) == 1


def test_llm_turns_api(home, auth_client):
    bots_svc.create_bot("llmapi", home=home)
    turns = bot_pi_dir("llmapi", home) / "llm_turns"
    turns.mkdir(parents=True, exist_ok=True)
    pending = turns / "req_api.json"
    pending.write_text(
        json.dumps({"messages": [{"role": "user", "content": "ping"}]}),
        encoding="utf-8",
    )
    r = auth_client.post(
        "/api/v1/bots/llmapi/llm-turns",
        json={
            "request_file": "llm_turns/req_api.json",
            "request_kind": "provider",
        },
    )
    assert r.status_code == 201
    body = r.get_json()
    assert body["meta"]["request_kind"] == "provider"
    mid = body["id"]
    g = auth_client.get(f"/api/v1/bots/llmapi/llm-turns/{mid}/request")
    assert g.status_code == 200
    assert g.get_json()["messages"][0]["content"] == "ping"
