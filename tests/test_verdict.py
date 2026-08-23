"""Tests for the reuse-evidence measurement.

The measurement's whole value is that it can come out against the
feature, so the parts that could quietly flatter it are the parts
under test: what counts as a hit, what counts as a false positive,
what is excluded, and what happens when an arm returns nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.verdict.cases import build_cases, load_pairs
from benchmarks.verdict.run import ArmResult, Excluded, _record

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "benchmarks" / "similarity" / "reuse_pair_labels.json"


def _case(kind, expected="", target="t"):
    from benchmarks.verdict.cases import VerdictCase

    return VerdictCase("c", "fixture", target, expected, kind)


# --- case derivation ----------------------------------------------


def test_a_same_behaviour_pair_yields_a_case_in_each_direction():
    """Either function could have been the one about to be written."""
    pairs = [
        {"corpus": "fixture", "left": "a", "right": "b", "label": "same-behaviour"},
    ]
    cases = build_cases(pairs)
    assert {(c.target, c.expected) for c in cases} == {("a", "b"), ("b", "a")}


def test_units_only_in_unrelated_pairs_become_negative_cases():
    pairs = [
        {"corpus": "fixture", "left": "a", "right": "b", "label": "same-behaviour"},
        {"corpus": "fixture", "left": "c", "right": "d", "label": "unrelated"},
    ]
    cases = {c.target: c for c in build_cases(pairs)}
    assert cases["c"].kind == "no-reuse-available"
    assert cases["c"].expected == ""


def test_a_unit_with_a_known_duplicate_is_never_a_negative_case():
    """Otherwise the negative set would contain reuse opportunities."""
    pairs = [
        {"corpus": "fixture", "left": "a", "right": "b", "label": "same-behaviour"},
        {"corpus": "fixture", "left": "a", "right": "z", "label": "unrelated"},
    ]
    kinds = {c.target: c.kind for c in build_cases(pairs)}
    assert kinds["a"] == "reuse-available"
    assert kinds["z"] == "no-reuse-available"


def test_cases_build_from_the_committed_labels():
    cases = build_cases(load_pairs(LABELS))
    assert any(c.kind == "reuse-available" for c in cases)
    assert any(c.kind == "no-reuse-available" for c in cases)


# --- scoring ------------------------------------------------------


def test_a_positive_counts_only_when_the_labelled_duplicate_is_surfaced():
    arm = ArmResult("a")
    _record(arm, _case("reuse-available", expected="d"), {"d", "x"}, set(), 100)
    _record(arm, _case("reuse-available", expected="d"), {"x", "y"}, set(), 100)
    assert arm.positives == 2
    assert arm.positives_surfaced == 1
    assert arm.surfaced_rate == pytest.approx(0.5)


def test_unlabelled_evidence_on_a_negative_is_not_a_false_positive():
    """A hole in the pool is not a verdict, and is counted apart."""
    arm = ArmResult("a")
    _record(arm, _case("no-reuse-available"), {"nobody-judged-this"}, {"known-unrelated"}, 100)
    assert arm.negatives_false_positive == 0
    assert arm.negatives_unlabelled == 1


def test_surfacing_a_known_unrelated_unit_is_a_false_positive():
    arm = ArmResult("a")
    _record(arm, _case("no-reuse-available"), {"known-unrelated"}, {"known-unrelated"}, 100)
    assert arm.negatives_false_positive == 1
    assert arm.negatives_unlabelled == 0


def test_surfacing_nothing_on_a_negative_is_neither():
    """Silence is the correct answer, not an error and not a hit."""
    arm = ArmResult("a")
    _record(arm, _case("no-reuse-available"), set(), {"known-unrelated"}, 0)
    assert arm.negatives_false_positive == 0
    assert arm.negatives_unlabelled == 0
    assert arm.negatives == 1


def test_an_arm_that_scored_nothing_reports_zero_rather_than_dividing():
    arm = ArmResult("a")
    assert arm.surfaced_rate == 0.0
    assert arm.false_positive_rate == 0.0
    assert arm.mean_bytes == 0.0


def test_byte_cost_is_accumulated_per_case():
    arm = ArmResult("a")
    _record(arm, _case("reuse-available", expected="d"), {"d"}, set(), 100)
    _record(arm, _case("reuse-available", expected="d"), {"d"}, set(), 300)
    assert arm.mean_bytes == pytest.approx(200.0)


# --- exclusions ---------------------------------------------------


def test_exclusions_are_counted_by_reason():
    excluded = Excluded()
    excluded.record("undocumented")
    excluded.record("undocumented")
    excluded.record("target-not-in-corpus")
    assert excluded.total == 3
    assert excluded.to_dict()["by_reason"]["undocumented"] == 2


def test_the_committed_result_reports_what_it_could_not_score():
    """Half the cases are excluded; a reader has to be told."""
    payload = json.loads(
        (ROOT / "benchmarks" / "verdict" / "evidence.json").read_text(encoding="utf-8")
    )
    assert payload["excluded"]["total"] > 0
    scored = payload["arms"][0]["cases_scored"]
    assert scored + payload["excluded"]["total"] == payload["cases_built"]


def test_every_arm_scored_the_same_cases():
    """Arms compared on different populations are not comparable."""
    payload = json.loads(
        (ROOT / "benchmarks" / "verdict" / "evidence.json").read_text(encoding="utf-8")
    )
    counts = {(a["cases_scored"], a["positives"], a["negatives"]) for a in payload["arms"]}
    assert len(counts) == 1
