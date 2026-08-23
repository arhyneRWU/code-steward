"""Independent candidate generators for the reuse-similarity pool.

Three generators, chosen because they disagree. Token shingles see
lexical overlap and nothing else. ``metadata_similarity`` sees names,
purposes, and signatures and never reads a body. jscpd sees
copy-paste spans and is blind to two functions that do the same thing
in different words. Pooling arms that fail differently is the only way
the labelled set contains pairs no single arm would have proposed --
and without those, every arm is scored on its own home ground.

Each generator returns scored pairs. The scores exist to rank a
generator's own output for pooling and are dropped before labelling:
nothing about which arm proposed a pair, or how confidently, reaches
the labeller.
"""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz

from benchmarks.similarity.units import CorpusUnit

# Five-token shingles: long enough that a shared ``for x in y:`` does
# not register, short enough to survive a renamed variable.
SHINGLE_SIZE = 5

# A shingle occurring in more than this many units is boilerplate --
# an import block, a logger call, a decorator preamble. Comparing
# every pair that shares one is quadratic work for no signal.
MAX_SHINGLE_DOCUMENT_FREQUENCY = 60

# Two units must share at least this many distinct shingles before
# their Jaccard score is worth computing.
MIN_SHARED_SHINGLES = 3


@dataclass(slots=True, frozen=True)
class ScoredPair:
    """One candidate pair as a single generator scored it."""

    left: str
    right: str
    score: float

    def key(self) -> tuple[str, str]:
        return (self.left, self.right) if self.left < self.right else (self.right, self.left)


def _shingles(unit: CorpusUnit) -> frozenset[int]:
    tokens = unit.tokens
    if len(tokens) < SHINGLE_SIZE:
        return frozenset()
    return frozenset(
        hash(tokens[index : index + SHINGLE_SIZE])
        for index in range(len(tokens) - SHINGLE_SIZE + 1)
    )


def shingle_pairs(units: list[CorpusUnit], top_k: int) -> list[ScoredPair]:
    """Rank pairs by Jaccard overlap of their five-token shingles.

    This is the naive control. It has no model of code, no notion of
    a signature, and no access to a name -- if it wins, the finding is
    that the sophisticated arms bought nothing.
    """
    sets = {unit.unit_id: _shingles(unit) for unit in units}
    postings: dict[int, list[str]] = defaultdict(list)
    for unit_id, shingles in sets.items():
        for shingle in shingles:
            postings[shingle].append(unit_id)

    shared: dict[tuple[str, str], int] = defaultdict(int)
    for holders in postings.values():
        if len(holders) < 2 or len(holders) > MAX_SHINGLE_DOCUMENT_FREQUENCY:
            continue
        for index, left in enumerate(holders):
            for right in holders[index + 1 :]:
                shared[(left, right) if left < right else (right, left)] += 1

    scored: list[ScoredPair] = []
    for (left, right), count in shared.items():
        if count < MIN_SHARED_SHINGLES:
            continue
        union = len(sets[left] | sets[right])
        if not union:
            continue
        scored.append(ScoredPair(left, right, len(sets[left] & sets[right]) / union))
    scored.sort(key=lambda pair: (-pair.score, pair.left, pair.right))
    return scored[:top_k]


def _metadata_text(unit: CorpusUnit) -> str:
    values = [unit.unit.name, unit.unit.qualname, unit.unit.purpose, *unit.unit.concepts]
    return " ".join(value for value in values if value)


def metadata_pairs(units: list[CorpusUnit], top_k: int) -> list[ScoredPair]:
    """Rank pairs by ``retrieval.metadata_similarity`` as it ships.

    Reimplemented here over batched RapidFuzz rather than called in a
    loop. The arithmetic is the production function's, weight for
    weight; a test pins the two together so this cannot drift into a
    flattering variant of the thing under evaluation.
    """
    texts = [_metadata_text(unit) for unit in units]
    signatures = [unit.unit.signature for unit in units]
    best: dict[tuple[str, str], float] = {}
    for index, unit in enumerate(units):
        semantic = fuzz.token_set_ratio
        for other in range(index + 1, len(units)):
            score = (
                semantic(texts[index], texts[other]) / 100.0 * 0.85
                + semantic(signatures[index], signatures[other]) / 100.0 * 0.15
            )
            if score < 0.7:
                continue
            other_unit = units[other]
            key = (
                (unit.unit_id, other_unit.unit_id)
                if unit.unit_id < other_unit.unit_id
                else (other_unit.unit_id, unit.unit_id)
            )
            best[key] = score
    scored = [ScoredPair(left, right, score) for (left, right), score in best.items()]
    scored.sort(key=lambda pair: (-pair.score, pair.left, pair.right))
    return scored[:top_k]


def _enclosing(units_by_path: dict[str, list[CorpusUnit]], path: str, line: int) -> str | None:
    best: CorpusUnit | None = None
    for unit in units_by_path.get(path, ()):
        if unit.start_line <= line <= unit.end_line and (
            best is None or unit.line_count < best.line_count
        ):
            best = unit
    return None if best is None else best.unit_id


def run_jscpd(checkout: Path, roots: Iterable[Path], report_dir: Path) -> Path:
    """Run jscpd over a corpus sample and return its JSON report."""
    report_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "npx",
        "--yes",
        "jscpd@4",
        "--min-tokens",
        "50",
        "--reporters",
        "json",
        "--format",
        "python",
        "--silent",
        "--output",
        str(report_dir),
        *[str(root) for root in roots],
    ]
    subprocess.run(command, check=True, cwd=checkout, capture_output=True)
    return report_dir / "jscpd-report.json"


def jscpd_pairs(report: Path, checkout: Path, units: list[CorpusUnit]) -> list[ScoredPair]:
    """Map jscpd clone spans onto the units that contain them.

    A clone jscpd reports across two files becomes a pair only when
    both ends sit inside a candidate unit. Spans covering a module
    header or a block of constants are dropped: they are real
    duplication and not a reuse decision about a function.
    """
    by_path: dict[str, list[CorpusUnit]] = defaultdict(list)
    for unit in units:
        by_path[unit.path].append(unit)

    payload = json.loads(report.read_text(encoding="utf-8"))
    scored: dict[tuple[str, str], float] = {}
    for clone in payload.get("duplicates", []):
        first, second = clone["firstFile"], clone["secondFile"]
        left = _enclosing(by_path, _relative(first["name"], checkout), first["start"])
        right = _enclosing(by_path, _relative(second["name"], checkout), second["start"])
        if left is None or right is None or left == right:
            continue
        key = (left, right) if left < right else (right, left)
        # Longer clones are stronger evidence; keep the longest.
        scored[key] = max(scored.get(key, 0.0), float(clone.get("lines", 0)))
    pairs = [ScoredPair(left, right, score) for (left, right), score in scored.items()]
    pairs.sort(key=lambda pair: (-pair.score, pair.left, pair.right))
    return pairs


def _relative(name: str, checkout: Path) -> str:
    path = Path(name)
    if path.is_absolute():
        try:
            return path.relative_to(checkout).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix()
