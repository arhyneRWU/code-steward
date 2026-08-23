"""Load corpus units and normalise their bodies for comparison.

The reuse question is asked about function-shaped things, so classes
and modules are not candidates. A unit also has to be big enough that
reusing it would save anyone anything: a two-line property is
duplicated all over every codebase and no reviewer would file that as
a reuse finding.

Normalisation, tokenisation, and the size floors all come from
``code_steward.similarity``. The benchmark deliberately does not own
its own copy: the arm that won this benchmark now ships, and the only
way to guarantee that the measured code and the shipped code stay the
same code is for one to import the other.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from benchmarks.guards import Exclusions
from code_steward.indexer import index_python_file
from code_steward.models import CodeUnit
from code_steward.similarity import (
    FUNCTION_KINDS,
    MIN_LINES,
    MIN_TOKENS,
    _declarations_by_start_line,
    normalise,
    tokenise,
)


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


def _declarations(tree: ast.AST) -> dict[int, ast.AST]:
    """Look declarations up the way the shipped comparison does."""
    return _declarations_by_start_line(tree)


def load_units(
    corpus: str,
    checkout: Path,
    files: list[Path],
    exclusions: Exclusions,
) -> list[CorpusUnit]:
    """Index a corpus sample and keep the units worth comparing.

    Every skip is recorded rather than swallowed, and ``exclusions``
    is **required** for that reason. It used to default to a fresh
    object, so a caller that passed nothing got the counts built and
    then discarded -- which is what all nine callers did. A corpus
    loader that
    quietly drops what it could not parse reports a smaller and
    cleaner population than the one the pins describe.
    """
    dropped = exclusions
    units: list[CorpusUnit] = []
    for path in files:
        try:
            indexed, _ = index_python_file(checkout, path)
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError) as error:
            dropped.record(f"unparseable-file:{type(error).__name__}", path.as_posix())
            continue
        declarations = _declarations(tree)
        for unit in indexed:
            if unit.kind not in FUNCTION_KINDS:
                dropped.record("not-a-function", unit.unit_id)
                continue
            if unit.end_line - unit.start_line + 1 < MIN_LINES:
                dropped.record("below-min-lines", unit.unit_id)
                continue
            node = declarations.get(unit.start_line)
            if node is None:
                dropped.record("no-matching-declaration", unit.unit_id)
                continue
            try:
                normalised = normalise(node)
            except (SyntaxError, ValueError, RecursionError) as error:
                dropped.record(f"unnormalisable:{type(error).__name__}", unit.unit_id)
                continue
            tokens = tokenise(normalised)
            if len(tokens) < MIN_TOKENS:
                dropped.record("below-min-tokens", unit.unit_id)
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
