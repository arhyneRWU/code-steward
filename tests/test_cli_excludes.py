from pathlib import Path

from code_steward.cli import main
from code_steward.db import all_units, connect


def _write_unit(path: Path, unit_id: str, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# code-steward: unit {unit_id}\ndef {name}() -> str:\n    return {name!r}\n",
        encoding="utf-8",
    )


def _units(root: Path) -> list[tuple[str, str]]:
    conn = connect(root / ".code-steward" / "index.sqlite3")
    try:
        return sorted((unit.unit_id, unit.path) for unit in all_units(conn))
    finally:
        conn.close()


def _repo_with_duplicate_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _write_unit(root / "app.py", "taxonomy.normalize", "normalize")
    _write_unit(root / "tests" / "fixtures" / "dupe.py", "taxonomy.normalize", "normalize_fixture")
    return root


def test_build_without_flags_uses_config_excludes(tmp_path: Path) -> None:
    root = _repo_with_duplicate_fixture(tmp_path)
    (root / "pyproject.toml").write_text(
        '[tool.code-steward]\nexclude = ["tests/fixtures"]\n', encoding="utf-8"
    )

    assert main(["--root", str(root), "build", "--quiet"]) == 0
    assert _units(root) == [("taxonomy.normalize", "app.py")]


def test_build_without_config_still_fails_on_duplicate_units(tmp_path: Path) -> None:
    root = _repo_with_duplicate_fixture(tmp_path)
    assert main(["--root", str(root), "build", "--quiet"]) == 1


def test_build_unions_config_and_cli_excludes(tmp_path: Path) -> None:
    root = _repo_with_duplicate_fixture(tmp_path)
    (root / "pyproject.toml").write_text(
        '[tool.code-steward]\nexclude = ["tests/fixtures"]\n', encoding="utf-8"
    )
    _write_unit(root / "scratch" / "draft.py", "scratch.draft", "draft")

    assert main(["--root", str(root), "build", "--quiet", "--exclude", "scratch"]) == 0
    assert _units(root) == [("taxonomy.normalize", "app.py")]


def test_update_honours_config_excludes(tmp_path: Path) -> None:
    root = _repo_with_duplicate_fixture(tmp_path)
    (root / "pyproject.toml").write_text(
        '[tool.code-steward]\nexclude = ["tests/fixtures"]\n', encoding="utf-8"
    )
    assert main(["--root", str(root), "build", "--quiet"]) == 0

    fixture = root / "tests" / "fixtures" / "dupe.py"
    assert main(["--root", str(root), "update", str(fixture), "--quiet"]) == 0
    assert _units(root) == [("taxonomy.normalize", "app.py")]


def test_update_honours_cli_excludes(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_unit(root / "app.py", "taxonomy.normalize", "normalize")
    assert main(["--root", str(root), "build", "--quiet"]) == 0

    _write_unit(root / "scratch" / "draft.py", "scratch.draft", "draft")
    scratch = root / "scratch" / "draft.py"
    argv = ["--root", str(root), "update", str(scratch), "--quiet", "--exclude", "scratch"]
    assert main(argv) == 0
    assert _units(root) == [("taxonomy.normalize", "app.py")]


def test_update_still_indexes_non_excluded_files(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[tool.code-steward]\nexclude = ["tests/fixtures"]\n', encoding="utf-8"
    )
    _write_unit(root / "app.py", "taxonomy.normalize", "normalize")
    assert main(["--root", str(root), "build", "--quiet"]) == 0

    _write_unit(root / "extra.py", "taxonomy.extra", "extra")
    assert main(["--root", str(root), "update", str(root / "extra.py"), "--quiet"]) == 0
    assert _units(root) == [("taxonomy.extra", "extra.py"), ("taxonomy.normalize", "app.py")]
