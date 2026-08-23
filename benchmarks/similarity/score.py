"""Score every reuse-similarity arm against the blind labels.

Four arms on one label file. Three of them generated the pool, so at
the pool depth every pair they return is labelled and their precision
is exact. The fourth -- RapidFuzz over normalised bodies -- was not a
generator, so its ranking reaches pairs nobody judged. Those are
counted and reported, never dropped, and its precision is published as
a bracket: pessimistic treats every unlabelled pair as noise,
optimistic treats every one as a hit. The truth is inside.

Recall is recall within the pool. A pair no generator proposed is
invisible here, so every recall figure is an upper bound. The probe
stratum bounds how badly: it is a generator-free random sample from
the same units, and its positive rate is the base rate this pool sits
above.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from benchmarks.guards import Exclusions
from benchmarks.similarity.corpus import CORPORA, corpus_files
from benchmarks.similarity.generators import (
    ScoredPair,
    jscpd_pairs,
    metadata_pairs,
    shingle_pairs,
)
from benchmarks.similarity.units import CorpusUnit, load_units

POSITIVE_LABELS = frozenset({"same-behaviour", "overlapping"})

# The depth the pool was built at. Scoring the pool generators at any
# greater depth would reach pairs nobody labelled and turn an exact
# precision into a bracketed one for no gain.
SCORE_DEPTH = 30


@dataclass(slots=True)
class ArmScore:
    """One arm's result on one corpus, with what it could not score."""

    arm: str
    corpus: str
    returned: int = 0
    labelled: int = 0
    unlabelled: int = 0
    positives: int = 0
    pool_positives: int = 0
    bytes_returned: int = 0

    @property
    def precision(self) -> float:
        return self.positives / self.labelled if self.labelled else 0.0

    @property
    def precision_pessimistic(self) -> float:
        return self.positives / self.returned if self.returned else 0.0

    @property
    def precision_optimistic(self) -> float:
        if not self.returned:
            return 0.0
        return (self.positives + self.unlabelled) / self.returned

    @property
    def recall(self) -> float:
        return self.positives / self.pool_positives if self.pool_positives else 0.0

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "corpus": self.corpus,
            "returned": self.returned,
            "labelled": self.labelled,
            "unlabelled": self.unlabelled,
            "positives": self.positives,
            "pool_positives": self.pool_positives,
            "bytes_returned": self.bytes_returned,
            "precision": round(self.precision, 3),
            "precision_pessimistic": round(self.precision_pessimistic, 3),
            "precision_optimistic": round(self.precision_optimistic, 3),
            "recall_in_pool": round(self.recall, 3),
            "f1": round(self.f1, 3),
        }


@dataclass(slots=True)
class Labels:
    """The committed blind labels, indexed for lookup."""

    by_pair: dict[tuple[str, str, str], str] = field(default_factory=dict)
    pooled_positives: dict[str, int] = field(default_factory=dict)
    probe_positives: dict[str, tuple[int, int]] = field(default_factory=dict)

    def label(self, corpus: str, left: str, right: str) -> str | None:
        low, high = (left, right) if left < right else (right, left)
        return self.by_pair.get((corpus, low, high))


