"""Cumulative Pi token counters on bots."""

from __future__ import annotations

from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc


def test_add_and_reset_token_usage(home):
    bots_svc.create_bot("Tok", slug="tok", home=home)
    row = bots_svc.get_bot("tok", home=home)
    assert row.get("tokens_in", 0) == 0
    assert row.get("tokens_out", 0) == 0
    bots_svc.add_token_usage("tok", 9800, 15, home=home)
    bots_svc.add_token_usage("tok", 100, 40, home=home)
    row = bots_svc.get_bot("tok", home=home)
    assert row["tokens_in"] == 9900
    assert row["tokens_out"] == 55
    chat_svc.clear_messages("tok", home=home)
    row = bots_svc.get_bot("tok", home=home)
    assert row["tokens_in"] == 0
    assert row["tokens_out"] == 0


def test_bot_schema_exposes_tokens(home, auth_client):
    bots_svc.create_bot("Tokapi", slug="tokapi", home=home)
    bots_svc.add_token_usage("tokapi", 12, 3, home=home)
    r = auth_client.get("/api/v1/bots/tokapi")
    assert r.status_code == 200
    body = r.get_json()
    assert body["tokens_in"] == 12
    assert body["tokens_out"] == 3
