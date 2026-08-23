"""Async functions must be comparable, like any other function.

`similarity.FUNCTION_KINDS` was `{"function", "method"}`. The indexer
emits `"async_function"` and never emits `"method"`, so the set held
one dead entry and was missing a real one -- and `check` and `similar`
silently skipped every `async def`.

Measured share of functions that were invisible: Django 2.8%, Airflow
5.4%, **Home Assistant 43.4%**. The alarm rate published for Home
Assistant in `docs/check.md` was computed on a population missing
nearly half the repository.
"""

from __future__ import annotations

import pytest

from code_steward.db import all_units, connect
from code_steward.maintenance import rebuild_index
from code_steward.similarity import unit_shingles

SOURCE = '''\
async def fetch_and_total(rows, limit):
    """Sum the rows an async source yields."""
    total = 0
    for key, value in rows.items():
        if value is None:
            continue
        total += value
    return total, limit


def plain_total(rows, limit):
    """Sum rows from a synchronous source."""
    total = 0
    for key, value in rows.items():
        if value is None:
            continue
        total += value
    return total, limit
'''


@pytest.fixture
def units(tmp_path):
    (tmp_path / "mixed.py").write_text(SOURCE, encoding="utf-8")
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    conn = connect(tmp_path / ".code-steward" / "index.sqlite3")
    found = all_units(conn)
    conn.close()
    return tmp_path, found


def test_an_async_function_gets_shingles(units):
    """Without shingles a function cannot be compared to anything."""
    project, found = units
    prepared = unit_shingles(project, found, cache=False)
    assert "mixed::fetch_and_total" in prepared
    assert prepared["mixed::fetch_and_total"]


def test_check_reports_a_duplicate_between_an_async_and_a_sync_function(tmp_path, capsys):
    """The user-visible consequence, not just the missing shingles."""
    from code_steward.cli import main

    target = tmp_path / "mixed.py"
    target.write_text(SOURCE, encoding="utf-8")
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    assert main(["--root", str(tmp_path), "check", str(target), "--all-overlaps"]) == 0
    out = capsys.readouterr().out
    assert "fetch_and_total" in out
