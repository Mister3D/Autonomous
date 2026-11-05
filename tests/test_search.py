"""Chat message FTS + NL (semantic) search."""

from __future__ import annotations

from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services import search as search_svc


def test_lexical_search_finds_user_message(home, auth_client):
    bot = bots_svc.create_bot("Alpha Search", home=home)
    name = bot["name"]
    chat_svc.send_message(
        name,
        "Je voudrais commander une raclette ce soir",
        home=home,
        trigger_agent=False,
    )
    chat_svc.send_message(
        name,
        "autre chose sans rapport",
        home=home,
        trigger_agent=False,
    )
    search_svc.ensure_fts(home)
    out = search_svc.search_messages("raclette", home=home, mode="lexical")
    assert out["count"] >= 1
    assert any("raclette" in (h["snippet"] or "").lower() for h in out["hits"])
    assert out["hits"][0]["bot"] == name
    assert out["hits"][0]["message_id"]


def test_search_skips_hidden_and_tools(home):
    bot = bots_svc.create_bot("Hidden Search", home=home)
    name = bot["name"]
    chat_svc.create_message(
        name,
        "secret interne invisible",
        role="assistant",
        meta={"hidden_prompt": True},
        home=home,
    )
    chat_svc.create_message(
        name,
        "outil dump raclette",
        role="event",
        meta={"kind": "tool", "tool_name": "vm_click"},
        home=home,
    )
    chat_svc.send_message(
        name, "message visible ananas", home=home, trigger_agent=False
    )
    out = search_svc.search_messages("raclette", home=home, mode="lexical")
    assert all("secret interne" not in (h["snippet"] or "") for h in out["hits"])
    assert all(h["role"] != "event" for h in out["hits"])
    out2 = search_svc.search_messages("ananas", home=home, mode="lexical")
    assert out2["count"] >= 1


def test_nl_semantic_uses_llm_expand_and_pick(home, monkeypatch):
    bot = bots_svc.create_bot("NL Search", home=home)
    name = bot["name"]
    msg = chat_svc.send_message(
        name,
        "Adresse de livraison : 47 rue des Postillons Saint-Denis",
        home=home,
        trigger_agent=False,
    )
    search_svc.ensure_fts(home)

    monkeypatch.setattr(
        search_svc,
        "_llm_config",
        lambda: {"base_url": "http://x", "model": "m", "api_key": "k"},
    )
    monkeypatch.setattr(
        search_svc,
        "_llm_expand_query",
        lambda q: ["adresse", "livraison", "Postillons", "domicile"],
    )

    def fake_pick(q, candidates):
        # Only keep the address message — drop noise.
        return [
            {**c, "mode": "nl_semantic"}
            for c in candidates
            if c["message_id"] == msg["id"]
        ]

    monkeypatch.setattr(search_svc, "_llm_pick_relevant", fake_pick)

    out = search_svc.search_messages(
        "où j'habite en ce moment ?",
        home=home,
        mode="nl",
    )
    assert out["mode"] == "nl_semantic"
    assert out["count"] == 1
    assert out["hits"][0]["message_id"] == msg["id"]
    assert "postillons" in out["hits"][0]["snippet"].lower()


def test_nl_requires_llm(home, monkeypatch):
    from autonomous.services.errors import ValidationError

    monkeypatch.setattr(search_svc, "_llm_config", lambda: None)
    bot = bots_svc.create_bot("No Llm", home=home)
    chat_svc.send_message(bot["name"], "hello", home=home, trigger_agent=False)
    try:
        search_svc.search_nl("où est mon adresse ?", home=home)
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        assert exc.code == "search_nl_no_llm"


def test_auto_picks_nl_for_short_question(home):
    assert search_svc.looks_like_nl("où j'habite ?")
    assert search_svc.looks_like_nl("Site d'achat")
    assert search_svc.looks_like_nl(
        "Tu peux retrouver le message où on parlait de mon adresse ?"
    )
    assert not search_svc.looks_like_nl("raclette")


def test_api_search_messages(home, auth_client, monkeypatch):
    bot = bots_svc.create_bot("Api Search", home=home)
    name = bot["name"]
    chat_svc.send_message(
        name, "unique-token-xyzzy-42", home=home, trigger_agent=False
    )
    r = auth_client.get("/api/v1/search/messages?q=xyzzy&mode=lexical")
    assert r.status_code == 200
    body = r.get_json()
    assert body["count"] >= 1
    assert body["hits"][0]["message_id"]

    monkeypatch.setattr(
        search_svc,
        "_llm_config",
        lambda: {"base_url": "http://x", "model": "m", "api_key": "k"},
    )
    monkeypatch.setattr(search_svc, "_llm_expand_query", lambda q: ["xyzzy", "token"])
    monkeypatch.setattr(
        search_svc,
        "_llm_pick_relevant",
        lambda q, cands: [{**c, "mode": "nl_semantic"} for c in cands[:1]],
    )
    r2 = auth_client.post(
        "/api/v1/search/messages/nl",
        json={"q": "le message avec le jeton bizarre", "limit": 10},
    )
    assert r2.status_code == 200
    assert r2.get_json()["count"] >= 1


def test_clear_messages_clears_fts(home):
    bot = bots_svc.create_bot("Clear Fts", home=home)
    name = bot["name"]
    chat_svc.send_message(
        name, "motcle-ephemere-99", home=home, trigger_agent=False
    )
    assert search_svc.search_messages("ephemere", home=home)["count"] >= 1
    chat_svc.clear_messages(name, home=home)
    assert search_svc.search_messages("ephemere", home=home)["count"] == 0
