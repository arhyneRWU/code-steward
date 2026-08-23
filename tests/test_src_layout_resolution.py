"""Resolution across a `src/` layout, which silently found nothing.

A unit at `src/pkg/mod.py` was keyed `src.pkg.mod`, while every
importer writes `from pkg.mod import ...`, which keys `pkg.mod`. The
two can never match, so on a src-layout repository no absolute import
resolved. Measured before the fix: 0 of 157 functions in this
project's own `src/` carried a single TESTED_BY edge, against 323
tests that almost all exercise them.

The failure is silent, which is why it survived. `trace` reports "no
resolved neighbours", and that reads as a caveat about dynamic
dispatch rather than as the whole relation being absent.
"""

from __future__ import annotations

import pytest

from code_steward.db import all_hard_relationships, connect
from code_steward.maintenance import rebuild_index
from code_steward.relationships import _module_key

MODULE = '''\
def compute(value):
    """Double a value and add one."""
    total = value * 2
    return total + 1
'''

TEST = """\
from pkg.mod import compute


def test_compute():
    assert compute(2) == 5
"""


@pytest.fixture
def relationships(tmp_path):
    package = tmp_path / "src" / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mod.py").write_text(MODULE, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_mod.py").write_text(TEST, encoding="utf-8")
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    conn = connect(tmp_path / ".code-steward" / "index.sqlite3")
    found = all_hard_relationships(conn)
    conn.close()
    return found


def test_a_test_importing_across_the_src_root_resolves(relationships):
    edges = [
        edge
        for edge in relationships
        if edge.relation == "TESTED_BY" and edge.target_kind == "unit"
    ]
    assert [(edge.source_unit_id, edge.target_ref) for edge in edges] == [
        ("src.pkg.mod::compute", "tests.test_mod::test_compute")
    ]


def test_unit_ids_keep_the_src_prefix(relationships):
    """Only the resolution key is stripped, never the identifier.

    Unit IDs are the stable name that committed benchmark labels are
    recorded against. Renaming them to match the import path would
    silently invalidate every frozen set in `benchmarks/`, which is
    a far larger cost than the defect being fixed.
    """
    sources = {edge.source_unit_id for edge in relationships}
    assert any(unit_id.startswith("src.pkg.mod::") for unit_id in sources)


def test_the_caller_edge_resolves_too(relationships):
    """The same key mismatch silently emptied CALLS across `src/`."""
    calls = [
        edge for edge in relationships if edge.relation == "CALLS" and edge.target_kind == "unit"
    ]
    assert [edge.target_ref for edge in calls] == ["src.pkg.mod::compute"]


def test_only_an_exact_src_component_is_stripped():
    """Guard on the stripping rule.

    Added after the fix rather than before it.

    A `startswith("src")` implementation would key `srcfoo/bar.py` as
    `foo.bar`, and a rule that ignored the component count would key
    a top-level `src.py` module as the empty string.
    """
    assert _module_key("src/pkg/mod.py") == "pkg.mod"
    assert _module_key("src/pkg/__init__.py") == "pkg"
    assert _module_key("srcfoo/bar.py") == "srcfoo.bar"
    assert _module_key("src.py") == "src"
    assert _module_key("django/db/models/query.py") == "django.db.models.query"
