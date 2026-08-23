from pathlib import Path

import pytest

from code_steward import config
from code_steward.config import load_config_excludes, resolve_excludes


def _write_pyproject(root: Path, body: str) -> None:
    (root / "pyproject.toml").write_text(body, encoding="utf-8")


def test_load_config_excludes_reads_tool_table(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path,
        '[tool.code-steward]\nexclude = ["tests/fixtures", "benchmarks"]\n',
    )
    assert load_config_excludes(tmp_path) == ("tests/fixtures", "benchmarks")


def test_load_config_excludes_without_pyproject(tmp_path: Path) -> None:
    assert load_config_excludes(tmp_path) == ()


def test_load_config_excludes_without_tool_table(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, '[project]\nname = "demo"\n')
    assert load_config_excludes(tmp_path) == ()


def test_load_config_excludes_rejects_non_string_entries(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, '[tool.code-steward]\nexclude = ["ok", 3]\n')
    with pytest.raises(ValueError, match="non-empty strings"):
        load_config_excludes(tmp_path)


def test_load_config_excludes_rejects_broken_toml(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, "[tool.code-steward\nexclude = [\n")
    with pytest.raises(ValueError, match="could not be parsed"):
        load_config_excludes(tmp_path)


def test_load_config_excludes_rejects_wrong_type(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, '[tool.code-steward]\nexclude = "tests/fixtures"\n')
    with pytest.raises(ValueError, match="must be a list of strings"):
        load_config_excludes(tmp_path)


def test_load_config_excludes_without_a_toml_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Python 3.10 without the tomli backport degrades, not crashes."""
    _write_pyproject(tmp_path, '[tool.code-steward]\nexclude = ["fixtures"]\n')
    monkeypatch.setattr(config, "_toml", None)
    assert load_config_excludes(tmp_path) == ()


def test_resolve_excludes_unions_config_and_cli(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, '[tool.code-steward]\nexclude = ["fixtures"]\n')
    assert resolve_excludes(tmp_path, ["scratch", "fixtures"]) == ("fixtures", "scratch")


def test_resolve_excludes_without_cli_values(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, '[tool.code-steward]\nexclude = ["fixtures"]\n')
    assert resolve_excludes(tmp_path, []) == ("fixtures",)


def test_resolve_excludes_without_config(tmp_path: Path) -> None:
    assert resolve_excludes(tmp_path, ["scratch"]) == ("scratch",)


def test_this_repo_dogfoods_exclude_config() -> None:
    root = Path(__file__).resolve().parents[1]
    excludes = load_config_excludes(root)
    assert "tests/fixtures" in excludes
    assert "benchmarks/retrieval/fixture_repo" in excludes
