"""browser_navigate is the first open, onto a URL the user wrote."""

from __future__ import annotations

import pytest

from autonomous.services import bots as bots_svc
from autonomous.services import browser as browser_svc
from autonomous.services import chat as chat_svc
from autonomous.services.errors import ValidationError
from autonomous.services import url_policy


def _page(url: str) -> dict:
    return {"url": url, "value": url}


def test_first_open_accepts_the_user_url(home, monkeypatch):
    bots_svc.create_bot("urlbot", home=home)
    chat_svc.create_message(
        "urlbot",
        "Ouvre https://books.example/start",
        role="user",
        home=home,
    )
    monkeypatch.setattr(browser_svc, "evaluate", lambda *a, **k: _page("about:blank"))
    assert url_policy.assert_seen_url(
        "urlbot", "https://books.example/start", home=home
    )
    assert url_policy.assert_seen_url("urlbot", "https://books.example/", home=home)


def test_already_open_refuses_every_url_change(home, monkeypatch):
    bots_svc.create_bot("urlbot2", home=home)
    chat_svc.create_message(
        "urlbot2", "Va sur https://books.example/", role="user", home=home
    )
    chat_svc.create_message(
        "urlbot2",
        "Je tente https://books.example/mylibrary",
        role="assistant",
        home=home,
    )
    monkeypatch.setattr(
        browser_svc, "evaluate", lambda *a, **k: _page("https://books.example/")
    )
    with pytest.raises(ValidationError) as raised:
        url_policy.assert_seen_url(
            "urlbot2", "https://books.example/mylibrary", home=home
        )
    assert raised.value.code == "url_change"
    with pytest.raises(ValidationError) as again:
        url_policy.assert_seen_url("urlbot2", "https://books.example/", home=home)
    assert again.value.code == "url_change"


def test_first_open_accepts_a_vault_origin(home, monkeypatch):
    bots_svc.create_bot("urlbot4", home=home)
    monkeypatch.setattr(browser_svc, "evaluate", lambda *a, **k: _page("about:blank"))
    monkeypatch.setattr(
        "autonomous.services.vault.list_entries",
        lambda home=None: [{"origin": "https://shop.example/login"}],
    )
    assert url_policy.assert_seen_url(
        "urlbot4", "https://shop.example/login", home=home
    )
    assert url_policy.assert_seen_url("urlbot4", "https://shop.example/", home=home)
    with pytest.raises(ValidationError) as raised:
        url_policy.assert_seen_url(
            "urlbot4", "https://shop.example/orders", home=home
        )
    assert raised.value.code == "invented_url"


def test_first_open_still_refuses_an_invented_path(home, monkeypatch):
    bots_svc.create_bot("urlbot3", home=home)
    chat_svc.create_message(
        "urlbot3", "https://books.example/", role="user", home=home
    )
    monkeypatch.setattr(browser_svc, "evaluate", lambda *a, **k: _page("chrome://newtab/"))
    called = {}

    def _run(bot, args, home=None):
        called["args"] = args
        return {"ok": True, "navigated": args[-1]}

    monkeypatch.setattr(browser_svc, "_run", _run)
    with pytest.raises(ValidationError) as raised:
        browser_svc.navigate("urlbot3", "https://books.example/user", home=home)
    assert raised.value.code == "invented_url"
    assert "args" not in called
    out = browser_svc.navigate("urlbot3", "https://books.example/", home=home)
    assert out["navigated"] == "https://books.example/"
