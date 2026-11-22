"""Durable daily token usage history (Settings chart)."""

from __future__ import annotations

from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services import token_usage_history as usage_hist


def test_history_survives_clear_and_purges_on_delete(home):
    bots_svc.create_bot("Alpha", slug="alpha", home=home)
    bots_svc.create_bot("Beta", slug="beta", home=home)
    bots_svc.add_token_usage("alpha", 1000, 50, home=home)
    bots_svc.add_token_usage("beta", 200, 10, home=home)
    bots_svc.add_token_usage("alpha", 100, 5, home=home)

    hist = usage_hist.history(home=home)
    assert len(hist["days"]) >= usage_hist.WINDOW_DAYS
    assert hist["max_cumulative"] == 1155
    by_bot = {s["bot"]: s for s in hist["series"]}
    assert by_bot["alpha"]["cumulative"][-1] == 1155
    assert by_bot["beta"]["cumulative"][-1] == 210
    # Short history is left-padded with zeros across the 30-day window.
    assert by_bot["alpha"]["cumulative"][0] == 0
    assert by_bot["alpha"]["daily"][-1] == 1155

    chat_svc.clear_messages("alpha", home=home)
    row = bots_svc.get_bot("alpha", home=home)
    assert row["tokens_in"] == 0
    assert row["tokens_out"] == 0

    hist2 = usage_hist.history(home=home)
    by_bot2 = {s["bot"]: s for s in hist2["series"]}
    assert by_bot2["alpha"]["cumulative"][-1] == 1155

    bots_svc.delete_bot("alpha", home=home, destroy_desk=False)
    hist3 = usage_hist.history(home=home)
    names = {s["bot"] for s in hist3["series"]}
    assert "alpha" not in names
    assert "beta" in names
    # Explicit table check: no orphan rows for deleted bot
    from autonomous.db import get_db

    with get_db(home) as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM bot_token_usage_daily WHERE bot = ?",
            ("alpha",),
        ).fetchone()["c"]
    assert n == 0


def test_token_usage_api(home, auth_client):
    bots_svc.create_bot("Chart", slug="chart", home=home)
    bots_svc.add_token_usage("chart", 42, 8, home=home)
    r = auth_client.get("/api/v1/bots/token-usage")
    assert r.status_code == 200
    body = r.get_json()
    assert body["max_cumulative"] == 50
    assert any(s["bot"] == "chart" and s["cumulative"][-1] == 50 for s in body["series"])
