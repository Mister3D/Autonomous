"""Inter-bot Tell / Ask messaging."""

from __future__ import annotations

from autonomous.services import botmail as botmail_svc
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc


def test_parse_route():
    assert botmail_svc.parse_route("Tell @bob hello") == {
        "mode": "tell",
        "target": "bob",
        "body": "hello",
    }
    assert botmail_svc.parse_route("Tell @bob: hi there")["mode"] == "tell"
    ask = botmail_svc.parse_route("Ask @alice what time is it?")
    assert ask["mode"] == "ask"
    assert ask["target"] == "alice"
    assert "time" in ask["body"]
    assert botmail_svc.parse_route("hello") is None


def test_parse_route_french_aliases():
    """FR Dit/Demande remain valid composer aliases."""
    assert botmail_svc.parse_route("Dit à @bob salut") == {
        "mode": "tell",
        "target": "bob",
        "body": "salut",
    }
    ask = botmail_svc.parse_route("Demande à @alice quelle heure est-il ?")
    assert ask["mode"] == "ask"
    assert ask["target"] == "alice"


def test_reformulate_peer_message_ask():
    assert (
        botmail_svc.reformulate_peer_message(
            "if she is ready", mode="ask"
        )
        == "Are you ready ?"
    )
    assert (
        botmail_svc.reformulate_peer_message("if you like tea", mode="ask")
        == "Do you like tea ?"
    )
    assert (
        botmail_svc.reformulate_peer_message(
            "what time is it?", mode="ask"
        )
        == "what time is it?"
    )
    assert (
        botmail_svc.reformulate_peer_message(
            "if she is ready", mode="ask", continuation=True
        )
        == "if she is ready"
    )


def test_reformulate_peer_message_tell():
    assert (
        botmail_svc.reformulate_peer_message(
            "that she is late", mode="tell"
        )
        == "You are late"
    )


def test_reformulate_peer_message_french_alias():
    assert (
        botmail_svc.reformulate_peer_message(
            "si elle fait du poney", mode="ask"
        )
        == "Est-ce que tu fais du poney ?"
    )


def test_composer_ask_is_route_intent_not_auto_mail(auth_client, home):
    """Ask @x starts the local agent — does not auto-forward to the peer."""
    auth_client.post("/api/v1/bots", json={"name": "manager"})
    auth_client.post("/api/v1/bots", json={"name": "lol"})
    r = auth_client.post(
        "/api/v1/bots/manager/messages",
        json={"content": "Ask @lol if she rides horses"},
    )
    assert r.status_code == 201
    mgr = auth_client.get("/api/v1/bots/manager/messages").json
    user = [m for m in mgr if m.get("role") == "user"][-1]
    meta = user.get("meta") or {}
    assert meta.get("mail_kind") == "route_intent"
    assert meta.get("to_bot") == "lol"
    assert meta.get("mode") == "ask"
    assert "agent_prompt" in meta
    assert "bot_ask" in meta["agent_prompt"]
    lol = auth_client.get("/api/v1/bots/lol/messages").json
    assert not any(
        (m.get("meta") or {}).get("kind") == "botmail" for m in lol
    )


def test_tell_delivers_when_idle(home):
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    botmail_svc.tell("alice", "bob", "hello bob", home=home, origin="test")
    msgs = chat_svc.list_messages("bob", home=home)
    assert any(
        m["role"] == "system"
        and m["meta"].get("mail_kind") == "tell"
        and "hello bob" in m["content"]
        for m in msgs
    )
    # Sender sees a Sent card with the peer-facing body.
    alice = chat_svc.list_messages("alice", home=home)
    sent = [
        m
        for m in alice
        if m["role"] == "system"
        and (m.get("meta") or {}).get("mail_kind") == "outgoing"
        and (m.get("meta") or {}).get("direction") == "sent"
    ]
    assert sent, alice
    assert "hello bob" in sent[-1]["content"]
    assert sent[-1]["meta"].get("to_bot") == "bob"
    assert sent[-1]["meta"].get("link_message_id")


def test_tell_queues_when_busy(home):
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    bots_svc.patch_bot("bob", {"status": "busy"}, home=home)
    botmail_svc.tell("alice", "bob", "later", home=home, origin="test")
    assert not any(
        m["role"] == "system" and "later" in (m.get("content") or "")
        for m in chat_svc.list_messages("bob", home=home)
    )
    bots_svc.patch_bot("bob", {"status": "idle"}, home=home)
    botmail_svc.on_run_finished("bob", assistant_content="done", home=home)
    assert any(
        m["role"] == "system" and "later" in m["content"]
        for m in chat_svc.list_messages("bob", home=home)
    )


