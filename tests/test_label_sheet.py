from __future__ import annotations

import sqlite3
import textwrap
from pathlib import Path

import pytest

from benchmarks.real_repo.label_sheet import blind_order, build_sheet, load_unit_sources

SOURCE = textwrap.dedent(
    '''
    def alpha():
        """Alpha."""
        return 1


    def beta():
        """Beta."""
        return 2
    '''
).lstrip()

ROWS = [("m::alpha", "m.py", 1, 3), ("m::beta", "m.py", 6, 8)]


@pytest.fixture
def indexed(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "m.py").write_text(SOURCE, encoding="utf-8")
    database = tmp_path / "index.sqlite3"
    conn = sqlite3.connect(database)
    conn.execute(
        "CREATE TABLE units (unit_id TEXT, path TEXT, start_line INTEGER, end_line INTEGER)"
    )
    conn.executemany("INSERT INTO units VALUES (?, ?, ?, ?)", ROWS)
    conn.commit()
    conn.close()
    return tmp_path, database


def test_load_unit_sources_extracts_exact_line_spans(indexed: tuple[Path, Path]) -> None:
    project_root, database = indexed

    sources = load_unit_sources(database, project_root)

    assert sources["m::alpha"].source.splitlines()[0] == "def alpha():"
    assert sources["m::alpha"].source.splitlines()[-1] == "    return 1"
    assert "beta" not in sources["m::alpha"].source


def test_blind_order_is_stable_and_not_alphabetical() -> None:
    units = {f"m::u{index}" for index in range(20)}

    first = blind_order("case-1", units)
    again = blind_order("case-1", units)
    other_case = blind_order("case-2", units)

    assert first == again
    assert sorted(first) == sorted(units)
    # The order must not reproduce any ranking or naming signal.
    assert first != sorted(units)
    assert first != other_case


def test_build_sheet_pools_arms_and_hides_every_answer(indexed: tuple[Path, Path]) -> None:
    project_root, database = indexed
    sources = load_unit_sources(database, project_root)
    cases = [{"id": "c1", "query": "Find alpha.", "relevant": ["m::alpha"], "traps": ["m::beta"]}]
    arms = {
        "cs": [{"id": "c1", "candidates": ["m::alpha"]}],
        "text": [{"id": "c1", "candidates": ["m::beta"]}],
    }

    sheet = build_sheet(cases, arms, sources)

    entry = sheet["sheets"][0]
    assert {candidate["unit_id"] for candidate in entry["candidates"]} == {
        "m::alpha",
        "m::beta",
    }
    # The sheet must leak neither the gold unit nor the arm.
    assert set(entry) == {"case_id", "query", "candidates"}
    for candidate in entry["candidates"]:
        assert set(candidate) == {"unit_id", "path", "lines", "source"}


def test_build_sheet_rejects_a_candidate_missing_from_the_index(
    indexed: tuple[Path, Path],
) -> None:
    project_root, database = indexed
    sources = load_unit_sources(database, project_root)
    cases = [{"id": "c1", "query": "Find alpha.", "relevant": ["m::alpha"]}]
    arms = {"cs": [{"id": "c1", "candidates": ["m::ghost"]}]}

    with pytest.raises(ValueError, match="absent from the index"):
        build_sheet(cases, arms, sources)
