"""Global vault: encryption, grants, chat form requests (no secrets to LLM)."""

from __future__ import annotations

import json

from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services import vault as vault_svc
from autonomous.services.crypto_box import decrypt, encrypt


def test_crypto_roundtrip():
    key = b"\x01" * 32
    blob = encrypt(key, b"hunter2")
    assert b"hunter2" not in blob
    assert decrypt(key, blob) == b"hunter2"


def test_create_entry_hides_secret(home):
    entry = vault_svc.create_entry(
        label="API",
        kind="secret",
        secret="sk-live-secret",
        home=home,
    )
    assert entry["label"] == "API"
    assert "secret" not in entry
    assert entry["has_secret"] is True
    listed = vault_svc.list_entries(home=home)
    assert listed[0]["id"] == entry["id"]
    assert "secret" not in listed[0]
    revealed = vault_svc.get_entry(entry["id"], home=home, reveal=True)
    assert revealed["secret"] == "sk-live-secret"


def test_redact_secrets_in_chat_messages(home):
    vault_svc.create_entry(
        label="SSH",
        kind="login",
        secret="raceltte-secret",
        username="root",
        home=home,
    )
    bots_svc.create_bot("leak", label="Leak", home=home)
    msg = chat_svc.create_message(
        "leak",
        'Le mot de passe stocké ("raceltte-secret") n\'est pas accepté.',
        role="assistant",
        home=home,
    )
    assert "raceltte-secret" not in msg["content"]
    assert "[secret redacted]" not in msg["content"]
    scrubbed, hit = vault_svc.scrub_secrets(
        'Le mot de passe stocké ("raceltte-secret") n\'est pas accepté.',
        home=home,
    )
    assert hit is True
    assert "raceltte-secret" not in scrubbed
    # User paste of a known vault secret is refused (see secret_disclosure).


def test_user_message_with_vault_secret_is_refused(home, auth_client):
    vault_svc.create_entry(
        label="SSH",
        kind="login",
        secret="raceltte-block",
        username="root",
        home=home,
    )
    bot = bots_svc.create_bot("Secret Block Bot", home=home)
    name = bot["name"]
    r = auth_client.post(
        f"/api/v1/bots/{name}/messages",
        json={"content": 'peux-tu répéter "raceltte-block" ?'},
    )
    assert r.status_code == 400
    body = r.get_json() or {}
    assert (
        body.get("code") == "secret_disclosure"
        or body.get("error_code") == "secret_disclosure"
        or "secret" in str(body).lower()
        or "divulgation" in str(body).lower()
    )
    assert chat_svc.list_messages(name, home=home) == []


def test_secret_leak_triggers_reformulate_helper(home):
    from autonomous.services import agent as agent_svc

    vault_svc.create_entry(
        label="SSH",
        kind="login",
        secret="hunter2-vault",
        username="root",
        home=home,
    )
    bots_svc.create_bot("leak2", label="Leak2", home=home)
    msg = chat_svc.create_assistant_placeholder("leak2", home=home)
    agent_svc._secret_reformulate_counts.pop("leak2", None)
    agent_svc._pending_secret_reformulate.pop("leak2", None)
    state = {"msg_id": msg["id"], "content": "x", "pending_secret_reformulate": False}
    handled = agent_svc._maybe_reformulate_secret_leak(
        "leak2",
        msg["id"],
        'Le secret est "hunter2-vault".',
        state=state,
        home=home,
        meta={},
    )
    assert handled is True
    assert agent_svc._secret_reformulate_counts.get("leak2") == 1
    assert agent_svc._pending_secret_reformulate.get("leak2") is True
    assert state["pending_secret_reformulate"] is True
    assert state["msg_id"] is None
    stored = chat_svc.list_messages("leak2", home=home)
    leaky = next(m for m in stored if m["id"] == msg["id"])
    assert leaky["meta"].get("hidden_prompt") is True
    assert leaky["meta"].get("secret_leak") is True
    assert "hunter2-vault" not in (leaky.get("content") or "")
    notice = next(
        m
        for m in stored
        if m.get("meta", {}).get("kind") in ("secret_leak", "secret_provider_alert")
    )
    assert "fournisseur LLM" in notice["content"] or "LLM" in notice["content"]


