from pathlib import Path

from benchmarks.retrieval.run import FIXTURE_ROOT, index_fixture_repo
from code_steward.db import all_hard_relationships, connect
from code_steward.maintenance import rebuild_index, update_index_file
from code_steward.relationships import extract_python_call_relationships


def _calls_by_source(relationships):
    return {
        source: {(edge.target_kind, edge.target_ref) for edge in edges if edge.relation == "CALLS"}
        for source, edges in relationships.items()
    }


def test_existing_wrapper_fixture_resolves_shared_taxonomy_calls() -> None:
    units, _ = index_fixture_repo()
    relationships, _ = extract_python_call_relationships(FIXTURE_ROOT, units)
    calls = _calls_by_source(relationships)

    for source in [
        "imports.resolve-species",
        "api.resolve-species",
        "cli.resolve-species",
    ]:
        assert ("unit", "taxonomy.normalize") in calls[source]


def test_call_extractor_resolves_local_imported_and_module_calls(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "core.py").write_text(
        "# code-steward: unit core.normalize\n"
        "def normalize(name: str) -> str:\n"
        "    return name.strip()\n\n"
        "# code-steward: unit core.local\n"
        "def local(label: str) -> str:\n"
        "    return normalize(label)\n",
        encoding="utf-8",
    )
    (root / "wrapper.py").write_text(
        "from core import normalize\n\n"
        "# code-steward: unit wrapper.imported\n"
        "def imported(label: str) -> str:\n"
        "    return normalize(label)\n",
        encoding="utf-8",
    )
    (root / "module_wrapper.py").write_text(
        "import core as c\n\n"
        "# code-steward: unit wrapper.module\n"
        "def via_module(label: str) -> str:\n"
        "    return c.normalize(label)\n\n"
        "# code-steward: unit wrapper.unresolved\n"
        "def unresolved(label: str) -> str:\n"
        "    return label.strip()\n",
        encoding="utf-8",
    )

    database = root / ".code-steward" / "index.sqlite3"
    rebuild_index(root, database)
    conn = connect(database)
    try:
        edges = all_hard_relationships(conn)
    finally:
        conn.close()

    calls = {}
    for edge in edges:
        if edge.relation == "CALLS":
            calls.setdefault(edge.source_unit_id, set()).add((edge.target_kind, edge.target_ref))

    assert ("unit", "core.normalize") in calls["core.local"]
    assert ("unit", "core.normalize") in calls["wrapper.imported"]
    assert ("unit", "core.normalize") in calls["wrapper.module"]
    assert ("symbol", "label.strip") in calls["wrapper.unresolved"]


def test_repeated_calls_are_aggregated_with_line_evidence(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text(
        "# code-steward: unit app.helper\n"
        "def helper(value: str) -> str:\n"
        "    return value\n\n"
        "# code-steward: unit app.caller\n"
        "def caller(value: str) -> str:\n"
        "    first = helper(value)\n"
        "    return helper(first)\n",
        encoding="utf-8",
    )

    database = root / ".code-steward" / "index.sqlite3"
    rebuild_index(root, database)
    conn = connect(database)
    try:
        edges = [
            edge
            for edge in all_hard_relationships(conn)
            if edge.source_unit_id == "app.caller"
            and edge.target_kind == "unit"
            and edge.target_ref == "app.helper"
        ]
    finally:
        conn.close()

    assert len(edges) == 1
    assert edges[0].evidence["lines"] == [7, 8]


def test_incremental_update_removes_calls_deleted_from_caller(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    core = root / "core.py"
    wrapper = root / "wrapper.py"
    core.write_text(
        "# code-steward: unit core.normalize\n"
        "def normalize(value: str) -> str:\n"
        "    return value\n",
        encoding="utf-8",
    )
    wrapper.write_text(
        "from core import normalize\n\n"
        "# code-steward: unit wrapper.resolve\n"
        "def resolve(value: str) -> str:\n"
        "    return normalize(value)\n",
        encoding="utf-8",
    )

    database = root / ".code-steward" / "index.sqlite3"
    rebuild_index(root, database)
    wrapper.write_text(
        "from core import normalize\n\n"
        "# code-steward: unit wrapper.resolve\n"
        "def resolve(value: str) -> str:\n"
        "    return value\n",
        encoding="utf-8",
    )

    conn = connect(database)
    try:
        update_index_file(conn, root, wrapper)
        edges = [
            edge
            for edge in all_hard_relationships(conn)
            if edge.source_unit_id == "wrapper.resolve" and edge.relation == "CALLS"
        ]
    finally:
        conn.close()

    assert edges == []


def test_removed_target_becomes_unresolved_symbol_after_incremental_update(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    core = root / "core.py"
    wrapper = root / "wrapper.py"
    core.write_text(
        "# code-steward: unit core.normalize\n"
        "def normalize(value: str) -> str:\n"
        "    return value\n",
        encoding="utf-8",
    )
    wrapper.write_text(
        "from core import normalize\n\n"
        "# code-steward: unit wrapper.resolve\n"
        "def resolve(value: str) -> str:\n"
        "    return normalize(value)\n",
        encoding="utf-8",
    )

    database = root / ".code-steward" / "index.sqlite3"
    rebuild_index(root, database)
    core.write_text(
        "# code-steward: unit core.other\ndef other(value: str) -> str:\n    return value\n",
        encoding="utf-8",
    )

    conn = connect(database)
    try:
        update_index_file(conn, root, core)
        edges = [
            edge
            for edge in all_hard_relationships(conn)
            if edge.source_unit_id == "wrapper.resolve" and edge.relation == "CALLS"
        ]
    finally:
        conn.close()

    assert [(edge.target_kind, edge.target_ref) for edge in edges] == [("symbol", "normalize")]
