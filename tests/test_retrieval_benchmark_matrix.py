"""Tests for the additive retrieval validity matrix (benchmark v2).

These cover the deterministic measurement infrastructure only. They
assert nothing about retrieval quality, because the whole point of the
matrix is that quality thresholds should not be frozen before
strategies are compared.
"""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path

import pytest

from benchmarks.retrieval.corpus import (
    ALL_VARIANTS,
    FIXTURE_ROOT,
    CorpusVariant,
    build_corpus,
    generated_unit_ids,
    strip_docstrings,
)
from benchmarks.retrieval.matrix import (
    QUERY_SETS,
    assert_label_parity,
    evaluate_cell,
    index_tree,
    load_case_set,
    run_matrix,
)
from benchmarks.retrieval.run import load_cases, run_benchmark
from code_steward.search import search_units

# Frozen benchmark v1, as reported by `make bench` today. v2 is
# additive: if this pin ever moves, v1 stopped being a regression guard.
# Frozen Benchmark v1, rebaselined when body term coverage became a
# scored field. The previous values are kept here rather than deleted,
# because a baseline that only ever shows its current numbers cannot
# tell a reader whether a change helped:
#
#     mrr             0.6513888888888889 -> 0.7986111111111112
#     known_trap_rate 0.09375            -> 0.046875
#
# Hit@K, macro recall, redundancy, and duplicates were unmoved. This
# fixture is a regression guard against itself, not a quality
# measure; the real-repository numbers for the same change are in
# docs/retrieval.md and they are a mixed result, not this clean one.
FROZEN_V1 = {
    "case_count": 12,
    "hit_rate_at_k": 11 / 12,
    "macro_recall_at_k": 11 / 12,
    "mrr": 0.7986111111111112,
    "known_trap_rate": 0.046875,
    "known_redundancy_rate": 0.0625,
    "duplicate_candidate_rate": 0.0,
}


# --- docstring stripping ----------------------------------------------


def test_strip_docstrings_removes_every_docstring() -> None:
    source = '''
class Widget:
    """Class doc."""

    def method(self) -> int:
        """Method doc."""
        return 1


def free(value: str) -> str:
    """Free function doc."""
    return value
'''
    stripped = strip_docstrings(source)
    tree = ast.parse(stripped)

    assert "doc." not in stripped
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assert ast.get_docstring(node) is None


def test_strip_docstrings_keeps_docstring_only_bodies_parseable() -> None:
    stripped = strip_docstrings('def stub() -> None:\n    """Only a docstring."""\n')

    assert ast.parse(stripped)
    assert stripped.strip().endswith("pass")


def test_strip_docstrings_preserves_unit_tags_above_declarations() -> None:
    for path in sorted(FIXTURE_ROOT.glob("*.py")):
        original = path.read_text(encoding="utf-8")
        stripped = strip_docstrings(original)
        for line in original.splitlines():
            if "code-steward:" in line:
                assert line in stripped.splitlines()


# --- corpus variants --------------------------------------------------