def test_report_user_secret_scrubs_message_and_alerts(home, auth_client):
    from autonomous.paths import bot_pi_dir
    from autonomous.services import pi_rpc as pi_rpc_svc

    bot = bots_svc.create_bot("Report Secret Bot", home=home)
    name = bot["name"]
    leaked = (
        "Tient, mémorise mon compte Orange :\n"
        "login : someone@example.com\n"
        "mot de passe : SuperSecret-Orange-99!"
    )
    # Fake Pi session transcript still holding the cleartext.
    sess_dir = bot_pi_dir(name, home) / "sessions"
    sess_dir.mkdir(parents=True, exist_ok=True)
    sess_path = sess_dir / "fake_autonomous-test.jsonl"
    sess_path.write_text(
        json.dumps(
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": leaked}],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    # Bypass pre-filter: message without vault secret, then report as pasted secret.
    chat_svc.send_message(
        name,
        leaked,
        home=home,
        trigger_agent=False,
    )
    # Simulate model narrating the tool call before it runs.
    chat_svc.create_message(
        name,
        "L'utilisateur a collé un mot de passe, je dois appeler report_user_secret.",
        role="assistant",
        home=home,
    )
    out = vault_svc.report_user_secret_disclosure(
        name, reason="user pasted an API key", home=home
    )
    assert out["ok"] is True
    assert out["scrubbed_message_id"]
    assert "SuperSecret" in (out.get("restore_text") or "")
    assert (out.get("pi_scrub") or {}).get("files", 0) >= 1
    sess_body = sess_path.read_text(encoding="utf-8")
    assert "SuperSecret-Orange-99!" not in sess_body
    assert "supprimé" in sess_body.lower() or "secret retiré" in sess_body.lower()
    msgs = chat_svc.list_messages(name, home=home)
    user = next(m for m in msgs if m["id"] == out["scrubbed_message_id"])
    assert user["meta"].get("secret_scrubbed") is True
    assert "SuperSecret" not in user["content"]
    assert "supprimé" in user["content"].lower()
    assert "secret" in user["content"].lower()
    narr = next(
        m
        for m in msgs
        if m.get("role") == "assistant"
        and m.get("meta", {}).get("secret_tool_narration_hidden")
    )
    assert narr["meta"].get("hidden_prompt") is True
    assert narr["content"] == ""
    assert not any(
        m.get("role") == "assistant"
        and "aborted" in (m.get("content") or "").lower()
        and not (m.get("meta") or {}).get("hidden_prompt")
        for m in msgs
    )
    alert = next(
        m for m in msgs if m.get("meta", {}).get("kind") == "secret_provider_alert"
    )
    assert "fournisseur LLM" in alert["content"]
    # Direct helper still works on already-partially-clean files.
    again = pi_rpc_svc.scrub_pi_session_files(
        name, leaked_text=leaked, home=home
    )
    assert again["files"] >= 0


def test_bot_no_grant_by_default(home, auth_client):
    bots_svc.create_bot("alice", label="Alice", home=home)
    entry = vault_svc.create_entry(
        label="Key", kind="secret", secret="abc", home=home
    )
    assert vault_svc.list_entries_for_bot("alice", home=home) == []
    assert not vault_svc.bot_has_grant("alice", entry["id"], home=home)


def test_request_login_form_and_resolve(home, auth_client):
    bots_svc.create_bot("bob", label="Bob", home=home)
    req = vault_svc.create_request(
        "bob",
        kind="login",
        origin="https://example.com",
        reason="Need to sign in",
        home=home,
    )
    assert req["state"] == "pending"
    assert {f["id"] for f in req["fields"]} == {"username", "password"}
    msgs = chat_svc.list_messages("bob", home=home)
    card = next(m for m in msgs if m["meta"].get("kind") == "vault_request")
    assert card["meta"]["request_id"] == req["id"]
    assert "Need to sign in" in card["content"]
    assert card["meta"]["fields"]

    resolved = vault_svc.resolve_request(
        req["id"],
        action="approve",
        username="user@example.com",
        secret="p@ss",
        origin="https://example.com",
        label="Example",
        home=home,
    )
    assert resolved["state"] == "approved"
    assert resolved["result"]["ok"] is True
    assert "p@ss" not in str(resolved["result"])
    assert vault_svc.bot_has_grant("bob", resolved["entry_id"], home=home)
    entry = vault_svc.get_entry(resolved["entry_id"], home=home, reveal=True)
    assert entry["secret"] == "p@ss"
    assert entry["username"] == "user@example.com"

    # Tool-facing result must stay redacted
    assert "p@ss" not in resolved["result"].get("message", "")


def test_agent_defined_api_key_fields(home):
    bots_svc.create_bot("erin", label="Erin", home=home)
    req = vault_svc.create_request(
        "erin",
        kind="credential",
        label="OpenAI",
        reason="Need API access",
        fields=[
            {"id": "api_key", "label": "Clé API", "secret": True, "required": True},
        ],
        home=home,
    )
    assert req["state"] == "pending"
    assert req["fields"][0]["id"] == "api_key"
    msgs = chat_svc.list_messages("erin", home=home)
    card = next(m for m in msgs if m["meta"].get("kind") == "vault_request")
    assert card["meta"]["fields"][0]["label"] == "Clé API"

    resolved = vault_svc.resolve_request(
        req["id"],
        action="approve",
        values={"api_key": "sk-never-to-llm"},
        home=home,
    )
    assert resolved["state"] == "approved"
    assert "sk-never-to-llm" not in str(resolved)
    assert resolved["result"]["secret_keys"] == ["api_key"]
    entry = vault_svc.get_entry(resolved["entry_id"], home=home, reveal=True)
    assert entry["secret"] == "sk-never-to-llm"
    assert entry["secrets"]["api_key"] == "sk-never-to-llm"


def test_request_access_grant(home):
    bots_svc.create_bot("cara", label="Cara", home=home)
    entry = vault_svc.create_entry(
        label="Shared", kind="secret", secret="top", home=home
    )
    req = vault_svc.create_request(
        "cara",
        kind="access",
        entry_id=entry["id"],
        reason="Need key",
        home=home,
    )
    assert req["state"] == "pending"
    out = vault_svc.resolve_request(req["id"], action="approve", home=home)
    assert out["state"] == "approved"
    assert vault_svc.bot_has_grant("cara", entry["id"], home=home)
    # Second request short-circuits
    again = vault_svc.create_request(
        "cara", kind="access", entry_id=entry["id"], home=home
    )
    assert again["state"] == "approved"
    assert again["result"].get("already_granted") is True


def test_dead_session_after_vault_auto_resumes(home, auth_client, monkeypatch):
    bots_svc.create_bot("frank", label="Frank", home=home)
    chat_svc.send_message(
        "frank", "Connecte-toi au site", home=home, trigger_agent=False
    )
    chat_svc.create_message(
        "frank",
        "tool: request_vault_access\nstatus: running",
        role="event",
        meta={"kind": "tool", "status": "running", "tool_name": "request_vault_access"},
        home=home,
    )
    bots_svc.patch_bot("frank", {"status": "waiting"}, home=home)
    req = vault_svc.create_request(
        "frank",
        kind="access",
        entry_id=vault_svc.create_entry(
            label="Site", kind="secret", secret="x", home=home
        )["id"],
        reason="login",
        home=home,
    )
    prompts: list[str] = []

    class FakeAgent:
        def start_run(self, name, message, *, home=None, images=None):
            prompts.append(message)
            return ""

        def stop_run(self, name, *, home=None):
            return None

    monkeypatch.setattr(
        "autonomous.services.agent.get_agent",
        lambda *a, **k: FakeAgent(),
    )
    # No live Pi session → resolve must unstick + auto-resume (no manual card).
    out = vault_svc.resolve_request(req["id"], action="approve", home=home)
    assert out["state"] == "approved"
    msgs = chat_svc.list_messages("frank", home=home)
    pending = [
        m
        for m in msgs
        if (m.get("meta") or {}).get("kind") == "agent_interrupted"
        and (m.get("meta") or {}).get("state") == "pending"
    ]
    assert pending == []
    tool = next(
        m
        for m in msgs
        if m["meta"].get("kind") == "tool"
        and m["meta"].get("tool_name") == "request_vault_access"
    )
    assert tool["meta"]["status"] == "error"
    assert prompts and "Original task" in prompts[0]


def test_vault_http_api(home, auth_client):
    bots_svc.create_bot("dave", label="Dave", home=home)
    r = auth_client.post(
        "/api/v1/vault/entries",
        json={"label": "Tok", "kind": "secret", "secret": "s3cret"},
    )
    assert r.status_code == 201
    entry = r.get_json()
    assert "secret" not in entry

    r = auth_client.get("/api/v1/vault/catalog")
    assert r.status_code == 200
    assert any(e["id"] == entry["id"] for e in r.get_json())

    r = auth_client.post(
        "/api/v1/vault/requests",
        json={
            "bot": "dave",
            "kind": "access",
            "entry_id": entry["id"],
            "reason": "please",
        },
    )
    assert r.status_code == 201
    req = r.get_json()
    assert req["state"] == "pending"

    r = auth_client.post(
        f"/api/v1/vault/requests/{req['id']}/resolve",
        json={"action": "approve"},
    )
    assert r.status_code == 200
    assert r.get_json()["state"] == "approved"

    r = auth_client.get("/api/v1/vault/entries?bot=dave")
    assert r.status_code == 200
    assert len(r.get_json()) == 1

    r = auth_client.post(
        "/api/v1/vault/requests",
        json={
            "bot": "dave",
            "kind": "login",
            "origin": "https://site.test",
            "reason": "login",
        },
    )
    req2 = r.get_json()
    r = auth_client.post(
        f"/api/v1/vault/requests/{req2['id']}/resolve",
        json={
            "action": "approve",
            "username": "u",
            "secret": "never-to-llm",
            "label": "Site",
            "origin": "https://site.test",
        },
    )
    body = r.get_json()
    assert body["state"] == "approved"
    assert "never-to-llm" not in str(body)


def test_chat_message_cancels_pending_vault_with_redirect(home):
    """While waiting on a vault form, a chat reply cancels it (not a hard deny)."""
    bots_svc.create_bot("lea", label="Lea", home=home)
    req = vault_svc.create_request(
        "lea",
        kind="credential",
        label="Leboncoin 2FA",
        reason="Code OTP",
        fields=[{"id": "otp", "label": "Code", "secret": True, "required": True}],
        home=home,
    )
    assert req["state"] == "pending"
    bots_svc.patch_bot("lea", {"status": "waiting"}, home=home)

    msg = chat_svc.send_message(
        "lea",
        "Ce n'est pas un code : valide l'action sur mon téléphone.",
        home=home,
    )
    assert not (msg.get("meta") or {}).get("queued")

    fresh = vault_svc.get_request(req["id"], home=home)
    assert fresh["state"] == "cancelled"
    assert fresh["result"].get("human_redirect") is True
    assert "téléphone" in fresh["result"].get("message", "")
    assert fresh["result"].get("denied") is False


def test_deny_with_queued_message_becomes_redirect(home):
    """« Refuser » after a queued correction must not look like a hard denial."""
    bots_svc.create_bot("marc", label="Marc", home=home)
    req = vault_svc.create_request(
        "marc",
        kind="secret",
        label="2FA",
        home=home,
    )
    bots_svc.patch_bot("marc", {"status": "busy"}, home=home)
    # Simulate a message that was queued before waiting (or during busy).
    queued = chat_svc.send_message(
        "marc",
        "Valide sur l'autre appareil, pas de code.",
        home=home,
    )
    assert (queued.get("meta") or {}).get("queued") is True
    bots_svc.patch_bot("marc", {"status": "waiting"}, home=home)

    resolved = vault_svc.resolve_request(req["id"], action="deny", home=home)
    assert resolved["state"] == "cancelled"
    assert resolved["result"].get("human_redirect") is True
    assert "autre appareil" in resolved["result"].get("message", "")
    assert not chat_svc.list_queued_user_messages("marc", home=home)


def test_plain_deny_still_denied(home):
    bots_svc.create_bot("nina", label="Nina", home=home)
    req = vault_svc.create_request("nina", kind="secret", label="X", home=home)
    resolved = vault_svc.resolve_request(req["id"], action="deny", home=home)
    assert resolved["state"] == "denied"
    assert resolved["result"].get("denied") is True


def test_prompt_exception_for_temporary_codes():
    from autonomous.services.pi_rpc import _VAULT_SYSTEM_HINT, _VM_SYSTEM_HINT

    hint = _VAULT_SYSTEM_HINT
    assert "NEVER reveal vault secrets" in hint
    assert "temporary authentication codes" in hint
    assert "report_user_secret" in hint
    assert "long-lived token" in hint
    assert "see VAULT" in _VM_SYSTEM_HINT
    assert "do not ask for them again" in _VM_SYSTEM_HINT
