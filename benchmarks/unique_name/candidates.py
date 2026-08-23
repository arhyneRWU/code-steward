"""Find the call sites the unique-name rule would resolve.

Pre-registered in `docs/unique-name-resolution.md`. The rule: where
`obj.method()` cannot be resolved by type but exactly one indexed
unit is named `method`, treat the call as an edge to that unit.

This module only *selects* those sites. Whether resolving them is
correct is decided by an oracle that does not work by name, because
a name-based key and a name-based rule are the same rule and would
agree by construction.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from code_steward.models import CodeUnit

CALLABLE_KINDS = frozenset({"function", "async_function", "method"})


@dataclass(slots=True, frozen=True)
class Candidate:
    """One `obj.method()` call the rule would turn into an edge."""

    path: str
    line: int
    column: int
    attribute: str
    caller: str


def unique_names(units: list[CodeUnit]) -> set[str]:
    """Names held by exactly one callable unit in the index."""
    counts = Counter(unit.name for unit in units if unit.kind in CALLABLE_KINDS)
    return {name for name, count in counts.items() if count == 1}


def attribute_call_sites(root: Path, files: list[Path], names: set[str]) -> list[Candidate]:
    """Every `obj.method()` whose method name is in ``names``.

    Plain `method()` calls are excluded: those already resolve, and
    including them would credit the rule with edges it did not add.
    The column is one-based, pointing at the attribute, because that
    is what a goto-definition oracle expects.
    """
    found: list[Candidate] = []
    for relative in files:
        try:
            source = (root / relative).read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue
        holder: dict[int, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                    holder.setdefault(line, node.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in names:
                continue
            if func.end_col_offset is None:
                continue
            found.append(
                Candidate(
                    path=str(relative),
                    line=func.lineno,
                    # Zero-based column of the attribute's first
                    # character, which is the convention jedi's
                    # goto() takes.
                    column=func.end_col_offset - len(func.attr),
                    attribute=func.attr,
                    caller=holder.get(func.lineno, ""),
                )
            )
    return found
