"""The four arms of the context-cost measurement.

Pre-registered in `docs/context-cost.md`. The question is not which
tool compresses better -- a compression ratio is mostly a statement
about the baseline chosen -- but how many bytes each one puts into a
context window to answer the same question, and how much of the true
neighbourhood those bytes contain.

Two things in here are easy to get wrong in a way that still prints a
plausible number, so both are tested:

- **Span accounting.** Two nodes whose line ranges overlap cost one
  read, not two. Counting them twice inflates the arm that names
  overlapping nodes, which is theirs.
- **Claim confirmation.** The answer key is the union of both tools'
  claims, kept only where the source really contains the call. The
  check confirms rather than refutes: a name collision can confirm a
  claim that is not real, so an unconfirmable claim is dropped from
  the key rather than counted against the arm that made it.
"""

from __future__ import annotations

import ast
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

# No test suite in the pinned checkout, so `tests_for` is dropped
# rather than charged as an empty call to either arm.
PATTERNS = ("callers_of", "callees_of")


@dataclass(slots=True, frozen=True)
class GcrNode:
    """One node as their graph reports it."""

    name: str
    qualified_name: str
    path: str
    start_line: int
    end_line: int
    kind: str


def parse_nodes(payload: dict[str, object], root: Path) -> list[GcrNode]:
    """Read their JSON response into nodes, paths made relative."""
    rows = payload.get("results")
    if not isinstance(rows, list):
        return []
    nodes: list[GcrNode] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("file_path", ""))
        try:
            path = str(Path(raw).relative_to(root))
        except ValueError:
            path = raw
        nodes.append(
            GcrNode(
                name=str(row.get("name", "")),
                qualified_name=str(row.get("qualified_name", "")),
                path=path,
                start_line=int(row.get("line_start") or 0),
                end_line=int(row.get("line_end") or 0),
                kind=str(row.get("kind", "")),
            )
        )
    return nodes


def query(root: Path, pattern: str, target: str) -> tuple[str, list[GcrNode]]:
    """Run one of their queries. Returns raw stdout and its nodes."""
    result = subprocess.run(
        ["code-review-graph", "query", "--repo", str(root), pattern, target],
        capture_output=True,
        text=True,
        check=False,
    )
    raw = result.stdout
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw, []
    return raw, parse_nodes(payload, root)


def span_bytes(root: Path, nodes: list[GcrNode]) -> int:
    """Bytes of source an agent reads for these spans, deduplicated.

    Lines claimed by two nodes are read once. Anything else counts
    the same source twice and flatters this project's arm.
    """
    wanted: dict[str, set[int]] = {}
    for node in nodes:
        if node.start_line <= 0 or node.end_line < node.start_line:
            continue
        wanted.setdefault(node.path, set()).update(range(node.start_line, node.end_line + 1))
    total = 0
    for path, lines in wanted.items():
        try:
            source = (root / path).read_text(encoding="utf-8").splitlines(keepends=True)
        except (OSError, UnicodeDecodeError):
            continue
        for number in lines:
            if 1 <= number <= len(source):
                total += len(source[number - 1].encode("utf-8"))
    return total


def _calls_in(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def _function_at(tree: ast.AST, start: int, end: int) -> ast.AST | None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.lineno == start or start <= node.lineno <= end:
            return node
    return None


def confirmed_claims(root: Path, target_name: str, claims: list[GcrNode]) -> list[GcrNode]:
    """Keep the claims whose source really calls ``target_name``.

    Conservative by design: it confirms a claim rather than refuting
    one, so a claim it cannot verify is left out of the key instead
    of being scored as an error against whoever made it.
    """
    kept: list[GcrNode] = []
    cache: dict[str, ast.AST | None] = {}
    for claim in claims:
        if claim.path not in cache:
            try:
                cache[claim.path] = ast.parse((root / claim.path).read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
                cache[claim.path] = None
        tree = cache[claim.path]
        if tree is None:
            continue
        function = _function_at(tree, claim.start_line, claim.end_line)
        if function is not None and target_name in _calls_in(function):
            kept.append(claim)
    return kept


def caller_index(root: Path, files: list[Path]) -> dict[str, set[tuple[str, str]]]:
    """Map a callee name to every function whose body calls it.

    One AST pass over the corpus, owned by neither tool. The union of
    the two tools' own claims was tried first and discarded: where one
    tool returns nothing, the other scores 1.0 against it by
    construction, which is a criterion that cannot fail.

    Exact only where the name is unique in the corpus, which is why
    the sample is restricted to unique names.
    """
    index: dict[str, set[tuple[str, str]]] = {}
    for relative in files:
        try:
            tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for callee in _calls_in(node):
                index.setdefault(callee, set()).add((str(relative), node.name))
    return index
