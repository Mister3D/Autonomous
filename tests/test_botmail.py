"""Inter-bot Dit / Demande messaging."""

from __future__ import annotations

from autonomous.services import botmail as botmail_svc
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc


def test_parse_route():
    assert botmail_svc.parse_route("Dit à @bob salut") == {
        "mode": "tell",
        "target": "bob",
        "body": "salut",
    }
    assert botmail_svc.parse_route("Dis à @bob: hello")["mode"] == "tell"
    ask = botmail_svc.parse_route("Demande à @alice quelle heure est-il ?")
    assert ask["mode"] == "ask"
    assert ask["target"] == "alice"
    assert "heure" in ask["body"]
    assert botmail_svc.parse_route("bonjour") is None


def test_tell_delivers_when_idle(home):
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    botmail_svc.tell("alice", "bob", "salut bob", home=home, origin="test")
    msgs = chat_svc.list_messages("bob", home=home)
    assert any(
        m["role"] == "system"
        and m["meta"].get("mail_kind") == "tell"
        and "salut bob" in m["content"]
        for m in msgs
    )


def test_tell_queues_when_busy(home):
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    bots_svc.patch_bot("bob", {"status": "busy"}, home=home)
    botmail_svc.tell("alice", "bob", "plus tard", home=home, origin="test")
    assert not any(
        m["role"] == "system" and "plus tard" in (m.get("content") or "")
        for m in chat_svc.list_messages("bob", home=home)
    )
    bots_svc.patch_bot("bob", {"status": "idle"}, home=home)
    botmail_svc.on_run_finished("bob", assistant_content="done", home=home)
    assert any(
        m["role"] == "system" and "plus tard" in m["content"]
        for m in chat_svc.list_messages("bob", home=home)
    )


def test_ask_reply_relaunches_asker(home):
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    ask = botmail_svc.ask("alice", "bob", "quelle heure ?", home=home, origin="test")
    assert ask["state"] == "open"
    bob_msgs = chat_svc.list_messages("bob", home=home)
    assert any(m["meta"].get("mail_kind") == "ask" for m in bob_msgs)

    botmail_svc.on_run_finished("bob", assistant_content="Il est 15h.", home=home)

    ask2 = botmail_svc.get_ask(ask["id"], home=home)
    assert ask2["state"] == "answered"
    assert ask2["answer"] == "Il est 15h."

    alice_msgs = chat_svc.list_messages("alice", home=home)
    answered = [
        m
        for m in alice_msgs
        if m["role"] == "system" and m["meta"].get("mail_kind") == "ask_answered"
    ]
    assert answered, alice_msgs
    assert answered[-1]["content"].strip() == "Il est 15h."
    assert "envoyé un message" not in answered[-1]["content"].lower()
    assert answered[-1]["meta"].get("from_bot") == "bob"
    assert answered[-1]["meta"].get("direction") == "received"
    # No fake user bubble « [@bot a répondu] ».
    assert not any(
        m["role"] == "user" and "a répondu" in (m.get("content") or "")
        for m in alice_msgs
    )


