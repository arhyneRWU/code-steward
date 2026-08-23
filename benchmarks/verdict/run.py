"""Score whether reuse evidence reaches the reviewer, and at what cost.

Three arms over the same held-out cases:

- `packet` -- the production retrieval path, task text only. The
  control, and what a reviewer sees today.
- `packet-reuse` -- the same packet with near-duplicate evidence
  attached to each candidate.
- `draft-similar` -- the held-out function's own body compared
  against the repository. This is the pre-implementation path, and it
  is **not** a like-for-like comparison with the other two: it is
  handed the code, while they are handed a sentence. It is scored
  anyway because it is the path the product actually recommends.

On positive cases the question is whether the labelled duplicate is
surfaced. On negative cases the question is what an arm surfaces when
the right answer is nothing -- split into evidence the labels call
`unrelated`, which is a real false positive, and evidence nobody
labelled, which is a hole in the pool rather than a verdict.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass, field
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import Any

from benchmarks.guards import Exclusions
from benchmarks.similarity.corpus import CORPORA, corpus_files
from benchmarks.similarity.units import CorpusUnit, load_units
from benchmarks.verdict.cases import UNDOCUMENTED, VerdictCase, build_cases, load_pairs
from code_steward.models import CodeUnit
from code_steward.packet import build_packet
from code_steward.retrieval import retrieve_units
from code_steward.similarity import rank_against, rank_similar_units, shingles

# The packet limit the CLI ships with.
PACKET_LIMIT = 8

# The duplicate limit the packet ships with.
DUPLICATE_LIMIT = 3


@dataclass(slots=True)
class ArmResult:
    """One arm's outcome across every case it could score."""

    arm: str
    positives: int = 0
    positives_surfaced: int = 0
    negatives: int = 0
    negatives_false_positive: int = 0
    negatives_unlabelled: int = 0
    bytes_total: int = 0
    cases_scored: int = 0

    @property
    def surfaced_rate(self) -> float:
        return self.positives_surfaced / self.positives if self.positives else 0.0

    @property
    def false_positive_rate(self) -> float:
        return self.negatives_false_positive / self.negatives if self.negatives else 0.0

    @property
    def mean_bytes(self) -> float:
        return self.bytes_total / self.cases_scored if self.cases_scored else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "cases_scored": self.cases_scored,
            "positives": self.positives,
            "positives_surfaced": self.positives_surfaced,
            "surfaced_rate": round(self.surfaced_rate, 3),
            "negatives": self.negatives,
            "negatives_false_positive": self.negatives_false_positive,
            "false_positive_rate": round(self.false_positive_rate, 3),
            "negatives_unlabelled_evidence": self.negatives_unlabelled,
            "mean_bytes": round(self.mean_bytes, 1),
        }


@dataclass(slots=True)
class Excluded:
    """Cases no arm could score, counted rather than dropped."""

    reasons: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def record(self, reason: str) -> None:
        self.reasons[reason] += 1

    @property
    def total(self) -> int:
        return sum(self.reasons.values())

    def to_dict(self) -> dict[str, Any]:
        return {"total": self.total, "by_reason": dict(sorted(self.reasons.items()))}


