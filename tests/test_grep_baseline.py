from __future__ import annotations

import sqlite3
import textwrap
from pathlib import Path

import pytest

from benchmarks.real_repo.grep_baseline import (
    UnitSpan,
    enclosing_unit,
    load_spans,
    query_terms,
    rank_units,
    run_baseline,
)

SOURCE = textwrap.dedent(
    '''
    """Module docstring."""


    class Jar:
        """Hold cookies."""

        def from_mapping(self, values):
            """Convert a name/value dictionary into a cookie jar."""
            return dict(values)


    def unrelated_helper(value):
        """Compute a checksum."""
        return value
    '''
).lstrip()

# (unit_id, start_line, end_line) for SOURCE, matching what the indexer
# records: the class span encloses the method span.
SPAN_ROWS = [
    ("jar::Jar", "jar.py", 4, 9),
    ("jar::Jar.from_mapping", "jar.py", 7, 9),
    ("jar::unrelated_helper", "jar.py", 12, 14),
]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "jar.py").write_text(SOURCE, encoding="utf-8")
    return tmp_path


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "index.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE units (unit_id TEXT, path TEXT, start_line INTEGER, end_line INTEGER)"
    )
    conn.executemany("INSERT INTO units VALUES (?, ?, ?, ?)", SPAN_ROWS)
    conn.commit()
    conn.close()
    return path


def test_query_terms_drops_boilerplate_and_keeps_order() -> None:
    terms = query_terms("Find the reusable helper that converts a cookie dictionary.")

    assert terms == ["converts", "cookie", "dictionary"]


def test_query_terms_deduplicates_case_insensitively() -> None:
    assert query_terms("Cookie cookie COOKIE jar") == ["cookie", "jar"]


def test_query_terms_ignores_tokens_shorter_than_three_characters() -> None:
    assert query_terms("an id or a jar") == ["jar"]


def test_enclosing_unit_prefers_the_innermost_span() -> None:
    spans = sorted(
        (UnitSpan(unit_id, path, start, end) for unit_id, path, start, end in SPAN_ROWS),
        key=lambda span: (span.start_line, -span.end_line),
    )

    assert enclosing_unit(spans, 8) == "jar::Jar.from_mapping"
    assert enclosing_unit(spans, 5) == "jar::Jar"
    assert enclosing_unit(spans, 13) == "jar::unrelated_helper"


def test_enclosing_unit_returns_none_outside_every_span() -> None:
    spans = [UnitSpan("jar::Jar", "jar.py", 4, 9)]

    assert enclosing_unit(spans, 1) is None
    assert enclosing_unit(spans, 40) is None


def test_load_spans_groups_by_path(database: Path) -> None:
    spans = load_spans(database)

    assert set(spans) == {"jar.py"}
    assert [span.unit_id for span in spans["jar.py"]] == [
        "jar::Jar",
        "jar::Jar.from_mapping",
        "jar::unrelated_helper",
    ]


def test_rank_units_orders_by_distinct_term_coverage(project: Path, database: Path) -> None:
    spans = load_spans(database)

    ordered, total_hits = rank_units(["cookie", "dictionary"], project, spans)

    assert total_hits > 0
    # The method mentions both terms; the class mentions only "cookies",
    # so coverage must place the method first.
    assert ordered[0] == "jar::Jar.from_mapping"
    assert "jar::unrelated_helper" not in ordered


def test_rank_units_ignores_matches_outside_any_unit(project: Path, database: Path) -> None:
    spans = load_spans(database)

    ordered, total_hits = rank_units(["Module"], project, spans)

    assert total_hits == 1
    assert ordered == []


def test_run_baseline_scores_a_case_it_can_answer(
    project: Path, database: Path, tmp_path: Path
) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        '[{"id": "c1", "category": "cookie-conversion", "limit": 8,'
        ' "query": "Find the code that converts a name/value dictionary into a cookie jar.",'
        ' "relevant": ["jar::Jar.from_mapping"], "traps": ["jar::unrelated_helper"]}]',
        encoding="utf-8",
    )

    report = run_baseline(project, database, cases_path)

    assert report["strategy"] == "text-search-term-coverage"
    assert report["summary"]["case_count"] == 1
    assert report["summary"]["hit_rate_at_1"] == 1.0
    # "value" appears in the trap's signature, so a term-coverage
    # baseline surfaces it. The harness must report that, not hide it.
    assert report["cases"][0]["known_traps_returned"] == 1
    # The reported cost is real source bytes, not an estimate.
    assert report["cases"][0]["read_bytes"] > 0


def test_run_baseline_reports_a_miss_rather_than_hiding_it(
    project: Path, database: Path, tmp_path: Path
) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        '[{"id": "c1", "category": "unfindable", "limit": 8,'
        ' "query": "Find the quantum flux capacitor calibration routine.",'
        ' "relevant": ["jar::Jar.from_mapping"], "traps": []}]',
        encoding="utf-8",
    )

    report = run_baseline(project, database, cases_path)

    assert report["summary"]["hit_rate_at_k"] == 0.0
    assert report["cases"][0]["unbounded_rank_of_first_relevant"] is None