def test_ask_reply_relaunches_asker(home):
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    ask = botmail_svc.ask("alice", "bob", "what time is it?", home=home, origin="test")
    assert ask["state"] == "open"
    bob_msgs = chat_svc.list_messages("bob", home=home)
    assert any(m["meta"].get("mail_kind") == "ask" for m in bob_msgs)

    botmail_svc.on_run_finished("bob", assistant_content="It is 3pm.", home=home)

    ask2 = botmail_svc.get_ask(ask["id"], home=home)
    assert ask2["state"] == "answered"
    assert ask2["answer"] == "It is 3pm."

    alice_msgs = chat_svc.list_messages("alice", home=home)
    answered = [
        m
        for m in alice_msgs
        if m["role"] == "system" and m["meta"].get("mail_kind") == "ask_answered"
    ]
    assert answered, alice_msgs
    assert answered[-1]["content"].strip() == "It is 3pm."
    assert "sent me a message" not in answered[-1]["content"].lower()
    assert answered[-1]["meta"].get("from_bot") == "bob"
    assert answered[-1]["meta"].get("direction") == "received"
    assert not any(
        m["role"] == "user" and "replied" in (m.get("content") or "").lower()
        for m in alice_msgs
    )


def test_old_received_preamble_stripped(home):
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    chat_svc.create_message(
        "bob",
        "@alice m’a envoyé un message :\nhello",
        role="system",
        meta={
            "kind": "botmail",
            "mail_kind": "tell",
            "direction": "received",
            "from_bot": "alice",
        },
        home=home,
    )
    msgs = chat_svc.list_messages("bob", home=home)
    botmail_svc.strip_received_preamble("bob", msgs, home=home)
    hit = [m for m in msgs if m["role"] == "system"][-1]
    assert hit["content"].strip() == "hello"
    assert "envoyé" not in hit["content"].lower()


def test_outgoing_stamp_on_asker_reply(home):
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    botmail_svc.ask("alice", "bob", "what time is it?", home=home, origin="test")
    # Real runs leave an assistant bubble; stamp it as the outgoing ask reply.
    chat_svc.create_message("bob", "It is 3pm.", role="assistant", home=home)
    botmail_svc.on_run_finished("bob", assistant_content="It is 3pm.", home=home)
    bob = chat_svc.list_messages("bob", home=home)
    out = [
        m
        for m in bob
        if m["role"] == "assistant"
        and (m.get("meta") or {}).get("direction") == "sent"
    ]
    assert out, bob
    assert out[-1]["meta"].get("to_bot") == "alice"
    alice = [
        m
        for m in chat_svc.list_messages("alice", home=home)
        if m["role"] == "system" and m["meta"].get("mail_kind") == "ask_answered"
    ]
    assert alice[-1]["meta"].get("direction") == "received"
    assert alice[-1]["meta"].get("from_bot") == "bob"


def test_composer_ask_routes_via_agent_intent(auth_client, home):
    auth_client.post("/api/v1/bots", json={"name": "alice"})
    auth_client.post("/api/v1/bots", json={"name": "bob"})
    r = auth_client.post(
        "/api/v1/bots/alice/messages",
        json={"content": "Ask @bob what is 2+2?"},
    )
    assert r.status_code == 201
    alice = auth_client.get("/api/v1/bots/alice/messages").json
    user = [m for m in alice if m.get("role") == "user"][-1]
    assert (user.get("meta") or {}).get("mail_kind") == "route_intent"
    assert (user.get("meta") or {}).get("to_bot") == "bob"
    bob = auth_client.get("/api/v1/bots/bob/messages").json
    assert not any((m.get("meta") or {}).get("mail_kind") == "ask" for m in bob)
    assert not any(
        "I sent" in (m.get("content") or "") or "J’ai envoyé" in (m.get("content") or "")
        for m in alice
    )


def test_composer_unknown_bot(auth_client):
    auth_client.post("/api/v1/bots", json={"name": "solo"})
    r = auth_client.post(
        "/api/v1/bots/solo/messages",
        json={"content": "Tell @unknown hello"},
    )
    assert r.status_code == 201
    msgs = auth_client.get("/api/v1/bots/solo/messages").json
    assert any(
        m["role"] == "system" and "not found" in (m.get("content") or "").lower()
        for m in msgs
    )


def test_mail_api_tell(auth_client):
    auth_client.post("/api/v1/bots", json={"name": "a1"})
    auth_client.post("/api/v1/bots", json={"name": "b1"})
    r = auth_client.post(
        "/api/v1/bots/a1/mail/tell",
        json={"to": "b1", "content": "ping"},
    )
    assert r.status_code == 201, r.data
    assert r.json["ok"] is True
    bob = auth_client.get("/api/v1/bots/b1/messages").json
    assert any(
        m.get("role") == "system" and "ping" in (m.get("content") or "")
        for m in bob
    )


