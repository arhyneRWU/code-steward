"""Check the candidate generators and the blinding they feed."""

from __future__ import annotations

import ast

from benchmarks.similarity.generators import metadata_pairs, shingle_pairs
from benchmarks.similarity.pool import PooledPair, blind_order, build_sheet, pair_id, probe_pairs
from benchmarks.similarity.units import CorpusUnit, normalise, tokenise
from code_steward.models import CodeUnit
from code_steward.retrieval import metadata_similarity


def _unit(unit_id: str, source: str, **meta) -> CorpusUnit:
    node = ast.parse(source).body[0]
    normalised = normalise(node)
    return CorpusUnit(
        unit_id=unit_id,
        corpus="fixture",
        path=f"{unit_id}.py",
        start_line=1,
        end_line=6,
        unit=CodeUnit(
            unit_id=unit_id,
            path=f"{unit_id}.py",
            kind="function",
            name=meta.get("name", unit_id),
            qualname=meta.get("qualname", unit_id),
            start_line=1,
            end_line=6,
            signature=meta.get("signature", ""),
            purpose=meta.get("purpose", ""),
            concepts=meta.get("concepts", []),
        ),
        normalised=normalised,
        tokens=tokenise(normalised),
    )


BODY = (
    "def {name}(values):\n"
    "    total = 0\n"
    "    for value in values:\n"
    "        total += value * 2\n"
    "    return total\n"
)


def test_shingle_pairs_rank_the_identical_body_first():
    units = [
        _unit("a", BODY.format(name="a")),
        _unit("b", BODY.format(name="a")),
        _unit("c", "def c(x):\n    print(x)\n    print(x)\n    print(x)\n    return None\n"),
    ]
    ranked = shingle_pairs(units, 5)
    assert ranked
    assert {ranked[0].left, ranked[0].right} == {"a", "b"}


def test_shingle_pairs_are_order_independent():
    units = [_unit("a", BODY.format(name="a")), _unit("b", BODY.format(name="a"))]
    forward = shingle_pairs(units, 5)
    backward = shingle_pairs(list(reversed(units)), 5)
    assert [pair.key() for pair in forward] == [pair.key() for pair in backward]


def test_metadata_arm_reproduces_the_production_function():
    """The benchmark arm must be the shipped function, not a variant.

    ``metadata_pairs`` batches the arithmetic for speed. If it ever
    drifts from ``retrieval.metadata_similarity``, the benchmark would
    be scoring something Code Steward does not ship.
    """
    left = _unit(
        "left",
        BODY.format(name="left"),
        name="sum_values",
        qualname="totals.sum_values",
        purpose="Add up the values.",
        concepts=["sum", "values"],
        signature="(values: list[int]) -> int",
    )
    right = _unit(
        "right",
        BODY.format(name="right"),
        name="sum_values",
        qualname="totals.sum_values",
        purpose="Add up the values.",
        concepts=["sum", "values"],
        signature="(values: list[int]) -> int",
    )
    ranked = metadata_pairs([left, right], 5)
    assert ranked
    expected = metadata_similarity(left.unit, right.unit)
    assert abs(ranked[0].score - expected) < 1e-9


def test_blind_order_carries_no_arm_signal():
    pairs = [
        PooledPair("fixture", "a", "b", "pooled", ("shingle",)),
        PooledPair("fixture", "c", "d", "pooled", ("jscpd",)),
        PooledPair("fixture", "e", "f", "probe", ()),
    ]
    assert [pair_id(pair) for pair in blind_order(pairs)] == [
        pair_id(pair) for pair in blind_order(list(reversed(pairs)))
    ]


def test_the_sheet_hides_corpus_stratum_and_provenance():
    units = {"a": _unit("a", BODY.format(name="a")), "b": _unit("b", BODY.format(name="b"))}
    sheet = build_sheet([PooledPair("fixture", "a", "b", "pooled", ("shingle", "jscpd"))], units)
    rendered = repr(sheet)
    assert "shingle" not in rendered
    assert "jscpd" not in rendered
    assert "pooled" not in rendered
    assert "fixture" not in rendered
    assert sheet["pairs"][0]["left"]["source"]


def test_probe_pairs_are_reproducible_and_distinct():
    units = [_unit(str(index), BODY.format(name=f"f{index}")) for index in range(10)]
    first = probe_pairs(units, "fixture", 4)
    second = probe_pairs(units, "fixture", 4)
    assert [pair_id(pair) for pair in first] == [pair_id(pair) for pair in second]
    assert all(pair.left != pair.right for pair in first)
    assert all(pair.stratum == "probe" for pair in first)