def load_labels(path: Path) -> Labels:
    """Read the label file and reject a corrupted or conflicted one."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    labels = Labels()
    probe: dict[str, list[str]] = {}
    for row in payload["pairs"]:
        left, right = row["left"], row["right"]
        low, high = (left, right) if left < right else (right, left)
        key = (row["corpus"], low, high)
        existing = labels.by_pair.get(key)
        if existing is not None and existing != row["label"]:
            raise ValueError(f"Pair {row['pair_id']} carries conflicting labels")
        labels.by_pair[key] = row["label"]
        if row["stratum"] == "pooled":
            if row["label"] in POSITIVE_LABELS:
                labels.pooled_positives[row["corpus"]] = (
                    labels.pooled_positives.get(row["corpus"], 0) + 1
                )
        else:
            probe.setdefault(row["corpus"], []).append(row["label"])
    labels.probe_positives = {
        corpus: (sum(1 for value in rows if value in POSITIVE_LABELS), len(rows))
        for corpus, rows in probe.items()
    }
    return labels


def _normalised_similarity(left: CorpusUnit, right: CorpusUnit) -> float:
    return fuzz.token_set_ratio(left.normalised, right.normalised) / 100.0


def body_fuzz_pairs(units: list[CorpusUnit], top_k: int) -> list[ScoredPair]:
    """Rank pairs by RapidFuzz over whole normalised bodies.

    This is the arm Code Steward would most plausibly ship next: the
    same matcher the retrieval pipeline already depends on, pointed at
    bodies instead of metadata. It was not a pool generator, so its
    output reaches unlabelled pairs and is scored as a bracket.
    """
    scored: list[ScoredPair] = []
    for index, left in enumerate(units):
        for right in units[index + 1 :]:
            value = _normalised_similarity(left, right)
            if value < 0.85:
                continue
            low, high = sorted((left.unit_id, right.unit_id))
            scored.append(ScoredPair(low, high, value))
    scored.sort(key=lambda pair: (-pair.score, pair.left, pair.right))
    return scored[:top_k]


def score_arm(
    arm: str,
    corpus: str,
    pairs: Iterable[ScoredPair],
    labels: Labels,
    sources: dict[str, CorpusUnit],
) -> ArmScore:
    """Score one arm's ranking, counting what it returned unlabelled."""
    result = ArmScore(arm=arm, corpus=corpus)
    result.pool_positives = labels.pooled_positives.get(corpus, 0)
    for pair in pairs:
        result.returned += 1
        result.bytes_returned += len(sources[pair.left].normalised.encode("utf-8"))
        result.bytes_returned += len(sources[pair.right].normalised.encode("utf-8"))
        label = labels.label(corpus, pair.left, pair.right)
        if label is None:
            result.unlabelled += 1
            continue
        result.labelled += 1
        if label in POSITIVE_LABELS:
            result.positives += 1
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score reuse-similarity arms.")
    parser.add_argument("--checkouts", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument(
        "--labels",
        type=Path,
        default=Path("benchmarks/similarity/reuse_pair_labels.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    labels = load_labels(args.labels.resolve())
    scores: list[ArmScore] = []

    from benchmarks.similarity.corpus import corpus_roots
    from benchmarks.similarity.generators import run_jscpd

    dropped = Exclusions()
    for corpus in CORPORA:
        checkout = (args.checkouts / corpus.name).resolve()
        units = load_units(corpus.name, checkout, corpus_files(corpus, checkout), dropped)
        sources = {unit.unit_id: unit for unit in units}
        report = run_jscpd(
            checkout,
            [root.relative_to(checkout) for root in corpus_roots(corpus, checkout)],
            args.work.resolve() / "jscpd" / corpus.name,
        )
        arms = {
            "token-shingle": shingle_pairs(units, SCORE_DEPTH),
            "jscpd": jscpd_pairs(report, checkout, units)[:SCORE_DEPTH],
            "metadata-similarity": metadata_pairs(units, SCORE_DEPTH),
            "body-rapidfuzz": body_fuzz_pairs(units, SCORE_DEPTH),
        }
        for arm, pairs in sorted(arms.items()):
            scores.append(score_arm(arm, corpus.name, pairs, labels, sources))
            print(f"{corpus.name}/{arm}: {scores[-1].to_dict()}")

    payload = {
        "schema_version": 1,
        "score_depth": SCORE_DEPTH,
        "probe_base_rate": {
            corpus: {"positive": positive, "total": total}
            for corpus, (positive, total) in sorted(labels.probe_positives.items())
        },
        "scores": [score.to_dict() for score in scores],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"-> {args.output}")


if __name__ == "__main__":
    main()