def _packet_bytes(packet: dict[str, Any]) -> int:
    return len(json.dumps(packet, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _score_case(
    case: VerdictCase,
    units: list[CodeUnit],
    by_id: dict[str, CorpusUnit],
    prepared: dict[str, frozenset[int]],
    unrelated_to_target: set[str],
    arms: dict[str, ArmResult],
) -> None:
    """Score one held-out case across all three arms.

    ``units`` carries the corpus-prefixed unit IDs the labels use, so
    everything downstream compares like with like. The held-out
    function is removed from all three arms: it has not been written
    yet, and leaving it in would let every arm find the answer by
    finding the question.
    """
    target = by_id[case.target]
    visible = [unit for unit in units if unit.unit_id != case.target]
    visible_shingles = {key: value for key, value in prepared.items() if key != case.target}

    results = retrieve_units(visible, target.unit.purpose, PACKET_LIMIT)
    candidate_ids = {result.unit.unit_id for result in results}

    # Arm 1: packet only. What a reviewer sees today.
    packet = build_packet(target.unit.purpose, results, [])
    _record(arms["packet"], case, candidate_ids, unrelated_to_target, _packet_bytes(packet))

    # Arm 2: packet plus near-duplicate evidence per candidate.
    duplicates = {}
    reuse_ids = set(candidate_ids)
    for result in results:
        near = rank_similar_units(
            result.unit.unit_id, visible, visible_shingles, limit=DUPLICATE_LIMIT
        )
        if near:
            duplicates[result.unit.unit_id] = near
            reuse_ids.update(row.unit.unit_id for row in near)
    reuse_packet = build_packet(target.unit.purpose, results, [], duplicates=duplicates)
    _record(
        arms["packet-reuse"], case, reuse_ids, unrelated_to_target, _packet_bytes(reuse_packet)
    )

    # Arm 3: the held-out body compared directly. Not like-for-like --
    # this arm is handed the code, the other two a sentence.
    matches = rank_against(
        prepared.get(case.target, frozenset()), visible, visible_shingles, PACKET_LIMIT
    )
    draft_ids = {row.unit.unit_id for row in matches}
    draft_bytes = sum(
        len(json.dumps(row.to_dict(), separators=(",", ":")).encode("utf-8")) for row in matches
    )
    _record(arms["draft-similar"], case, draft_ids, unrelated_to_target, draft_bytes)


def _record(
    arm: ArmResult,
    case: VerdictCase,
    surfaced: set[str],
    unrelated_to_target: set[str],
    byte_cost: int,
) -> None:
    arm.cases_scored += 1
    arm.bytes_total += byte_cost
    if case.kind == "reuse-available":
        arm.positives += 1
        if case.expected in surfaced:
            arm.positives_surfaced += 1
        return
    arm.negatives += 1
    # A unit the labels call unrelated to this target is a real false
    # positive. Anything else is unlabelled, which is a hole in the
    # pool rather than a verdict, and is counted separately.
    if surfaced & unrelated_to_target:
        arm.negatives_false_positive += 1
    elif surfaced:
        arm.negatives_unlabelled += 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure whether reuse evidence arrives.")
    parser.add_argument("--checkouts", type=Path, required=True)
    parser.add_argument(
        "--labels",
        type=Path,
        default=Path("benchmarks/similarity/reuse_pair_labels.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    pairs = load_pairs(args.labels.resolve())
    cases = build_cases(pairs)

    unrelated: dict[str, set[str]] = defaultdict(set)
    for row in pairs:
        if row["label"] == "unrelated":
            unrelated[row["left"]].add(row["right"])
            unrelated[row["right"]].add(row["left"])

    arms = {name: ArmResult(name) for name in ("packet", "packet-reuse", "draft-similar")}
    excluded = Excluded()

    for corpus in CORPORA:
        checkout = (args.checkouts / corpus.name).resolve()
        corpus_units = load_units(
            corpus.name, checkout, corpus_files(corpus, checkout), Exclusions()
        )
        by_id = {unit.unit_id: unit for unit in corpus_units}
        prepared = {unit.unit_id: shingles(unit.tokens) for unit in corpus_units}
        # Re-key the indexed units onto the corpus-prefixed IDs the
        # labels use. Only the ID changes; nothing the ranker scores
        # is touched.
        units = [dataclass_replace(entry.unit, unit_id=entry.unit_id) for entry in corpus_units]

        for case in cases:
            if case.corpus != corpus.name:
                continue
            target = by_id.get(case.target)
            if target is None:
                excluded.record("target-not-in-corpus")
                continue
            if case.expected and case.expected not in by_id:
                excluded.record("expected-not-in-corpus")
                continue
            purpose = target.unit.purpose.strip()
            if not purpose:
                excluded.record("empty-purpose")
                continue
            fallback = target.unit.name.replace("_", " ").strip().lower()
            if purpose.lower() == fallback:
                excluded.record(UNDOCUMENTED)
                continue
            _score_case(case, units, by_id, prepared, unrelated[case.target], arms)
        print(f"{corpus.name}: done", flush=True)

    payload = {
        "schema_version": 1,
        "packet_limit": PACKET_LIMIT,
        "duplicate_limit": DUPLICATE_LIMIT,
        "cases_built": len(cases),
        "excluded": excluded.to_dict(),
        "arms": [arm.to_dict() for arm in arms.values()],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
