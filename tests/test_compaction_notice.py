"""Pi compaction events become a chat notice, without copying the summary."""

from autonomous.services.agent import compaction_notice


def test_compaction_start_is_a_running_notice():
    text, meta = compaction_notice({"type": "compaction_start", "reason": "threshold"})
    assert "résume" in text
    assert meta == {"kind": "compaction", "status": "running", "reason": "threshold"}


def test_compaction_end_keeps_token_counts_not_the_summary():
    text, meta = compaction_notice(
        {
            "type": "compaction_end",
            "reason": "overflow",
            "aborted": False,
            "result": {
                "summary": "SECRET checkpoint that must not land in the thread",
                "tokensBefore": 180000,
                "estimatedTokensAfter": 24000,
            },
        }
    )
    assert text.startswith("Pi a résumé")
    assert "SECRET" not in text
    assert meta["status"] == "done"
    assert meta["tokens_before"] == 180000
    assert meta["tokens_after"] == 24000
    assert "summary" not in meta


def test_compaction_end_error_and_unrelated_records():
    text, meta = compaction_notice(
        {
            "type": "compaction_end",
            "reason": "manual",
            "aborted": False,
            "errorMessage": "model overloaded",
            "result": None,
        }
    )
    assert meta["status"] == "error"
    assert meta["error"] == "model overloaded"
    assert "échoué" in text
    assert compaction_notice({"type": "message_end"}) is None
