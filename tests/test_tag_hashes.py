from pathlib import Path

from code_steward.indexer import index_python_file


def _indexed_fixture(tmp_path: Path, fixture_name: str):
    source = Path(__file__).parent / "fixtures" / fixture_name
    tmp_path.mkdir(parents=True, exist_ok=True)
    target = tmp_path / fixture_name
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    units, _ = index_python_file(tmp_path, target)
    return {unit.qualname: unit for unit in units}


def test_alias_and_nested_region_renames_do_not_change_declaration_hash(
    tmp_path: Path,
) -> None:
    first = _indexed_fixture(tmp_path / "a", "tag_hash_a.py")
    second = _indexed_fixture(tmp_path / "b", "tag_hash_b.py")

    assert first["normalize"].unit_id == "taxonomy.normalize"
    assert second["normalize"].unit_id == "taxonomy.resolve"
    assert first["normalize"].body_hash == second["normalize"].body_hash


def test_region_rename_does_not_change_region_hash(tmp_path: Path) -> None:
    first = _indexed_fixture(tmp_path / "a", "tag_hash_a.py")
    second = _indexed_fixture(tmp_path / "b", "tag_hash_b.py")

    assert first["taxonomy.validation"].body_hash == second["taxonomy.checks"].body_hash
    assert (
        first["taxonomy.normalize.cleaning"].body_hash
        == second["taxonomy.resolve.cleaning"].body_hash
    )
