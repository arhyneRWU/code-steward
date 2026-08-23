"""The realistic-draft score must not flatter the draft arm.

The result it produces is the one most likely to be quoted as the
product's headline, and the easiest ways to inflate it are all
arithmetic: dropping drafts that failed, counting a near-miss as a
hit, or reporting only the denominator that looks best.
"""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.verdict.draft_score import _surfaced, load_drafts
from code_steward.models import CodeUnit
from code_steward.similarity import SimilarUnit

RESULT = Path("benchmarks/verdict/realistic_draft.json")


def _match(unit_id: str, score: float) -> SimilarUnit:
    unit = CodeUnit(
        unit_id=unit_id,
        path="x.py",
        kind="function",
        name=unit_id,
        qualname=unit_id,
        start_line=1,
        end_line=9,
    )
    return SimilarUnit(unit, score, 5)


def test_only_the_expected_unit_counts_as_surfaced():
    matches = [_match("other", 0.9), _match("wanted", 0.4)]
    assert _surfaced(matches, "wanted")
    assert not _surfaced(matches, "absent")


def test_a_match_below_the_floor_does_not_count_when_a_floor_is_given():
    matches = [_match("wanted", 0.26)]
    assert _surfaced(matches, "wanted")
    assert not _surfaced(matches, "wanted", 0.27)


def test_a_strong_wrong_answer_never_rescues_a_case():
    """Ranking something confidently is not finding the right thing."""
    assert not _surfaced([_match("other", 0.99)], "wanted", 0.27)


def test_drafts_load_from_every_answer_file(tmp_path):
    for index in range(3):
        (tmp_path / f"answer-{index:02d}.json").write_text(
            json.dumps({"drafts": [{"id": f"t{index}", "code": "def f():\n    pass\n"}]}),
            encoding="utf-8",
        )
    assert sorted(load_drafts(tmp_path)) == ["t0", "t1", "t2"]


def test_the_published_result_reports_both_denominators():
    """A draft too small to compare is a failure, not a non-event."""
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    arms = {row["arm"]: row for row in payload["arms"]}
    for name in ("agent-draft", "agent-draft-floored"):
        arm = arms[name]
        assert "surfaced_rate_all_cases" in arm
        # The all-cases rate can never flatter the usable-draft rate.
        assert arm["surfaced_rate_all_cases"] <= arm["surfaced_rate"]


def test_the_floored_arm_can_never_beat_the_unfloored_one():
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    arms = {row["arm"]: row for row in payload["arms"]}
    assert arms["agent-draft-floored"]["surfaced"] <= arms["agent-draft"]["surfaced"]
    assert arms["agent-draft"]["surfaced"] <= arms["real-body"]["surfaced"]
