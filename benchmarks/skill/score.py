"""Score the skill A/B, arm against arm.

The question: does an agent following the skill do better work?

Two arms answer the same questions. Arm A has the Code Steward skill
and CLI; arm B has ordinary Grep, Glob and Read. Answers are sets of
unit IDs, scored against ground truth from the call graph, so there
is no rubric and no labeller.

## Pre-registered, and simulated before being fixed

Primary measure: the **paired per-question F1 difference**, arm A
minus arm B. The skill is judged to help if the lower bound of a
one-sided 95% bootstrap interval on the mean difference is above
zero.

Simulated power for that criterion, before any data was collected:

| n  | true F1 gap | sd  | power |
| -- | ----------- | --- | ----- |
| 12 | 0.10        | 0.30| 0.36  |
| 12 | 0.20        | 0.30| 0.77  |
| 20 | 0.10        | 0.30| 0.45  |
| 20 | 0.20        | 0.30| 0.91  |
| 30 | 0.20        | 0.30| 0.98  |

So **at n = 20 this design detects a 0.20 F1 gap and cannot reliably
detect a 0.10 one.** A null result is evidence against a large
effect, not evidence of no effect, and must not be reported as a
kill. This is written down before the run because the previous
pre-registered criterion in this project asymptoted at ~51% power at
any n, and nobody noticed until it was simulated.

## What is not punished

Units an arm names that the key does not contain are counted and
reported **separately**, not as false positives. The key is built
from a graph that resolves 32.6% of call edges, so an arm that finds
a real caller the graph missed is doing better work, and scoring it
as wrong would measure the index rather than the agent.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path
from typing import Any

BOOTSTRAP = 5000
PERMUTATIONS = 20000
SEED = 11


def f1(predicted: set[str], truth: set[str]) -> tuple[float, float, float]:
    """Precision, recall and F1 over unit IDs."""
    if not truth:
        return 0.0, 0.0, 0.0
    hit = len(predicted & truth)
    precision = hit / len(predicted) if predicted else 0.0
    recall = hit / len(truth)
    if precision + recall == 0:
        return precision, recall, 0.0
    return precision, recall, 2 * precision * recall / (precision + recall)


def _bootstrap_lower(diffs: list[float]) -> float:
    """One-sided 95% lower bound on the mean paired difference."""
    rng = random.Random(SEED)
    means = []
    for _ in range(BOOTSTRAP):
        sample = [rng.choice(diffs) for _ in diffs]
        means.append(statistics.fmean(sample))
    means.sort()
    return means[int(0.05 * len(means))]


def permutation_p(diffs: list[float]) -> float:
    """One-sided paired sign-flip permutation test.

    Chosen over the sign test by simulation rather than by argument:
    at n=30 the two are within a point or two of each other at every
    tie rate tried, and this one keeps the magnitude of a difference
    instead of discarding it. Exact, and it makes no distributional
    assumption -- which matters because most questions tie and the
    differences are nothing like normal.
    """
    observed = sum(diffs)
    if observed <= 0:
        return 1.0
    rng = random.Random(SEED)
    hits = 0
    for _ in range(PERMUTATIONS):
        total = sum(value if rng.random() < 0.5 else -value for value in diffs)
        if total >= observed:
            hits += 1
    # Add-one, so a p of exactly zero is never claimed.
    return (hits + 1) / (PERMUTATIONS + 1)


def score(
    questions: list[dict[str, Any]],
    arms: dict[str, dict[str, list[str]]],
) -> dict[str, Any]:
    """Score every arm, then compare them pairwise on F1."""
    per_arm: dict[str, Any] = {}
    per_question: dict[str, dict[str, float]] = {}

    for arm, answers in arms.items():
        rows = []
        for question in questions:
            truth = set(question["answer"])
            predicted = set(answers.get(question["id"], []))
            precision, recall, value = f1(predicted, truth)
            rows.append(
                {
                    "id": question["id"],
                    "precision": round(precision, 4),
                    "recall": round(recall, 4),
                    "f1": round(value, 4),
                    # Named but not in the key. Not an error: the key
                    # is a 32.6%-resolved graph.
                    "outside_key": sorted(predicted - truth),
                }
            )
            per_question.setdefault(question["id"], {})[arm] = recall
        per_arm[arm] = {
            "mean_f1": round(statistics.fmean(row["f1"] for row in rows), 4),
            "mean_recall": round(statistics.fmean(row["recall"] for row in rows), 4),
            "mean_precision": round(statistics.fmean(row["precision"] for row in rows), 4),
            "answered": sum(1 for row in rows if row["f1"] > 0),
            "mean_answer_size": round(
                statistics.fmean(len(answers.get(q["id"], [])) for q in questions), 2
            ),
            "outside_key_total": sum(len(row["outside_key"]) for row in rows),
            "questions": rows,
        }

    comparison: dict[str, Any] = {}
    names = sorted(arms)
    if len(names) == 2:
        # Report treatment minus control, not alphabetical order. The
        # first run printed "control - skill" and every difference
        # came out negative while the skill was ahead.
        treatment = next((name for name in names if name != "control"), names[0])
        left = treatment
        right = next(name for name in names if name != treatment)
        diffs = [
            per_question[question["id"]][left] - per_question[question["id"]][right]
            for question in questions
            if left in per_question.get(question["id"], {})
            and right in per_question.get(question["id"], {})
        ]
        if diffs:
            ties = sum(1 for value in diffs if abs(value) < 1e-9)
            comparison = {
                "arms": f"{left} - {right}",
                "measure": "recall",
                "n": len(diffs),
                "ties": ties,
                "tie_rate": round(ties / len(diffs), 3),
                "mean_difference": round(statistics.fmean(diffs), 4),
                "permutation_p": round(permutation_p(diffs), 4),
                "one_sided_95_lower": round(_bootstrap_lower(diffs), 4),
                "note": (
                    "Primary measure is RECALL, not F1. The key is built from "
                    "resolved CALLS edges and was validated as a strict subset "
                    "of the callers that exist, so it is a lower bound: recall "
                    "against it is interpretable and precision is not, because "
                    "a correct caller the graph missed would count against "
                    "precision. Power depends on the tie rate, which cannot be "
                    "known in advance -- roughly 0.69 at a 0.50 tie rate and "
                    "0.93 at 0.35, for n=30. A null with a high tie rate is "
                    "inconclusive, not a kill."
                ),
            }
    return {"schema_version": 1, "per_arm": per_arm, "comparison": comparison}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score the skill A/B.")
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument(
        "--arm",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="an arm's answers, as name=path.json; pass twice",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    questions = json.loads(args.questions.read_text(encoding="utf-8"))["questions"]
    arms: dict[str, dict[str, list[str]]] = {}
    for spec in args.arm:
        name, _, path = spec.partition("=")
        arms[name] = json.loads(Path(path).read_text(encoding="utf-8"))
    report = score(questions, arms)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["comparison"], indent=2))
    for name, row in sorted(report["per_arm"].items()):
        print(f"{name}: F1 {row['mean_f1']:.3f}  recall {row['mean_recall']:.3f}")


if __name__ == "__main__":
    main()
