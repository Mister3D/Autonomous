"""One compaction card across threshold → overflow failure storms."""

from autonomous.services.agent import compaction_card_reuse_id, compaction_notice


def test_reuse_latest_failed_compaction_card():
    messages = [
        {"id": "a", "meta": {"kind": "compaction", "status": "done"}},
        {"id": "b", "meta": {"kind": "compaction", "status": "error", "reason": "threshold"}},
        {"id": "c", "meta": {"kind": "llm_turn"}},
    ]
    assert compaction_card_reuse_id(messages) == "b"


def test_reuse_running_or_aborted_card():
    assert (
        compaction_card_reuse_id(
            [{"id": "r", "meta": {"kind": "compaction", "status": "running"}}]
        )
        == "r"
    )
    assert (
        compaction_card_reuse_id(
            [{"id": "x", "meta": {"kind": "compaction", "status": "aborted"}}]
        )
        == "x"
    )


def test_successful_compaction_starts_a_new_card_cycle():
    messages = [
        {"id": "old-fail", "meta": {"kind": "compaction", "status": "error"}},
        {"id": "ok", "meta": {"kind": "compaction", "status": "done"}},
    ]
    assert compaction_card_reuse_id(messages) is None


def test_chunked_passes_land_in_notice_meta():
    _text, meta = compaction_notice(
        {
            "type": "compaction_end",
            "reason": "threshold",
            "result": {
                "tokensBefore": 200000,
                "estimatedTokensAfter": 30000,
                "details": {"passes": 3, "chunked": True},
            },
        }
    )
    assert meta["status"] == "done"
    assert meta["passes"] == 3
    assert meta["chunked"] is True


def test_chunked_recovery_failure_sets_lower_thinking_hint():
    _text, meta = compaction_notice(
        {
            "type": "compaction_end",
            "reason": "overflow",
            "errorMessage": (
                "Context overflow recovery failed: Chunked compaction recovery failed "
                "(empty summary). Try lowering the thinking level (Réflexion) in bot "
                "details, then Relancer."
            ),
        }
    )
    assert meta["status"] == "error"
    assert meta["hint"] == "lower_thinking"
