"""Pi spawn replaces the coding-assistant preamble."""

from __future__ import annotations

from autonomous.services.pi_rpc import _BASE_SYSTEM_PROMPT


def test_base_system_prompt_is_not_coding_assistant():
    text = _BASE_SYSTEM_PROMPT.lower()
    assert "coding assistant" not in text
    assert "coding agent harness" not in text
    assert "autonomous" in text
    assert "companion" in text
