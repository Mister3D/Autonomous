"""Guard rails: tool count since last user/webhook, review + hard stop."""

from __future__ import annotations

from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services.agent import (
    _resolve_action_limit,
    _resolve_review_every,
    _wants_guard_stop,
)
from autonomous.services import settings as settings_svc


def test_count_tools_since_last_user_resets_on_user_message(home):
    bots_svc.create_bot("g1", home=home)
    assert chat_svc.count_tools_since_last_user("g1", home=home) == 0

    chat_svc.create_message("g1", "hello", role="user", home=home)
    chat_svc.create_message(
        "g1",
        "tool",
        role="event",
        meta={"kind": "tool", "status": "done", "tool_name": "vm_click"},
        home=home,
    )
    chat_svc.create_message(
        "g1",
        "tool2",
        role="event",
        meta={"kind": "tool", "status": "done", "tool_name": "vm_ground"},
        home=home,
    )
    assert chat_svc.count_tools_since_last_user("g1", home=home) == 2

    # New user message (or webhook/cron inject) resets the window.
    chat_svc.create_message(
        "g1",
        "Webhook déclenché.",
        role="user",
        meta={"kind": "webhook"},
        home=home,
    )
    assert chat_svc.count_tools_since_last_user("g1", home=home) == 0
    chat_svc.create_message(
        "g1",
        "tool3",
        role="event",
        meta={"kind": "tool", "status": "done", "tool_name": "bash"},
        home=home,
    )
    assert chat_svc.count_tools_since_last_user("g1", home=home) == 1


def test_resolve_defaults(home):
    bots_svc.create_bot("g2", home=home)
    row = bots_svc.get_bot("g2", home=home)
    assert _resolve_action_limit(row, home=home) == 1000
    # New homes get default 100; older DBs may still have 70 from previous DEFAULTS.
    n = _resolve_review_every(row, home=home)
    assert n in (70, 100)
    settings_svc.set_many({"guard.review_every": 100}, home=home)
    assert _resolve_review_every(row, home=home) == 100
    settings_svc.set_many({"guard.review_every": 0}, home=home)
    assert _resolve_review_every(row, home=home) == 0


def test_guard_stop_parse():
    assert _wants_guard_stop("GUARD:STOP — stuck on captcha")
    assert _wants_guard_stop("guard : stop")
    assert not _wants_guard_stop("GUARD:CONTINUE")
    assert not _wants_guard_stop("still working")
