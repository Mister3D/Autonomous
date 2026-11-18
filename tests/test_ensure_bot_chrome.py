"""Chrome starts on demand for browser tools — not at desk boot."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from autonomous.services import browser as browser_svc
from autonomous.services import desk as desk_svc


def test_ensure_bot_chrome_noop_when_cdp_ready():
    with patch.object(desk_svc, "chrome_cdp_ready", return_value=True) as ready:
        with patch.object(desk_svc, "restart_bot_chrome") as restart:
            assert desk_svc.ensure_bot_chrome("bot") is True
    ready.assert_called_once()
    restart.assert_not_called()


def test_ensure_bot_chrome_restarts_when_cdp_down():
    with patch.object(desk_svc, "chrome_cdp_ready", return_value=False):
        with patch.object(desk_svc, "restart_bot_chrome", return_value=True) as restart:
            assert desk_svc.ensure_bot_chrome("bot") is True
    restart.assert_called_once_with("bot", home=None)


def test_browser_run_ensures_chrome_before_cdp(monkeypatch):
    calls: list[str] = []

    def ensure_desk(bot, *, home=None):
        calls.append("desk")

    def ensure_chrome(bot, home=None):
        calls.append("chrome")
        return True

    monkeypatch.setattr(browser_svc, "_ensure_desk", ensure_desk)
    monkeypatch.setattr(browser_svc, "_copy_workers", lambda *a, **k: None)
    monkeypatch.setattr(
        "autonomous.services.desk.ensure_bot_chrome",
        ensure_chrome,
    )
    monkeypatch.setattr(
        "autonomous.services.desk.container_name",
        lambda bot, home=None: "autonomous-bot",
    )

    completed = MagicMock(returncode=0, stdout=b'{"ok": true}\n', stderr=b"")
    with patch("subprocess.run", return_value=completed):
        out = browser_svc._run("bot", ["tabs"])
    assert out.get("ok") is True
    assert calls == ["desk", "chrome"]


def test_browser_run_fails_when_chrome_will_not_start(monkeypatch):
    monkeypatch.setattr(browser_svc, "_ensure_desk", lambda *a, **k: None)
    monkeypatch.setattr(
        "autonomous.services.desk.ensure_bot_chrome",
        lambda *a, **k: False,
    )
    from autonomous.services.errors import AutonomousError

    try:
        browser_svc._run("bot", ["tabs"])
        assert False, "expected AutonomousError"
    except AutonomousError as exc:
        assert exc.code == "browser_chrome_start_failed"


def test_soft_cdp_read_does_not_start_chrome(monkeypatch):
    """VNC gesture page-read must not spawn Chrome over a native GUI."""
    calls: list[str] = []

    monkeypatch.setattr(browser_svc, "_ensure_desk", lambda *a, **k: None)
    monkeypatch.setattr(browser_svc, "_copy_workers", lambda *a, **k: None)
    monkeypatch.setattr(
        "autonomous.services.desk.ensure_bot_chrome",
        lambda *a, **k: calls.append("chrome") or True,
    )
    monkeypatch.setattr(
        "autonomous.services.desk.chrome_cdp_ready",
        lambda *a, **k: False,
    )
    assert browser_svc.page_marker("bot") == {}
    assert browser_svc.read_after_gesture("bot") == ""
    assert "chrome" not in calls

    from autonomous.services.errors import AutonomousError

    try:
        browser_svc._run("bot", ["tabs"], ensure_chrome=False)
        assert False, "expected AutonomousError"
    except AutonomousError as exc:
        assert exc.code == "browser_cdp_down"
    assert "chrome" not in calls
