"""Pool generator output into a blind labelling sheet.

Two strata, and they answer different questions.

The **pooled** stratum is the top slice of each generator's ranking,
unioned across generators. Precision and recall are computed on it.
Its known weakness is that recall is recall *within the pool*: a pair
no generator proposed is invisible, so every arm's recall is an upper
bound. That is the standard pooling caveat and it is reported, not
papered over.

The **probe** stratum is a deterministic random sample of pairs drawn
from the same units without any generator involved. It exists to
measure two things the pooled stratum cannot: the base rate of
similarity in each corpus, and whether the pool missed an obvious
population. Probe pairs are labelled by the same person under the same
blinding and are excluded from precision, because scoring a generator
on pairs it was never asked about measures nothing.

The labeller sees a pair of function bodies and their paths. Not which
generator proposed them, not the rank, not the score, not the stratum.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmarks.similarity.generators import ScoredPair
from benchmarks.similarity.units import CorpusUnit

# Three-valued, matching the packet-precision sheet. A binary
# same/different forces every partial overlap into whichever bucket
# the labeller leans towards, and partial overlap is the population
# a reuse tool actually has to get right.
LABELS = ("same-behaviour", "overlapping", "unrelated")

LABEL_GUIDANCE = """\
same-behaviour -- one could replace the other, or one could call the
                  other, with only mechanical changes. REUSE.
overlapping    -- a real shared core with genuine differences around
                  it; a reviewer would want them factored together.
                  EXTEND or REFACTOR.
unrelated      -- shared idiom, shared framework, shared shape, but
                  no shared job. Reporting this pair wastes the
                  reader's time.
"""


@dataclass(slots=True, frozen=True)
class PooledPair:
    """One candidate pair with its stratum and generator provenance.

    Provenance is carried here so the pool can be audited. It is
    stripped before the sheet is written.
    """

    corpus: str
    left: str
    right: str
    stratum: str
    generators: tuple[str, ...]


def blind_order(pairs: Sequence[PooledPair]) -> list[PooledPair]:
    """Order the sheet by a digest of the pair, carrying no signal."""
    return sorted(
        pairs,
        key=lambda pair: hashlib.sha256(
            f"{pair.corpus}\x00{pair.left}\x00{pair.right}".encode()
        ).hexdigest(),
    )


def probe_pairs(units: list[CorpusUnit], corpus: str, count: int) -> list[PooledPair]:
    """Draw a reproducible random sample, no generator involved."""
    ordered = sorted(
        units,
        key=lambda unit: hashlib.sha256(f"probe\x00{unit.unit_id}".encode()).hexdigest(),
    )
    chosen: list[PooledPair] = []
    for index in range(count):
        left = ordered[(index * 2) % len(ordered)]
        right = ordered[(index * 2 + 1 + index * 7) % len(ordered)]
        if left.unit_id == right.unit_id:
            continue
        low, high = sorted((left.unit_id, right.unit_id))
        chosen.append(PooledPair(corpus, low, high, "probe", ()))
    return chosen


def pool(
    corpus: str,
    generated: dict[str, list[ScoredPair]],
    depth: int,
) -> list[PooledPair]:
    """Union the top ``depth`` pairs from every generator."""
    provenance: dict[tuple[str, str], set[str]] = {}
    for name, pairs in sorted(generated.items()):
        for scored in pairs[:depth]:
            provenance.setdefault(scored.key(), set()).add(name)
    return [
        PooledPair(corpus, left, right, "pooled", tuple(sorted(names)))
        for (left, right), names in provenance.items()
    ]


def build_sheet(
    pairs: Sequence[PooledPair],
    sources: dict[str, CorpusUnit],
) -> dict[str, Any]:
    """Render pairs as a blind sheet: bodies, paths, nothing else."""
    entries = []
    for pair in blind_order(pairs):
        left, right = sources[pair.left], sources[pair.right]
        entries.append(
            {
                "pair_id": pair_id(pair),
                # No corpus name, no stratum, no generators, no score.
                "left": _side(left),
                "right": _side(right),
            }
        )
    return {
        "schema_version": 1,
        "labels": list(LABELS),
        "guidance": LABEL_GUIDANCE,
        "pair_count": len(entries),
        "pairs": entries,
    }


def _side(unit: CorpusUnit) -> dict[str, Any]:
    return {
        "path": unit.path,
        "lines": [unit.start_line, unit.end_line],
        "source": unit.normalised,
    }


def pair_id(pair: PooledPair) -> str:
    """Derive a stable opaque identifier for a pair."""
    digest = hashlib.sha256(f"{pair.corpus}\x00{pair.left}\x00{pair.right}".encode())
    return digest.hexdigest()[:16]


def write_key(pairs: Sequence[PooledPair], path: Path) -> None:
    """Write the provenance key the labeller must not read."""
    payload = [
        {
            "pair_id": pair_id(pair),
            "corpus": pair.corpus,
            "left": pair.left,
            "right": pair.right,
            "stratum": pair.stratum,
            "generators": list(pair.generators),
        }
        for pair in sorted(pairs, key=pair_id)
    ]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
