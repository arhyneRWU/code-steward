"""Load corpus units and normalise their bodies for comparison.

The reuse question is asked about function-shaped things, so classes
and modules are not candidates. A unit also has to be big enough that
reusing it would save anyone anything: a two-line property is
duplicated all over every codebase and no reviewer would file that as
a reuse finding.

Normalisation runs through ``ast.unparse``, which discards comments
and formatting and re-emits canonical source. Identifiers are kept.
Renaming locals would turn the token-shingle arm into a structural
comparator, and structural comparison is a different arm with
different failure modes -- worth building later, not worth smuggling
into the control.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from code_steward.indexer import index_python_file
from code_steward.models import CodeUnit

# A unit under five lines is too small for reuse to be the right
# call even when two of them are identical.
MIN_LINES = 5

# Below this many normalised tokens the shingle arm has nothing to
# work with and every pair scores near 1.0 by accident.
MIN_TOKENS = 20

FUNCTION_KINDS = frozenset({"function", "method"})


@dataclass(slots=True, frozen=True)
class CorpusUnit:
    """One candidate function with the text each arm scores."""

    unit_id: str
    corpus: str
    path: str
    start_line: int
    end_line: int
    unit: CodeUnit
    normalised: str
    tokens: tuple[str, ...]

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


def _strip_docstring(node: ast.AST) -> None:
    body = getattr(node, "body", None)
    if not body:
        return
    first = body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        del body[0]
        if not body:
            body.append(ast.Pass())


def normalise(node: ast.AST) -> str:
    """Re-emit a declaration as canonical source without docstrings."""
    clone = ast.parse(ast.unparse(node)).body[0]
    for child in ast.walk(clone):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            _strip_docstring(child)
    return ast.unparse(clone)


def tokenise(text: str) -> tuple[str, ...]:
    """Split normalised source into comparable tokens."""
    tokens: list[str] = []
    current: list[str] = []
    for char in text:
        if char.isalnum() or char == "_":
            current.append(char)
            continue
        if current:
            tokens.append("".join(current))
            current = []
        if not char.isspace():
            tokens.append(char)
    if current:
        tokens.append("".join(current))
    return tuple(tokens)


def _declarations(tree: ast.AST) -> dict[int, ast.AST]:
    found: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found[node.lineno] = node
    return found


def load_units(corpus: str, checkout: Path, files: list[Path]) -> list[CorpusUnit]:
    """Index a corpus sample and keep the units worth comparing."""
    units: list[CorpusUnit] = []
    for path in files:
        try:
            indexed, _ = index_python_file(checkout, path)
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        declarations = _declarations(tree)
        for unit in indexed:
            if unit.kind not in FUNCTION_KINDS:
                continue
            if unit.end_line - unit.start_line + 1 < MIN_LINES:
                continue
            node = declarations.get(unit.start_line)
            if node is None:
                continue
            try:
                normalised = normalise(node)
            except (SyntaxError, ValueError, RecursionError):
                continue
            tokens = tokenise(normalised)
            if len(tokens) < MIN_TOKENS:
                continue
            units.append(
                CorpusUnit(
                    unit_id=f"{corpus}:{unit.unit_id}",
                    corpus=corpus,
                    path=unit.path,
                    start_line=unit.start_line,
                    end_line=unit.end_line,
                    unit=unit,
                    normalised=normalised,
                    tokens=tokens,
                )
            )
    return units
