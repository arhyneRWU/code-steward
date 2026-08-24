"""Updating several files should cost one relationship refresh.

Measured in the field: a single-file `update` on a 14,791-unit
repository took 22.9 seconds, because `refresh_relationships` re-derives
the whole index every time. Sessions rationally stopped using it and ran
full rebuilds instead -- 197 seconds of one hour spent maintaining the
index against 11 seconds using it.

The cost is per refresh, not per file, so the fix is to refresh once.
"""

from __future__ import annotations

from pathlib import Path

from code_steward.db import all_units, connect
from code_steward.maintenance import rebuild_index, update_index_files


def _project(tmp_path: Path) -> Path:
    (tmp_path / "a.py").write_text("def one():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def two():\n    return 2\n", encoding="utf-8")
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    return tmp_path


def test_several_files_refresh_relationships_once(tmp_path: Path, monkeypatch) -> None:
    root = _project(tmp_path)
    (root / "a.py").write_text("def one():\n    return two()\n", encoding="utf-8")
    (root / "b.py").write_text("def two():\n    return 22\n", encoding="utf-8")

    calls = []
    import code_steward.maintenance as maintenance

    original = maintenance.refresh_relationships
    monkeypatch.setattr(
        maintenance,
        "refresh_relationships",
        lambda conn, project_root: (calls.append(1), original(conn, project_root))[1],
    )
    conn = connect(root / ".code-steward" / "index.sqlite3")
    stats = update_index_files(conn, root, [root / "a.py", root / "b.py"])
    conn.close()

    assert calls == [1], "two files must not cost two whole-index refreshes"
    assert set(stats.updated_paths) == {"a.py", "b.py"}


def test_a_batch_update_indexes_the_new_code(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "a.py").write_text(
        "def one():\n    return 1\n\n\ndef three():\n    return 3\n", "utf-8"
    )
    conn = connect(root / ".code-steward" / "index.sqlite3")
    update_index_files(conn, root, [root / "a.py"])
    names = {unit.name for unit in all_units(conn)}
    conn.close()
    assert "three" in names


def test_a_deleted_file_is_removed_in_a_batch(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "b.py").unlink()
    conn = connect(root / ".code-steward" / "index.sqlite3")
    stats = update_index_files(conn, root, [root / "b.py"])
    names = {unit.name for unit in all_units(conn)}
    conn.close()
    assert "two" not in names
    assert "b.py" in stats.removed_paths
