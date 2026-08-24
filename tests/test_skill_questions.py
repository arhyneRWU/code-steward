"""The A/B question builder, and the floor on answer size.

Run 2 raises the floor because 19 of the 30 Django questions the old
floor produced had two-unit answers. The floor is a parameter, not a
rewritten constant, so run 1 stays reproducible.
"""

from __future__ import annotations

from benchmarks.skill.questions import build_questions
from code_steward.models import CodeUnit, HardRelationship


def _unit(name: str) -> CodeUnit:
    return CodeUnit(
        unit_id=f"m.py::{name}",
        path="m.py",
        name=name,
        qualname=name,
        kind="function",
        signature=f"{name}()",
        start_line=1,
        end_line=2,
    )


def _calls(source: str, target: str) -> HardRelationship:
    return HardRelationship(
        source_unit_id=f"m.py::{source}",
        relation="CALLS",
        target_ref=f"m.py::{target}",
        target_kind="unit",
        provenance="test",
    )


def _fixture() -> tuple[list[CodeUnit], list[HardRelationship]]:
    names = ["root", "a", "b", "c", "leaf"]
    units = [_unit(name) for name in names]
    edges = [_calls("root", "a"), _calls("root", "b"), _calls("root", "c")]
    edges.append(_calls("leaf", "a"))
    edges.append(_calls("leaf", "b"))
    return units, edges


def test_min_answer_floor_excludes_small_answers() -> None:
    units, edges = _fixture()
    kept = build_questions(units, edges, limit=10, min_answer=3)
    assert kept, "a three-unit answer should survive a floor of three"
    assert all(len(question["answer"]) >= 3 for question in kept)


def test_default_floor_is_the_run_one_floor() -> None:
    units, edges = _fixture()
    sizes = {len(q["answer"]) for q in build_questions(units, edges, limit=10)}
    assert 2 in sizes, "the default floor must stay at two for run 1"


def test_the_criterion_can_fail_under_the_null() -> None:
    """A criterion that always fires is not evidence.

    Run 1's bootstrap bound fired on 100% of its data because the
    sample held no negative differences. This checks the replacement
    against the null it is supposed to model.
    """
    from benchmarks.skill.power import power

    rate = power(n=40, tie_rate=0.5, p_up=0.5, trials=60, seed=3)
    assert rate <= 0.20, f"fires too often under the null: {rate}"
