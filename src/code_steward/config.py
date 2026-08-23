"""Persistent project configuration read from ``pyproject.toml``.

Only ``[tool.code-steward]`` is consulted, and only the ``exclude``
key is understood today.  A project with no ``pyproject.toml`` and a
file with no ``[tool.code-steward]`` table both mean "no excludes".
Configuration that is present but wrong is an error: silently
ignoring a mistyped ``exclude`` would surface later as a confusing
indexing failure somewhere else.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    try:
        import tomli as _toml  # type: ignore[no-redef]
    except ModuleNotFoundError:  # pragma: no cover - no TOML reader available
        _toml = None  # type: ignore[assignment]

CONFIG_FILENAME = "pyproject.toml"
TOOL_TABLE = "code-steward"


def _read_tool_table(project_root: Path) -> dict[str, Any]:
    """Return ``[tool.code-steward]`` or an empty mapping."""
    if _toml is None:
        return {}
    config = project_root / CONFIG_FILENAME
    try:
        text = config.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = _toml.loads(text)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"{CONFIG_FILENAME}: could not be parsed: {exc}") from exc
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return {}
    table = tool.get(TOOL_TABLE)
    return table if isinstance(table, dict) else {}


def load_config_excludes(project_root: Path) -> tuple[str, ...]:
    """Read exclude patterns configured for this project.

    An absent key means no excludes. A key that is present but not a
    list of non-empty strings is a configuration error, because the
    author clearly intended something that will not happen.
    """
    table = _read_tool_table(project_root)
    if "exclude" not in table:
        return ()
    values = table["exclude"]
    if not isinstance(values, list):
        raise ValueError(
            f"{CONFIG_FILENAME}: [tool.{TOOL_TABLE}] exclude must be a list of "
            f"strings, got {type(values).__name__}"
        )
    for value in values:
        if not isinstance(value, str) or not value:
            raise ValueError(
                f"{CONFIG_FILENAME}: [tool.{TOOL_TABLE}] exclude entries must be "
                f"non-empty strings, got {value!r}"
            )
    return tuple(values)


def resolve_excludes(
    project_root: Path,
    cli_excludes: Iterable[str] = (),
) -> tuple[str, ...]:
    """Union configured excludes with the ones given on the CLI.

    Config order is preserved and CLI values are appended, so
    neither source can silently replace the other.
    """
    resolved: list[str] = []
    for value in (*load_config_excludes(project_root), *cli_excludes):
        if value and value not in resolved:
            resolved.append(value)
    return tuple(resolved)
