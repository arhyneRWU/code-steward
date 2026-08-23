"""Choose a relevance floor from a held-out null distribution.

`similar` has a result limit and no score floor, so it returns its
best candidates however weak they are. The reviewer measurement in
`docs/verdict.md` showed what that costs: on a third of cases where
the correct answer was to write the function, a reviewer shown eight
plausible candidates picked one. The tool cannot currently return
nothing, so it cannot be right when nothing is the answer.

**The criterion is fixed here, before any curve is read.** The floor
is the smallest value at which the false-positive rate over the null
distribution falls to or below `TARGET_FALSE_POSITIVE_RATE`. It is
not chosen to maximise anything, and it is not chosen on the frozen
gold set -- doing that would convert a benchmark into a target.

**The null distribution is cross-corpus.** A Home Assistant
integration and an Airflow provider solve unrelated problems, so a
match between them is almost always coincidence. "Almost" is doing
real work: some genuine overlap exists, because retry loops and
dictionary merging look the same everywhere. Those pairs make the
measured false-positive rate an overestimate, which pushes the chosen
floor up rather than down. The bias is toward declining too often,
which is the safer direction for this particular failure.

**The sample is held out by construction.** Both corpora are sliced
in hash order immediately after the gold sample, so no directory here
was ever labelled. Disjointness is asserted by a test rather than
claimed here.

Recall against the frozen gold positives is reported at the chosen
floor. That is a consequence being observed, never an input to the
choice.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.guards import Exclusions
from benchmarks.similarity.corpus import (
    CORPORA,
    CORPORA_BY_NAME,
    corpus_files,
    held_out_files,
)
from benchmarks.similarity.units import CorpusUnit, load_units
from code_steward.similarity import jaccard, rank_against, shingles

# The false-positive rate the floor is chosen to achieve. One in a
# hundred spurious candidates surviving is the budget; the value is a
# judgement, stated here rather than buried in a comparison.
TARGET_FALSE_POSITIVE_RATE = 0.01

# Directories to take beyond each corpus's gold sample.
HELD_OUT_SIZE = {"home-assistant": 60, "airflow": 20}

# Floors to evaluate. Two decimal places is finer than the underlying
# Jaccard resolution warrants and costs nothing to compute.
CANDIDATE_FLOORS = tuple(round(value / 100, 2) for value in range(0, 61))


def _null_scores(
    left: list[CorpusUnit],
    right: list[CorpusUnit],
) -> list[float]:
    """Score every left unit against the whole unrelated right corpus.

    One score per query -- the best match it found, or 0.0 when the
    blocking step returned nothing. Taking the best is deliberate: the
    floor has to survive the strongest spurious match a query
    produces, not the average one.
    """
    prepared = {unit.unit_id: shingles(unit.tokens) for unit in right}
    units = [unit.unit for unit in right]
    for unit, entry in zip(units, right, strict=True):
        unit.unit_id = entry.unit_id
    scores: list[float] = []
    for query in left:
        ranked = rank_against(shingles(query.tokens), units, prepared, limit=1)
        scores.append(ranked[0].score if ranked else 0.0)
    return scores


def false_positive_rate(scores: list[float], floor: float) -> float:
    """Share of null queries still returning something at ``floor``."""
    if not scores:
        raise ValueError("No null scores: the floor would be chosen from nothing.")
    return sum(1 for score in scores if score >= floor) / len(scores)


def choose_floor(scores: list[float]) -> float:
    """Smallest floor meeting the pre-registered error budget."""
    for floor in CANDIDATE_FLOORS:
        if false_positive_rate(scores, floor) <= TARGET_FALSE_POSITIVE_RATE:
            return floor
    raise ValueError(
        "No candidate floor reaches the target false-positive rate. "
        "Widen CANDIDATE_FLOORS rather than relaxing the target."
    )


def gold_recall(
    labels: Path, scored: dict[tuple[str, str], float], floor: float
) -> dict[str, Any]:
    """Report what ``floor`` does to the frozen positives.

    Read-only. This runs after the floor is chosen and cannot change
    it.
    """
    pairs = json.loads(labels.read_text(encoding="utf-8"))["pairs"]
    positives = [row for row in pairs if row["label"] == "same-behaviour"]
    kept = 0
    missing = 0
    for row in positives:
        left, right = row["left"], row["right"]
        key = (left, right) if left < right else (right, left)
        score = scored.get(key)
        if score is None:
            missing += 1
            continue
        if score >= floor:
            kept += 1
    scorable = len(positives) - missing
    return {
        "positives": len(positives),
        "not_rescored": missing,
        "scorable": scorable,
        "kept": kept,
        "recall": round(kept / scorable, 3) if scorable else 0.0,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Choose a relevance floor.")
    parser.add_argument("--checkouts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()

    dropped = Exclusions()
    loaded: dict[str, list[CorpusUnit]] = {}
    for name, size in HELD_OUT_SIZE.items():
        corpus = CORPORA_BY_NAME[name]
        checkout = (args.checkouts / name).resolve()
        files = held_out_files(corpus, checkout, size)
        loaded[name] = load_units(name, checkout, files, dropped)
        print(f"{name}: {len(loaded[name])} held-out units from {len(files)} files", flush=True)

    scores = _null_scores(loaded["home-assistant"], loaded["airflow"])
    scores += _null_scores(loaded["airflow"], loaded["home-assistant"])

    floor = choose_floor(scores)
    curve = [
        {
            "floor": value,
            "false_positive_rate": round(false_positive_rate(scores, value), 4),
        }
        for value in CANDIDATE_FLOORS
        if value <= 0.4
    ]

    # Everything below observes the consequences of a floor that is
    # already fixed. Nothing here can feed back into the choice.
    labels = Path("benchmarks/similarity/reuse_pair_labels.json")
    scored: dict[tuple[str, str], float] = {}
    for corpus in CORPORA:
        checkout = (args.checkouts / corpus.name).resolve()
        gold = load_units(corpus.name, checkout, corpus_files(corpus, checkout), dropped)
        prepared = {unit.unit_id: shingles(unit.tokens) for unit in gold}
        pairs = json.loads(labels.read_text(encoding="utf-8"))["pairs"]
        for row in pairs:
            if row["corpus"] != corpus.name:
                continue
            left, right = row["left"], row["right"]
            first, second = prepared.get(left), prepared.get(right)
            if first is None or second is None:
                continue
            key = (left, right) if left < right else (right, left)
            scored[key] = jaccard(first, second)
        print(f"{corpus.name}: rescored", flush=True)

    payload = {
        "schema_version": 1,
        "target_false_positive_rate": TARGET_FALSE_POSITIVE_RATE,
        "held_out_size": HELD_OUT_SIZE,
        "null_queries": len(scores),
        "null_nonzero": sum(1 for score in scores if score > 0),
        "chosen_floor": floor,
        "curve": curve,
        "gold_recall_at_floor": gold_recall(labels, scored, floor),
        "excluded": dropped.to_dict(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