@pytest.fixture(scope="module")
def corpora() -> dict[str, tuple[int, int]]:
    """Map variant key to (unit count, documented unit count)."""
    from benchmarks.retrieval.matrix import _is_documented

    built: dict[str, tuple[int, int]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for variant in ALL_VARIANTS:
            root = build_corpus(variant, Path(tmp))
            units, _ = index_tree(root)
            built[variant.key] = (
                len(units),
                sum(1 for unit in units if _is_documented(unit)),
            )
    return built


def test_documented_core_variant_matches_the_frozen_fixture(corpora) -> None:
    units, documented = corpora["documented/core"]

    assert units == 20
    # 18 of 20: `taxonomy.lookup-label` is deliberately undocumented and
    # the `orders.validation` region derives its purpose from the unit
    # ID, not a docstring. That is still a 90% documentation rate
    # against a real ~17%.
    assert documented == 18


def test_undocumented_variant_has_no_docstring_purposes(corpora) -> None:
    units, documented = corpora["undocumented/core"]

    assert units == 20
    assert documented == 0


def test_undocumented_purpose_falls_back_to_the_identifier() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = build_corpus(CorpusVariant(documented=False, scaled=False), Path(tmp))
        units, _ = index_tree(root)

    by_id = {unit.unit_id: unit for unit in units}
    assert by_id["taxonomy.normalize"].purpose == "normalize taxon name"


def test_stripping_changes_documentation_only(corpora) -> None:
    documented_units, _ = corpora["documented/core"]
    undocumented_units, _ = corpora["undocumented/core"]

    assert documented_units == undocumented_units


def test_scaled_corpus_reaches_a_realistic_candidate_window(corpora) -> None:
    units, _ = corpora["documented/scaled"]

    assert units >= 100
    # limit 5-6 over the scaled corpus must be a real-repository-sized
    # window.
    assert 6 / units < 0.06


def test_generated_units_never_collide_with_gold_labels() -> None:
    labelled: set[str] = set()
    for name in QUERY_SETS:
        for case in load_case_set(name):
            labelled.update(case["relevant"])
            labelled.update(case.get("traps", []))
            for group in case.get("redundancy_groups", []):
                labelled.update(group)

    assert not (generated_unit_ids() & labelled)


# --- verbose query set ------------------------------------------------


def test_verbose_set_reuses_the_gold_labels_verbatim() -> None:
    assert_label_parity()


def test_verbose_queries_are_substantially_longer() -> None:
    short = sum(len(case["query"].split()) for case in load_case_set("short"))
    verbose = sum(len(case["query"].split()) for case in load_case_set("verbose"))

    assert verbose >= 3 * short


def test_verbose_queries_avoid_identifier_shaped_wording() -> None:
    """Paraphrases must not smuggle the identifier back in.

    An identifier-shaped query is exactly the one that already works.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = build_corpus(CorpusVariant(documented=True, scaled=False), Path(tmp))
        units, _ = index_tree(root)
    by_id = {unit.unit_id: unit for unit in units}

    for case in load_case_set("verbose"):
        query = case["query"].lower()
        for unit_id in case["relevant"]:
            unit = by_id[unit_id]
            assert unit.name.lower() not in query
            assert unit.name.replace("_", " ").lower() not in query
            assert unit_id.lower() not in query


# --- matrix report ----------------------------------------------------


@pytest.fixture(scope="module")
def matrix_report() -> dict:
    return run_matrix("retrieve")


def test_matrix_reports_every_axis_combination(matrix_report) -> None:
    keys = {
        (cell["documentation"], cell["query_style"], cell["scale"])
        for cell in matrix_report["cells"]
    }

    assert len(matrix_report["cells"]) == 8
    assert len(keys) == 8


def test_matrix_metrics_are_in_range(matrix_report) -> None:
    rates = (
        "hit_rate_at_1",
        "hit_rate_at_3",
        "hit_rate_at_5",
        "hit_rate_at_k",
        "macro_recall_at_k",
        "mrr",
        "known_trap_rate",
        "known_redundancy_rate",
        "duplicate_candidate_rate",
        "candidate_fill_rate",
        "candidate_window",
    )
    for cell in matrix_report["cells"]:
        summary = cell["summary"]
        assert summary["case_count"] == len(load_cases())
        for key in rates:
            assert 0.0 <= summary[key] <= 1.0, (cell["scale"], key)
        assert summary["mean_packet_bytes"] > 0
        assert summary["hit_rate_at_1"] <= summary["hit_rate_at_k"]


def test_scaled_cells_report_a_smaller_candidate_window(matrix_report) -> None:
    by_scale = {
        cell["scale"]: cell["summary"]["candidate_window"] for cell in matrix_report["cells"]
    }

    assert by_scale["scaled"] < 0.06 < by_scale["core"]


def test_matrix_returns_no_duplicate_candidates(matrix_report) -> None:
    for cell in matrix_report["cells"]:
        for case in cell["cases"]:
            assert len(case["candidates"]) == len(set(case["candidates"]))


# --- frozen v1 regression guard ---------------------------------------


def test_frozen_v1_baseline_is_unchanged() -> None:
    summary = run_benchmark()["summary"]

    for key, expected in FROZEN_V1.items():
        assert summary[key] == pytest.approx(expected), key


def test_documented_core_cell_reproduces_frozen_v1_under_the_v1_pipeline() -> None:
    """documented/core must be the v1 corpus, unchanged."""
    with tempfile.TemporaryDirectory() as tmp:
        root = build_corpus(CorpusVariant(documented=True, scaled=False), Path(tmp))
        units, endpoints = index_tree(root)
    cell = evaluate_cell(load_case_set("short"), units, endpoints, search_units)

    v1 = run_benchmark()["summary"]
    for key in ("hit_rate_at_k", "macro_recall_at_k", "mrr", "known_trap_rate"):
        assert cell["summary"][key] == pytest.approx(v1[key]), key
