"""Desk ready must not double-prompt while a Pi run is still active."""

from __future__ import annotations

from unittest.mock import patch

from autonomous.services import bots as bots_svc
from autonomous.services import desk as desk_svc


def test_continue_after_desk_skips_resume_when_run_in_progress(home):
    bots_svc.create_bot("deskrun", home=home)
    bots_svc.patch_bot("deskrun", {"status": "waiting"}, home=home)

    with (
        patch("autonomous.services.agent.run_in_progress", return_value=True),
        patch("autonomous.services.chat.resume_run") as resume,
    ):
        desk_svc._continue_agent_after_desk("deskrun", home=home)
        resume.assert_not_called()
        row = bots_svc.get_bot("deskrun", home=home)
        assert row["status"] == "busy"


def test_continue_restores_busy_even_if_status_was_idle(home):
    """Regression: desk boot used to force idle before continue → orb vanished."""
    bots_svc.create_bot("deskidlerun", home=home)
    bots_svc.patch_bot("deskidlerun", {"status": "idle"}, home=home)

    with (
        patch("autonomous.services.agent.run_in_progress", return_value=True),
        patch("autonomous.services.chat.resume_run") as resume,
    ):
        desk_svc._continue_agent_after_desk("deskidlerun", home=home)
        resume.assert_not_called()
        assert bots_svc.get_bot("deskidlerun", home=home)["status"] == "busy"


def test_continue_after_desk_resumes_when_idle_no_run(home):
    bots_svc.create_bot("deskidle", home=home)
    bots_svc.patch_bot("deskidle", {"status": "waiting"}, home=home)

    with (
        patch("autonomous.services.agent.run_in_progress", return_value=False),
        patch("autonomous.services.chat.resume_run", return_value={"ok": True}) as resume,
    ):
        desk_svc._continue_agent_after_desk("deskidle", home=home)
        resume.assert_called_once()
