"""Desk authorization poll flags for agent wait (vm_request_desk)."""

from __future__ import annotations

from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services import desk as desk_svc


def test_desk_status_includes_pending_request(home):
    bots_svc.create_bot("waitdesk", home=home)
    st = desk_svc.status("waitdesk", home=home)
    assert st["state"] == "absent"
    assert st.get("pending_request_id") is None

    posted = desk_svc.request_authorization(
        "waitdesk", mode="terminal", reason="besoin VM", home=home
    )
    assert posted["ok"] is True
    assert posted["state"] == "pending"

    st2 = desk_svc.status("waitdesk", home=home)
    assert st2["pending_state"] == "pending"
    assert st2["pending_request_id"] == posted["message_id"]

    desk_svc.resolve_desk_requests("waitdesk", state="denied", home=home)
    st3 = desk_svc.status("waitdesk", home=home)
    assert st3["pending_request_id"] is None
    assert st3["pending_state"] == "denied"

    bot = bots_svc.get_bot("waitdesk", home=home)
    # request_authorization set waiting; deny path in API clears it — service alone keeps card.
    assert any(
        (m.get("meta") or {}).get("state") == "denied"
        for m in chat_svc.list_messages("waitdesk", home=home)
        if (m.get("meta") or {}).get("kind") == "desk_request"
    )
    assert bot["status"] in ("waiting", "idle")


def test_desk_request_api_deny_clears_waiting(home, auth_client):
    bots_svc.create_bot("denydesk", home=home)
    r = auth_client.post(
        "/api/v1/bots/denydesk/desk/request",
        json={"mode": "terminal", "reason": "test"},
    )
    assert r.status_code == 200
    assert bots_svc.get_bot("denydesk", home=home)["status"] == "waiting"

    r2 = auth_client.post(
        "/api/v1/bots/denydesk/desk/request/resolve",
        json={"action": "deny"},
    )
    assert r2.status_code == 200
    assert bots_svc.get_bot("denydesk", home=home)["status"] == "idle"
