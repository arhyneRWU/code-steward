from pathlib import Path

import pytest

from code_steward.db import all_units, connect, replace_file
from code_steward.models import CodeUnit


def _unit(unit_id: str, path: str, name: str = "normalize") -> CodeUnit:
    return CodeUnit(
        unit_id=unit_id,
        path=path,
        kind="function",
        name=name,
        qualname=name,
        start_line=1,
        end_line=2,
    )


def test_cross_file_unit_id_conflict_fails_without_replacing_existing_unit(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    replace_file(conn, "a.py", [_unit("shared.normalize", "a.py")], [])

    with pytest.raises(ValueError, match="conflicts with existing unit"):
        replace_file(conn, "b.py", [_unit("shared.normalize", "b.py")], [])

    units = all_units(conn)
    assert [(unit.unit_id, unit.path) for unit in units] == [("shared.normalize", "a.py")]


def test_reindexing_same_file_can_keep_semantic_id(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    replace_file(conn, "a.py", [_unit("shared.normalize", "a.py")], [])
    replace_file(conn, "a.py", [_unit("shared.normalize", "a.py", "normalize_again")], [])

    units = all_units(conn)
    assert len(units) == 1
    assert units[0].unit_id == "shared.normalize"
    assert units[0].name == "normalize_again"


def test_duplicate_ids_in_one_replace_call_fail_before_mutation(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    replace_file(conn, "stable.py", [_unit("stable.unit", "stable.py")], [])

    duplicate = [_unit("duplicate.unit", "new.py"), _unit("duplicate.unit", "new.py")]
    with pytest.raises(ValueError, match="Duplicate Code Steward unit ID"):
        replace_file(conn, "new.py", duplicate, [])

    units = all_units(conn)
    assert [(unit.unit_id, unit.path) for unit in units] == [("stable.unit", "stable.py")]
