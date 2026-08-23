"""Find existing units whose behaviour a new one would duplicate.

This is the arm that won the reuse-similarity benchmark, promoted from
`benchmarks/similarity/` unchanged. It compares five-token windows of
normalised function bodies and reports Jaccard overlap. It has no model
of code, reads no names, and consults no metadata.

It was chosen on evidence rather than on design taste. Measured across
three pinned public repositories and 298 blind-labelled pairs, it
reached macro precision 0.978 and F1 0.571, against 0.744 and 0.431 for
this project's own `retrieval.metadata_similarity`, at 1.8x fewer
bytes. jscpd and a RapidFuzz-over-bodies arm both placed behind it too.
`docs/similarity.md` carries the table, including what the benchmark
cannot see.

**The constants below are measured values, not tuning knobs.** Every
figure published for this arm was produced with exactly these numbers,
and `benchmarks/similarity/generators.py` imports this module rather
than reimplementing it, so the code that was measured and the code that
ships cannot drift apart. Changing any constant here invalidates
`docs/similarity.md` and requires re-running the benchmark, not
adjusting the prose.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .models import CodeUnit

# Five-token windows: long enough that a shared ``for x in y:`` does not
# register, short enough to survive a renamed variable.
SHINGLE_SIZE = 5

# A window occurring in more than this many units is boilerplate -- an
# import block, a logger call, a decorator preamble. Comparing every
# pair that shares one is quadratic work for no signal.
MAX_SHINGLE_DOCUMENT_FREQUENCY = 60

# Below this many shared windows a pair is coincidence.
MIN_SHARED_SHINGLES = 3

# A unit under five lines is too small for reuse to be the right call
# even when two of them are identical.
MIN_LINES = 5

# Below this many normalised tokens there is nothing to compare and
# every pair scores near 1.0 by accident.
MIN_TOKENS = 20

FUNCTION_KINDS = frozenset({"function", "method"})


@dataclass(slots=True, frozen=True)
class SimilarUnit:
    """One existing unit that overlaps a target, and by how much."""

    unit: CodeUnit
    score: float
    shared_shingles: int

    def to_dict(self) -> dict[str, object]:
        return {
            "unit_id": self.unit.unit_id,
            "path": self.unit.path,
            "lines": [self.unit.start_line, self.unit.end_line],
            "signature": self.unit.signature,
            "purpose": self.unit.purpose,
            "score": round(self.score, 3),
            "shared_shingles": self.shared_shingles,
        }


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
    """Re-emit a declaration as canonical source without docstrings.

    ``ast.unparse`` discards comments and formatting. Identifiers are
    deliberately kept: renaming locals would turn this into a
    structural comparator, which is a different tool with different
    failure modes and was not the one measured.
    """
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


def shingles(tokens: tuple[str, ...]) -> frozenset[int]:
    """Hash every five-token window of a normalised body."""
    if len(tokens) < SHINGLE_SIZE:
        return frozenset()
    return frozenset(
        hash(tokens[index : index + SHINGLE_SIZE])
        for index in range(len(tokens) - SHINGLE_SIZE + 1)
    )


def jaccard(left: frozenset[int], right: frozenset[int]) -> float:
    """Overlap of two shingle sets, 0.0 when either is empty."""
    union = len(left | right)
    return len(left & right) / union if union else 0.0


def unit_shingles(project_root: Path, units: Iterable[CodeUnit]) -> dict[str, frozenset[int]]:
    """Build a shingle set for every unit large enough to compare.

    Units too small to be worth reusing, and files that will not parse,
    are simply absent from the result. Callers that need to account for
    what was skipped should compare against the input.
    """
    sources: dict[str, list[str]] = {}
    trees: dict[str, dict[int, ast.AST]] = {}
    built: dict[str, frozenset[int]] = {}

    for unit in units:
        if unit.kind not in FUNCTION_KINDS:
            continue
        if unit.end_line - unit.start_line + 1 < MIN_LINES:
            continue
        if unit.path not in trees:
            try:
                text = (project_root / unit.path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                trees[unit.path] = {}
                sources[unit.path] = []
                continue
            sources[unit.path] = text.splitlines()
            try:
                parsed = ast.parse(text)
            except (SyntaxError, ValueError):
                trees[unit.path] = {}
                continue
            trees[unit.path] = {
                child.lineno: child
                for child in ast.walk(parsed)
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            }
        node = trees[unit.path].get(unit.start_line)
        if node is None:
            continue
        try:
            tokens = tokenise(normalise(node))
        except (SyntaxError, ValueError, RecursionError):
            continue
        if len(tokens) < MIN_TOKENS:
            continue
        built[unit.unit_id] = shingles(tokens)
    return built


def draft_shingles(source: str) -> frozenset[int]:
    """Build a shingle set for code that is not indexed yet.

    The reuse question is most useful before the code exists. An agent
    about to write a function can ask what already resembles it, using
    the same comparison the indexed path uses -- a draft is normalised
    and tokenised exactly like a stored unit, so a draft and its
    eventual indexed self produce the same shingles.

    Raises ``SyntaxError`` if the draft does not parse. That is worth
    surfacing rather than swallowing: a caller that silently receives
    an empty result cannot tell "nothing resembles this" from "your
    snippet was malformed", and those need different responses.
    """
    tree = ast.parse(source)
    nodes = [
        node for node in tree.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    if not nodes:
        return frozenset()
    tokens: tuple[str, ...] = ()
    for node in nodes:
        tokens += tokenise(normalise(node))
    return shingles(tokens) if len(tokens) >= MIN_TOKENS else frozenset()


def rank_against(
    needle: frozenset[int],
    units: list[CodeUnit],
    prepared: dict[str, frozenset[int]],
    limit: int = 8,
    exclude: str = "",
) -> list[SimilarUnit]:
    """Rank indexed units against any shingle set, drafts included."""
    if not needle:
        return []

    by_id = {unit.unit_id: unit for unit in units}
    ranked: list[SimilarUnit] = []
    for unit_id, candidate in prepared.items():
        if unit_id == exclude:
            continue
        shared = len(needle & candidate)
        if shared < MIN_SHARED_SHINGLES:
            continue
        unit = by_id.get(unit_id)
        if unit is None:
            continue
        ranked.append(SimilarUnit(unit, jaccard(needle, candidate), shared))

    ranked.sort(key=lambda row: (-row.score, row.unit.path, row.unit.start_line))
    return ranked[:limit]


def rank_similar_units(
    target: str,
    units: list[CodeUnit],
    prepared: dict[str, frozenset[int]],
    limit: int = 8,
) -> list[SimilarUnit]:
    """Rank existing units by shingle overlap with one target unit.

    Returns an empty list when the target is absent or too small to
    compare, which is the correct answer rather than an error: most
    functions in most repositories have no reuse candidate at all. On
    the benchmark's random probe stratum -- 45 pairs drawn without any
    generator -- the right answer was "nothing" 45 times out of 45.
    """
    return rank_against(prepared.get(target, frozenset()), units, prepared, limit, target)


def rank_all_pairs(
    prepared: dict[str, frozenset[int]],
    limit: int,
) -> list[tuple[str, str, float]]:
    """Rank every overlapping pair in a repository, best first.

    Uses an inverted index so only pairs sharing a rare window are
    scored. Windows held by more than
    ``MAX_SHINGLE_DOCUMENT_FREQUENCY`` units are skipped as
    boilerplate: they generate quadratic work and carry no signal.
    """
    postings: dict[int, list[str]] = defaultdict(list)
    for unit_id, values in prepared.items():
        for value in values:
            postings[value].append(unit_id)

    shared: dict[tuple[str, str], int] = defaultdict(int)
    for holders in postings.values():
        if len(holders) < 2 or len(holders) > MAX_SHINGLE_DOCUMENT_FREQUENCY:
            continue
        for index, left in enumerate(holders):
            for right in holders[index + 1 :]:
                shared[(left, right) if left < right else (right, left)] += 1

    scored: list[tuple[str, str, float]] = []
    for (left, right), count in shared.items():
        if count < MIN_SHARED_SHINGLES:
            continue
        value = jaccard(prepared[left], prepared[right])
        if value:
            scored.append((left, right, value))
    scored.sort(key=lambda row: (-row[2], row[0], row[1]))
    return scored[:limit]
