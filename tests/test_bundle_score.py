"""The small-model DRY score must not be winnable by guessing.

This result carries more weight than any other in the project -- it
is the only evidence that a cheap model can do the work at all -- so
the ways it could be inflated are pinned individually.
"""

from __future__ import annotations

import json

from benchmarks.verdict.bundle_score import load_answers, score

POSITIVE = {"bundle_id": "p1", "corpus": "x", "kind": "duplicate-present", "expected": ["A", "D"]}
NEGATIVE = {"bundle_id": "n1", "corpus": "x", "kind": "no-duplicate", "expected": []}


def _answer(bundle_id, pair):
    return {bundle_id: {"id": bundle_id, "duplicate_pair": pair}}


def test_both_members_of_the_pair_are_required():
    assert score([POSITIVE], _answer("p1", ["A", "D"]))["counts"]["positive_correct"] == 1


def test_order_does_not_matter():
    assert score([POSITIVE], _answer("p1", ["D", "A"]))["counts"]["positive_correct"] == 1


def test_naming_one_right_and_one_wrong_earns_nothing():
    """Acting on it would merge the wrong two functions."""
    counts = score([POSITIVE], _answer("p1", ["A", "F"]))["counts"]
    assert counts.get("positive_correct", 0) == 0
    assert counts["positive_wrong_pair"] == 1


def test_declining_a_real_duplicate_is_a_miss_not_a_pass():
    counts = score([POSITIVE], _answer("p1", []))["counts"]
    assert counts.get("positive_correct", 0) == 0
    assert counts["positive_missed"] == 1


def test_inventing_a_pair_on_a_clean_bundle_is_counted():
    counts = score([NEGATIVE], _answer("n1", ["B", "C"]))["counts"]
    assert counts["negative_invented"] == 1
    assert counts.get("negative_correct", 0) == 0


def test_declining_a_clean_bundle_is_correct():
    assert score([NEGATIVE], _answer("n1", []))["counts"]["negative_correct"] == 1


def test_a_missing_answer_is_counted_not_skipped():
    assert score([POSITIVE, NEGATIVE], _answer("p1", ["A", "D"]))["counts"]["missing"] == 1


def test_answers_load_from_every_file(tmp_path):
    for index in range(3):
        (tmp_path / f"answer-{index:02d}.json").write_text(
            json.dumps({"answers": [{"id": f"b{index}", "duplicate_pair": []}]}), encoding="utf-8"
        )
    assert sorted(load_answers(tmp_path)) == ["b0", "b1", "b2"]