def test_ask_deep_link_meta(home):
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    user = chat_svc.send_message("alice", "Ask @bob what time is it?", home=home)
    assert (user.get("meta") or {}).get("mail_kind") == "route_intent"
    ask = botmail_svc.ask(
        "alice",
        "bob",
        "What time is it?",
        home=home,
        origin="test",
        origin_message_id=user["id"],
    )
    assert ask["state"] == "open"
    alice = chat_svc.list_messages("alice", home=home)
    user_msg = next(m for m in alice if m["id"] == user["id"])
    sent = [
        m
        for m in alice
        if (m.get("meta") or {}).get("mail_kind") == "outgoing"
    ][-1]
    bob = chat_svc.list_messages("bob", home=home)
    recv = [m for m in bob if (m.get("meta") or {}).get("mail_kind") == "ask"][-1]
    assert recv["meta"].get("link_bot") == "alice"
    # Received card deep-links to the Sent card (peer-facing body).
    assert recv["meta"].get("link_message_id") == sent["id"]
    assert sent["meta"].get("link_message_id") == recv["id"]
    assert user_msg["meta"].get("link_message_id") == recv["id"]
    assert user_msg["meta"].get("link_bot") == "bob"


def test_ask_links_latest_route_intent_automatically(home):
    """API ask without origin_message_id still deep-links the Tell/Ask bubble."""
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    user = chat_svc.send_message("alice", "Ask @bob what time is it?", home=home)
    botmail_svc.ask("alice", "bob", "What time is it?", home=home, origin="api")
    alice = chat_svc.list_messages("alice", home=home)
    user_msg = next(m for m in alice if m["id"] == user["id"])
    sent = [
        m
        for m in alice
        if (m.get("meta") or {}).get("mail_kind") == "outgoing"
    ][-1]
    bob = chat_svc.list_messages("bob", home=home)
    recv = [m for m in bob if (m.get("meta") or {}).get("mail_kind") == "ask"][-1]
    assert user_msg["meta"].get("link_message_id") == recv["id"]
    assert recv["meta"].get("link_message_id") == sent["id"]


def test_delete_purges_queued_mail(home):
    """Deleting the sender must drop queued mail so a recreated peer stays clean."""
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    bots_svc.patch_bot("bob", {"status": "busy"}, home=home)
    botmail_svc.tell("alice", "bob", "zombie message", home=home, origin="test")
    bots_svc.delete_bot("alice", home=home, destroy_desk=False)
    bots_svc.patch_bot("bob", {"status": "idle"}, home=home)
    botmail_svc.on_run_finished("bob", assistant_content="done", home=home)
    assert not any(
        "zombie message" in (m.get("content") or "")
        for m in chat_svc.list_messages("bob", home=home)
    )


def test_drain_skips_ghost_sender_after_recreate(home):
    """Same slug recreated must not receive mail queued by a deleted peer."""
    from autonomous.db import get_db

    bots_svc.create_bot("horloge", home=home)
    bots_svc.create_bot("test", home=home)
    old_test_id = bots_svc.get_bot("test", home=home)["id"]
    bots_svc.patch_bot("test", {"status": "busy"}, home=home)
    botmail_svc.tell("horloge", "test", "It is 4:30pm", home=home, origin="test")
    with get_db(home) as conn:
        conn.execute("DELETE FROM bots WHERE name IN ('horloge', 'test')")
    bots_svc.create_bot("Test", slug="test", home=home)
    new_test_id = bots_svc.get_bot("test", home=home)["id"]
    assert new_test_id != old_test_id
    botmail_svc.on_run_finished("test", assistant_content="fnac done", home=home)
    assert not any(
        "4:30" in (m.get("content") or "")
        or "horloge" in (m.get("content") or "").lower()
        for m in chat_svc.list_messages("test", home=home)
    )


def test_bot_has_stable_uuid(home):
    a = bots_svc.create_bot("alice", home=home)
    assert a.get("id")
    assert bots_svc.looks_like_bot_id(a["id"])
    assert bots_svc.get_bot_by_id(a["id"], home=home)["name"] == a["name"]
    assert bots_svc.bot_uuid("alice", home=home) == a["id"]


def test_rescue_mentions_never_auto_mails(home):
    """Mention / send-claim without bot_tell must NOT invent peer mail from user text."""
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    chat_svc.create_message(
        "alice",
        "I think @bob rides horses — do you like that too?",
        role="user",
        home=home,
    )
    rescued = botmail_svc.maybe_rescue_mentions(
        "alice",
        "I forwarded that to @bob; I'll let you know as soon as I get a reply.",
        mail_sent=[],
        home=home,
    )
    assert rescued == []
    assert not any(
        (m.get("meta") or {}).get("kind") == "botmail"
        for m in chat_svc.list_messages("bob", home=home)
    )


