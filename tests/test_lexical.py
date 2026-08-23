"""Tests for the lexical matching shared by the ranker and its control.

The control arm and the thing it controls must agree about what a
query term is, or the comparison between them measures the difference
in their tokenisers rather than the difference in their ideas. One of
these tests exists solely to keep them sharing an implementation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_steward.lexical import (
    STOPWORDS,
    body_terms,
    query_terms,
    term_coverage,
)
from code_steward.search import WEIGHTS

ROOT = Path(__file__).resolve().parents[1]


def test_query_terms_drops_stopwords():
    assert query_terms("find the function that selects a proxy") == ["selects", "proxy"]


def test_query_terms_drops_task_phrasing():
    """'helper', 'existing', 'reusable' match almost every unit."""
    for word in ("helper", "existing", "reusable", "implementation"):
        assert word in STOPWORDS


def test_query_terms_deduplicates_and_lowercases():
    assert query_terms("Proxy proxy PROXY select") == ["proxy", "select"]


def test_query_terms_ignores_runs_shorter_than_three():
    assert query_terms("go to id x") == []


def test_body_terms_keeps_distinct_tokens_only():
    assert body_terms("def foo(bar):\n    return foo(bar)") == "def foo bar return"


def test_body_terms_lowercases():
    assert body_terms("SelectProxy") == "selectproxy"


def test_term_coverage_matches_substrings_not_whole_tokens():
    """Substring matching is why "rebuild" finds rebuild_proxies."""
    assert term_coverage(["rebuild"], "def rebuild_proxies self") == pytest.approx(100.0)


def test_term_coverage_is_the_fraction_of_terms_present():
    assert term_coverage(["alpha", "beta"], "alpha only") == pytest.approx(50.0)


def test_an_empty_query_scores_zero_not_full_marks():
    """Otherwise every unit in the repository gets a perfect score."""
    assert term_coverage([], "anything at all") == 0.0


def test_an_empty_body_scores_zero():
    assert term_coverage(["alpha"], "") == 0.0


def test_the_weights_sum_to_one():
    """A base score outside 0-100 would break the type bonus cap."""
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_body_carries_half_the_weight():
    """Fixed before measuring; see the rationale in search.py."""
    assert WEIGHTS["body"] == pytest.approx(0.5)


def test_the_five_metadata_fields_kept_their_proportions():
    metadata = {k: v for k, v in WEIGHTS.items() if k != "body"}
    assert sum(metadata.values()) == pytest.approx(0.5)
    # Previously purpose .35, signature .20, concepts .20, name .15,
    # qualname .10 -- each halved, so the ratios are unchanged.
    assert metadata["purpose"] / metadata["qualname"] == pytest.approx(3.5)
    assert metadata["signature"] == pytest.approx(metadata["concepts"])


def test_the_control_arm_shares_this_implementation():
    """A control with its own tokeniser is not a control."""
    source = (ROOT / "benchmarks" / "real_repo" / "grep_baseline.py").read_text(encoding="utf-8")
    assert "from code_steward.lexical import" in source
    assert "STOPWORDS = frozenset" not in source
