"""The floor must be held out, pre-registered, and honest about zero.

Two things could quietly invalidate the chosen floor: a held-out
sample that overlaps the labelled one, and a criterion that drifts
into maximising something. Both are asserted here rather than
described in the doc.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.similarity.floor import (
    TARGET_FALSE_POSITIVE_RATE,
    choose_floor,
    false_positive_rate,
)
from code_steward.models import CodeUnit
from code_steward.similarity import REUSE_FLOOR, Ranking, rank_with_floor, shingles, tokenise

RESULT = Path("benchmarks/similarity/floor.json")


def test_the_shipped_floor_is_the_one_the_benchmark_chose():
    """Prose and code cannot drift apart on this number."""
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    assert payload["chosen_floor"] == REUSE_FLOOR


def test_the_chosen_floor_meets_the_pre_registered_budget():
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    at_floor = [
        row for row in payload["curve"] if row["floor"] == pytest.approx(payload["chosen_floor"])
    ]
    assert at_floor, "the chosen floor must appear on the published curve"
    assert at_floor[0]["false_positive_rate"] <= TARGET_FALSE_POSITIVE_RATE


def test_the_floor_is_the_smallest_value_meeting_the_budget():
    """Not the best value. The smallest one that clears the bar."""
    # 98 queries find nothing, two find something. At a 1% budget
    # exactly one survivor is allowed, so the floor must land just
    # above the weaker of the two and not a step higher.
    scores = [0.0] * 98 + [0.20, 0.50]
    chosen = choose_floor(scores)
    assert chosen == 0.21
    assert false_positive_rate(scores, chosen) <= TARGET_FALSE_POSITIVE_RATE
    assert false_positive_rate(scores, round(chosen - 0.01, 2)) > TARGET_FALSE_POSITIVE_RATE


def test_a_rate_with_no_denominator_raises_rather_than_reporting_zero():
    with pytest.raises(ValueError, match="No null scores"):
        false_positive_rate([], 0.3)


def test_an_unreachable_target_raises_rather_than_returning_a_guess():
    with pytest.raises(ValueError, match="Widen CANDIDATE_FLOORS"):
        choose_floor([1.0] * 100)


def _unit(unit_id: str, body: str) -> CodeUnit:
    return CodeUnit(
        unit_id=unit_id,
        path=f"{unit_id}.py",
        kind="function",
        name=unit_id,
        qualname=unit_id,
        start_line=1,
        end_line=9,
    )


def _prepared(bodies: dict[str, str]) -> dict[str, frozenset[int]]:
    return {key: shingles(tokenise(value)) for key, value in bodies.items()}


BODY = "total = 0\nfor item in items:\n    total += item.value\nreturn total\n"


def test_a_weak_match_is_suppressed_and_counted():
    prepared = _prepared({"a": BODY})
    units = [_unit("a", BODY)]
    ranking = rank_with_floor(prepared["a"], units, prepared, floor=1.1)
    assert ranking.matches == []
    assert ranking.below_floor == 1
    assert ranking.checked == 1


def test_below_floor_is_omitted_when_nothing_was_discarded():
    """A present key must always mean something was actually cut."""
    empty = Ranking(matches=[], below_floor=0, floor=REUSE_FLOOR)
    assert "below_floor" not in empty.to_dict()
    cut = Ranking(matches=[], below_floor=4, floor=REUSE_FLOOR)
    assert cut.to_dict()["below_floor"] == 4


def test_the_floor_travels_with_the_result():
    """A reader cannot interpret an empty result without it."""
    assert Ranking(matches=[], below_floor=0, floor=0.27).to_dict()["floor"] == 0.27
