from pathlib import Path

from code_steward.db import all_hard_relationships, connect, get_unit
from code_steward.maintenance import rebuild_index, update_index_file
from code_steward.relationships import (
    PYTHON_AST_PROVENANCE,
    TESTS_PROVENANCE,
    refresh_python_call_relationships,
    refresh_tested_by_relationships,
)

CORE_SOURCE = """# code-steward: unit core.normalize
def normalize(name: str) -> str:
    return name.strip()


# code-steward: unit core.shout
def shout(name: str) -> str:
    return normalize(name).upper()
"""

TEST_SOURCE = """from core import normalize, shout


# code-steward: unit tests.helper
def build_label(raw: str) -> str:
    return raw.strip()


# code-steward: unit tests.test-normalize
def test_normalize() -> None:
    assert normalize(" a ") == "a"


# code-steward: unit tests.test-shout
def test_shout() -> None:
    label = build_label(" a ")
    assert shout(label) == "A"
    assert label.upper() == "A"
"""


def _write_repo(tmp_path: Path, test_source: str = TEST_SOURCE) -> Path:
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "core.py").write_text(CORE_SOURCE, encoding="utf-8")
    (root / "tests" / "test_core.py").write_text(test_source, encoding="utf-8")
    return root


def _tested_by(edges):
    return {
        (edge.source_unit_id, edge.target_ref)
        for edge in edges
        if edge.relation == "TESTED_BY" and edge.provenance == TESTS_PROVENANCE
    }


def _built(tmp_path: Path, test_source: str = TEST_SOURCE):
    root = _write_repo(tmp_path, test_source)
    database = root / ".code-steward" / "index.sqlite3"
    rebuild_index(root, database)
    return root, connect(database)


def test_test_function_creates_tested_by_edge_on_production_unit(tmp_path: Path) -> None:
    _root, conn = _built(tmp_path)
    try:
        edges = all_hard_relationships(conn)
    finally:
        conn.close()

    assert ("core.normalize", "tests.test-normalize") in _tested_by(edges)
    assert ("core.shout", "tests.test-shout") in _tested_by(edges)


def test_tested_by_evidence_locates_the_test_unit(tmp_path: Path) -> None:
    _root, conn = _built(tmp_path)
    try:
        edges = all_hard_relationships(conn)
    finally:
        conn.close()

    edge = next(
        item
        for item in edges
        if item.relation == "TESTED_BY" and item.source_unit_id == "core.normalize"
    )
    assert edge.target_kind == "unit"
    assert edge.provenance == TESTS_PROVENANCE
    assert edge.evidence["path"] == "tests/test_core.py"
    assert edge.evidence["name"] == "test_normalize"
    assert edge.evidence["qualname"] == "test_normalize"
    assert edge.evidence["lines"] == [11]


def test_production_to_production_call_is_not_tested_by(tmp_path: Path) -> None:
    _root, conn = _built(tmp_path)
    try:
        edges = all_hard_relationships(conn)
    finally:
        conn.close()

    tested_by = _tested_by(edges)
    assert ("core.normalize", "core.shout") not in tested_by
    assert all(target.startswith("tests.") for _source, target in tested_by)


def test_test_helper_functions_do_not_produce_tested_by_edges(tmp_path: Path) -> None:
    _root, conn = _built(tmp_path)
    try:
        edges = all_hard_relationships(conn)
    finally:
        conn.close()

    tested_by = _tested_by(edges)
    assert not any(source == "tests.helper" for source, _target in tested_by)
    assert not any(target == "tests.helper" for _source, target in tested_by)


def test_unresolved_symbol_calls_are_ignored(tmp_path: Path) -> None:
    _root, conn = _built(tmp_path)
    try:
        edges = all_hard_relationships(conn)
    finally:
        conn.close()

    unresolved = {
        edge.target_ref
        for edge in edges
        if edge.relation == "CALLS" and edge.target_kind == "symbol"
    }
    assert "label.upper" in unresolved
    assert all(edge.target_kind == "unit" for edge in edges if edge.relation == "TESTED_BY")


def test_refreshing_tests_provenance_keeps_python_ast_edges(tmp_path: Path) -> None:
    root, conn = _built(tmp_path)
    try:
        before = [edge for edge in all_hard_relationships(conn) if edge.relation == "CALLS"]
        refresh_tested_by_relationships(conn)
        after = [edge for edge in all_hard_relationships(conn) if edge.relation == "CALLS"]
        assert before == after
        assert all(edge.provenance == PYTHON_AST_PROVENANCE for edge in after)

        refresh_python_call_relationships(conn, root)
        tested_by = _tested_by(all_hard_relationships(conn))
        assert ("core.normalize", "tests.test-normalize") in tested_by
    finally:
        conn.close()


def test_tested_by_edge_is_invalidated_when_the_test_stops_calling(tmp_path: Path) -> None:
    root, conn = _built(tmp_path)
    try:
        initial = _tested_by(all_hard_relationships(conn))
        assert ("core.normalize", "tests.test-normalize") in initial

        rewritten = TEST_SOURCE.replace(
            '    assert normalize(" a ") == "a"',
            '    assert " a ".strip() == "a"',
        )
        test_file = root / "tests" / "test_core.py"
        test_file.write_text(rewritten, encoding="utf-8")
        update_index_file(conn, root, test_file)

        tested_by = _tested_by(all_hard_relationships(conn))
        assert ("core.normalize", "tests.test-normalize") not in tested_by
        assert ("core.shout", "tests.test-shout") in tested_by
    finally:
        conn.close()


def test_tested_by_target_hash_tracks_the_test_body(tmp_path: Path) -> None:
    root, conn = _built(tmp_path)
    try:
        rewritten = TEST_SOURCE.replace(
            '    assert normalize(" a ") == "a"',
            '    assert normalize("  a  ") == "a"',
        )
        test_file = root / "tests" / "test_core.py"
        test_file.write_text(rewritten, encoding="utf-8")
        update_index_file(conn, root, test_file)

        edge = next(
            item
            for item in all_hard_relationships(conn)
            if item.relation == "TESTED_BY" and item.source_unit_id == "core.normalize"
        )
        test_unit = get_unit(conn, "tests.test-normalize")
        assert test_unit is not None
        assert edge.target_hash == test_unit.body_hash
    finally:
        conn.close()


def test_pytest_fixtures_do_not_produce_tested_by_edges(tmp_path: Path) -> None:
    fixture_source = """import pytest

from core import normalize


# code-steward: unit tests.fixture-label
@pytest.fixture
def label() -> str:
    return normalize(" a ")


# code-steward: unit tests.test-uses-fixture
def test_uses_fixture(label: str) -> None:
    assert label == "a"
"""
    _root, conn = _built(tmp_path, fixture_source)
    try:
        tested_by = _tested_by(all_hard_relationships(conn))
    finally:
        conn.close()

    assert not any(target == "tests.fixture-label" for _source, target in tested_by)