def test_old_received_preamble_stripped(home):
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    chat_svc.create_message(
        "bob",
        "@alice m’a envoyé un message :\nsalut",
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
    assert msgs[-1]["content"] == "salut"


def test_ask_reply_marks_sent_bubble(home):
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    botmail_svc.ask("alice", "bob", "quelle heure ?", home=home, origin="test")
    sent = chat_svc.create_message(
        "bob", "@alice, il est 16h30.", role="assistant", home=home
    )
    botmail_svc.on_run_finished(
        "bob", assistant_content="@alice, il est 16h30.", home=home
    )
    bubble = next(
        m for m in chat_svc.list_messages("bob", home=home) if m["id"] == sent["id"]
    )
    assert bubble["meta"].get("direction") == "sent"
    assert bubble["meta"].get("mail_kind") == "outgoing"
    assert bubble["meta"].get("to_bot") == "alice"
    alice = [
        m
        for m in chat_svc.list_messages("alice", home=home)
        if m["role"] == "system" and m["meta"].get("mail_kind") == "ask_answered"
    ]
    assert alice[-1]["meta"].get("direction") == "received"
    assert alice[-1]["meta"].get("from_bot") == "bob"


def test_composer_demande_routes(auth_client, home):
    auth_client.post("/api/v1/bots", json={"name": "alice"})
    auth_client.post("/api/v1/bots", json={"name": "bob"})
    r = auth_client.post(
        "/api/v1/bots/alice/messages",
        json={"content": "Demande à @bob combien font 2+2 ?"},
    )
    assert r.status_code == 201
    bob = auth_client.get("/api/v1/bots/bob/messages").json
    assert any(
        m.get("role") == "system"
        and "2+2" in (m.get("content") or "")
        and m.get("meta", {}).get("mail_kind") == "ask"
        for m in bob
    )
    alice = auth_client.get("/api/v1/bots/alice/messages").json
    # Pas d’accusé « J’ai envoyé… » — seulement la bulle user Dit/Demande.
    assert not any(
        "J’ai envoyé" in (m.get("content") or "") or "J'ai envoyé" in (m.get("content") or "")
        for m in alice
    )
    assert not any(m.get("meta", {}).get("mail_kind") == "ask_sent" for m in alice)


def test_composer_unknown_bot(auth_client):
    auth_client.post("/api/v1/bots", json={"name": "solo"})
    r = auth_client.post(
        "/api/v1/bots/solo/messages",
        json={"content": "Dit à @inconnu hello"},
    )
    assert r.status_code == 201
    msgs = auth_client.get("/api/v1/bots/solo/messages").json
    assert any(
        m["role"] == "system" and "introuvable" in (m.get("content") or "").lower()
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
    user = chat_svc.send_message("alice", "Demande à @bob quelle heure ?", home=home)
    alice = chat_svc.list_messages("alice", home=home)
    user_msg = next(m for m in alice if m["id"] == user["id"])
    # Meta may be enriched after route (link back to peer card).
    assert (user_msg.get("meta") or {}).get("to_bot") == "bob" or (
        user_msg.get("meta") or {}
    ).get("mail_kind") in ("ask", None)
    # Reload after peer delivery patches link_message_id onto the user bubble.
    alice = chat_svc.list_messages("alice", home=home)
    user_msg = next(m for m in alice if m["id"] == user["id"])
    bob = chat_svc.list_messages("bob", home=home)
    recv = [m for m in bob if (m.get("meta") or {}).get("mail_kind") == "ask"][-1]
    assert recv["meta"].get("link_bot") == "alice"
    assert recv["meta"].get("link_message_id") == user["id"]
    assert user_msg["meta"].get("link_message_id") == recv["id"]
    assert user_msg["meta"].get("link_bot") == "bob"


def test_delete_purges_queued_mail(home):
    """Deleting the sender must drop queued mail so a recreated peer stays clean."""
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    bots_svc.patch_bot("bob", {"status": "busy"}, home=home)
    botmail_svc.tell("alice", "bob", "message zombie", home=home, origin="test")
    bots_svc.delete_bot("alice", home=home, destroy_desk=False)
    bots_svc.patch_bot("bob", {"status": "idle"}, home=home)
    botmail_svc.on_run_finished("bob", assistant_content="done", home=home)
    assert not any(
        "message zombie" in (m.get("content") or "")
        for m in chat_svc.list_messages("bob", home=home)
    )


def test_drain_skips_ghost_sender_after_recreate(home):
    """Same slug recreated must not receive mail queued by a deleted peer.

    Inbox rows key off bots.id (UUID). A new bot with the same slug gets a new
    id, so the old queued tell is invisible to the drain.
    """
    from autonomous.db import get_db

    bots_svc.create_bot("horloge", home=home)
    bots_svc.create_bot("test", home=home)
    old_test_id = bots_svc.get_bot("test", home=home)["id"]
    bots_svc.patch_bot("test", {"status": "busy"}, home=home)
    botmail_svc.tell("horloge", "test", "Il est 16h30", home=home, origin="test")
    # Broken delete that leaves inbox rows (UUID still points at the dead life).
    with get_db(home) as conn:
        conn.execute("DELETE FROM bots WHERE name IN ('horloge', 'test')")
    bots_svc.create_bot("Test", slug="test", home=home)
    new_test_id = bots_svc.get_bot("test", home=home)["id"]
    assert new_test_id != old_test_id
    botmail_svc.on_run_finished("test", assistant_content="fnac done", home=home)
    assert not any(
        "16h30" in (m.get("content") or "")
        or "horloge" in (m.get("content") or "").lower()
        for m in chat_svc.list_messages("test", home=home)
    )


def test_bot_has_stable_uuid(home):
    a = bots_svc.create_bot("alice", home=home)
    assert a.get("id")
    assert bots_svc.looks_like_bot_id(a["id"])
    assert bots_svc.get_bot_by_id(a["id"], home=home)["name"] == a["name"]
    assert bots_svc.bot_uuid("alice", home=home) == a["id"]


def test_rescue_mentions_sends_ask_when_no_mail_tool(home):
    """Assistant names @bob and awaits a reply, but never called bot_ask → rescue."""
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    chat_svc.create_message(
        "alice",
        "Demande à bob si on peut y aller",
        role="user",
        home=home,
    )
    rescued = botmail_svc.maybe_rescue_mentions(
        "alice",
        "J’ai transmis à @bob, je te fais suivre dès que je reçois sa réponse.",
        mail_sent=[],
        home=home,
    )
    assert len(rescued) == 1
    assert rescued[0]["to"] == "bob"
    assert rescued[0]["mode"] == "ask"
    bob = chat_svc.list_messages("bob", home=home)
    assert any(
        m["role"] == "system"
        and m["meta"].get("mail_kind") == "ask"
        and "y aller" in (m.get("content") or "")
        for m in bob
    )


def test_rescue_mentions_skips_when_already_mailed(home):
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    chat_svc.create_message("alice", "ping bob", role="user", home=home)
    rescued = botmail_svc.maybe_rescue_mentions(
        "alice",
        "Message envoyé à @bob.",
        mail_sent=[{"tool": "bot_tell", "to": "bob"}],
        home=home,
    )
    assert rescued == []
    assert not any(
        m["meta"].get("kind") == "botmail"
        for m in chat_svc.list_messages("bob", home=home)
        if isinstance(m.get("meta"), dict)
    )


def test_rescue_via_on_run_finished(home):
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    chat_svc.create_message(
        "alice", "Dis à bob bonjour de ma part", role="user", home=home
    )
    botmail_svc.on_run_finished(
        "alice",
        assistant_content="Ok, j’écris à @bob tout de suite.",
        mail_sent=[],
        home=home,
    )
    assert any(
        m["role"] == "system"
        and m["meta"].get("mail_kind") == "tell"
        and "bonjour" in (m.get("content") or "").lower()
        for m in chat_svc.list_messages("bob", home=home)
    )


def test_rescue_skipped_when_answering_ask(home):
    """Answering an ask with @asker in the text must not re-mail the asker."""
    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    ask = botmail_svc.ask("alice", "bob", "quelle heure ?", home=home, origin="test")
    before = len(chat_svc.list_messages("alice", home=home))
    botmail_svc.on_run_finished(
        "bob",
        assistant_content="@alice, il est 15h.",
        mail_sent=[],
        home=home,
    )
    ask2 = botmail_svc.get_ask(ask["id"], home=home)
    assert ask2["state"] == "answered"
    # One ask_answered card, no extra tell/ask from rescue.
    alice = chat_svc.list_messages("alice", home=home)
    mail = [
        m
        for m in alice[before:]
        if (m.get("meta") or {}).get("kind") == "botmail"
    ]
    assert len(mail) == 1
    assert mail[0]["meta"].get("mail_kind") == "ask_answered"


def test_orphan_tell_relay_when_asker_awaits(home):
    """bot_tell + « je te fais suivre » → peer answer is mirrored back."""
    bots_svc.create_bot("trump", home=home)
    bots_svc.create_bot("etat-major", home=home)
    chat_svc.create_message(
        "trump",
        "Demande à l'état-major si on peut bombarder",
        role="user",
        home=home,
    )
    botmail_svc.tell(
        "trump",
        "etat-major",
        "Peut-on bombarder ?",
        home=home,
        origin="test",
    )
    chat_svc.create_message(
        "trump",
        "J’ai transmis à @etat-major. Je te ferai suivre dès que je reçois sa réponse.",
        role="assistant",
        home=home,
    )
    botmail_svc.on_run_finished(
        "etat-major",
        assistant_content="Non, ce n’est pas envisageable.",
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
    assert "pas envisageable" in answered[-1]["content"]
    assert answered[-1]["meta"].get("from_bot") == "etat-major"


def test_drain_cancels_orphan_queued_without_purge(home):
    """Defense in depth: cancel queued rows whose from_bot vanished mid-flight."""
    from autonomous.db import get_db

    bots_svc.create_bot("alice", home=home)
    bots_svc.create_bot("bob", home=home)
    bots_svc.patch_bot("bob", {"status": "busy"}, home=home)
    botmail_svc.tell("alice", "bob", "encore là", home=home, origin="test")
    # Simulate a half-broken delete that left inbox rows (pre-fix DB).
    with get_db(home) as conn:
        conn.execute("DELETE FROM bots WHERE name = ?", ("alice",))
    bots_svc.patch_bot("bob", {"status": "idle"}, home=home)
    botmail_svc.on_run_finished("bob", assistant_content="done", home=home)
    assert not any(
        "encore là" in (m.get("content") or "")
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
