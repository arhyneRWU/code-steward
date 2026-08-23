from pathlib import Path

import pytest

from code_steward.db import all_units, connect
from code_steward.maintenance import rebuild_index, update_index_file


def _write_unit(path: Path, unit_id: str, name: str) -> None:
    path.write_text(
        f"# code-steward: unit {unit_id}\ndef {name}() -> str:\n    return {name!r}\n",
        encoding="utf-8",
    )


def _indexed_units(db_path: Path) -> list[tuple[str, str]]:
    conn = connect(db_path)
    try:
        return [(unit.unit_id, unit.path) for unit in all_units(conn)]
    finally:
        conn.close()


def test_atomic_rebuild_removes_deleted_files_and_allows_semantic_id_move(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    database = root / ".code-steward" / "index.sqlite3"
    source = root / "a.py"
    destination = root / "b.py"

    _write_unit(source, "shared.normalize", "normalize_a")
    rebuild_index(root, database)
    assert _indexed_units(database) == [("shared.normalize", "a.py")]

    source.unlink()
    _write_unit(destination, "shared.normalize", "normalize_b")
    rebuild_index(root, database)

    assert _indexed_units(database) == [("shared.normalize", "b.py")]


def test_failed_duplicate_rebuild_preserves_last_valid_index(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    database = root / ".code-steward" / "index.sqlite3"

    _write_unit(root / "a.py", "shared.normalize", "normalize_a")
    rebuild_index(root, database)
    before = database.read_bytes()

    _write_unit(root / "b.py", "shared.normalize", "normalize_b")
    with pytest.raises(ValueError, match="conflicts with existing unit"):
        rebuild_index(root, database)

    assert database.read_bytes() == before
    assert _indexed_units(database) == [("shared.normalize", "a.py")]
    assert list(database.parent.glob(f".{database.name}.*.tmp")) == []


def test_failed_parse_rebuild_preserves_last_valid_index(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    database = root / ".code-steward" / "index.sqlite3"

    _write_unit(root / "a.py", "stable.unit", "stable")
    rebuild_index(root, database)
    before = database.read_bytes()

    (root / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        rebuild_index(root, database)

    assert database.read_bytes() == before
    assert _indexed_units(database) == [("stable.unit", "a.py")]


def test_incremental_move_succeeds_before_old_file_update_event(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    database = root / ".code-steward" / "index.sqlite3"
    old_path = root / "a.py"
    new_path = root / "b.py"

    _write_unit(old_path, "shared.normalize", "normalize_a")
    rebuild_index(root, database)

    old_path.write_text(
        "def former_owner() -> str:\n    return 'released'\n",
        encoding="utf-8",
    )
    _write_unit(new_path, "shared.normalize", "normalize_b")

    conn = connect(database)
    try:
        stats = update_index_file(conn, root, new_path)
    finally:
        conn.close()

    assert stats.updated_paths == ("a.py", "b.py")
    assert ("shared.normalize", "b.py") in _indexed_units(database)
    assert ("shared.normalize", "a.py") not in _indexed_units(database)


def test_incremental_duplicate_claim_fails_without_mutation(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    database = root / ".code-steward" / "index.sqlite3"
    old_path = root / "a.py"
    new_path = root / "b.py"

    _write_unit(old_path, "shared.normalize", "normalize_a")
    rebuild_index(root, database)
    before = database.read_bytes()
    _write_unit(new_path, "shared.normalize", "normalize_b")

    conn = connect(database)
    try:
        with pytest.raises(ValueError, match="Duplicate Code Steward unit ID"):
            update_index_file(conn, root, new_path)
    finally:
        conn.close()

    assert database.read_bytes() == before
    assert _indexed_units(database) == [("shared.normalize", "a.py")]


def test_incremental_delete_removes_stale_file(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    database = root / ".code-steward" / "index.sqlite3"
    source = root / "a.py"

    _write_unit(source, "stable.unit", "stable")
    rebuild_index(root, database)
    source.unlink()

    conn = connect(database)
    try:
        stats = update_index_file(conn, root, source)
    finally:
        conn.close()

    assert stats.removed_paths == ("a.py",)
    assert _indexed_units(database) == []