def test_rescue_skips_bare_citation(home):
    bots_svc.create_bot("manager", home=home)
    bots_svc.create_bot("pascaline", home=home)
    chat_svc.create_message(
        "manager",
        "Cite @pascaline without sending her a message",
        role="user",
        home=home,
    )
    rescued = botmail_svc.maybe_rescue_mentions(
        "manager",
        "Pascaline is your bot. She rides horses.",
        mail_sent=[],
        home=home,
    )
    assert rescued == []


def test_rescue_skips_cite_with_at_token(home):
    bots_svc.create_bot("manager", home=home)
    bots_svc.create_bot("pascaline", home=home)
    chat_svc.create_message("manager", "With the @", role="user", home=home)
    rescued = botmail_svc.maybe_rescue_mentions(
        "manager",
        "Here: @pascaline\n\nAs you asked me not to send her a message, "
        "I am only citing her in this chat.",
        mail_sent=[],
        home=home,
    )
    assert rescued == []
    assert not chat_svc.list_messages("pascaline", home=home)


def test_rescue_via_on_run_finished_does_not_mail(home):
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    chat_svc.create_message(
        "alice", "Tell bob hello from me", role="user", home=home
    )
    botmail_svc.on_run_finished(
        "alice",
        assistant_content="Ok, writing to @bob right away.",
        mail_sent=[],
        home=home,
    )
    assert not any(
        (m.get("meta") or {}).get("kind") == "botmail"
        for m in chat_svc.list_messages("bob", home=home)
    )


def test_rescue_skipped_when_answering_ask(home):
    """Answering an ask with @asker in the text must not re-mail the asker."""
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    ask = botmail_svc.ask("alice", "bob", "what time is it?", home=home, origin="test")
    before = len(chat_svc.list_messages("alice", home=home))
    botmail_svc.on_run_finished(
        "bob",
        assistant_content="@alice, it is 3pm.",
        mail_sent=[],
        home=home,
    )
    ask2 = botmail_svc.get_ask(ask["id"], home=home)
    assert ask2["state"] == "answered"
    alice = chat_svc.list_messages("alice", home=home)
    mail = [
        m
        for m in alice[before:]
        if (m.get("meta") or {}).get("kind") == "botmail"
    ]
    assert len(mail) == 1
    assert mail[0]["meta"].get("mail_kind") == "ask_answered"


def test_orphan_tell_relay_when_asker_awaits(home):
    """bot_tell + « I'll forward the reply » → peer answer is mirrored back."""
    bots_svc.create_bot("trump", home=home)
    bots_svc.create_bot("etat-major", home=home)
    chat_svc.create_message(
        "trump",
        "Ask @etat-major if we can proceed",
        role="user",
        home=home,
    )
    botmail_svc.tell(
        "trump",
        "etat-major",
        "Can we proceed?",
        home=home,
        origin="test",
    )
    chat_svc.create_message(
        "trump",
        "I forwarded that to @etat-major. I'll let you know as soon as I get a reply.",
        role="assistant",
        home=home,
    )
    botmail_svc.on_run_finished(
        "etat-major",
        assistant_content="No, that is not advisable.",
        home=home,
    )
    trump_msgs = chat_svc.list_messages("trump", home=home)
    answered = [
        m
        for m in trump_msgs
        if m["role"] == "system"
        and (m.get("meta") or {}).get("mail_kind") == "ask_answered"
    ]
    assert answered, trump_msgs
    assert "not advisable" in answered[-1]["content"]
    assert answered[-1]["meta"].get("from_bot") == "etat-major"


def test_drain_cancels_orphan_queued_without_purge(home):
    """Defense in depth: cancel queued rows whose from_bot vanished mid-flight."""
    from autonomous.db import get_db

    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    bots_svc.patch_bot("bob", {"status": "busy"}, home=home)
    botmail_svc.tell("alice", "bob", "still here", home=home, origin="test")
    with get_db(home) as conn:
        conn.execute("DELETE FROM bots WHERE name = ?", ("alice",))
    bots_svc.patch_bot("bob", {"status": "idle"}, home=home)
    botmail_svc.on_run_finished("bob", assistant_content="done", home=home)
    assert not any(
        "still here" in (m.get("content") or "")
        for m in chat_svc.list_messages("bob", home=home)
    )
    bob_id = bots_svc.get_bot("bob", home=home)["id"]
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT state FROM bot_inbox WHERE bot = ? ORDER BY created_at DESC LIMIT 1",
            (bob_id,),
        ).fetchone()
    assert row is not None
    assert row["state"] == "cancelled"
