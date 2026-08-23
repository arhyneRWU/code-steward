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
            per_question.setdefault(question["id"], {})[arm] = value
        per_arm[arm] = {
            "mean_f1": round(statistics.fmean(row["f1"] for row in rows), 4),
            "mean_recall": round(statistics.fmean(row["recall"] for row in rows), 4),
            "mean_precision": round(statistics.fmean(row["precision"] for row in rows), 4),
            "answered": sum(1 for row in rows if row["f1"] > 0),
            "outside_key_total": sum(len(row["outside_key"]) for row in rows),
            "questions": rows,
        }

    comparison: dict[str, Any] = {}
    names = sorted(arms)
    if len(names) == 2:
        left, right = names
        diffs = [
            per_question[question["id"]][left] - per_question[question["id"]][right]
            for question in questions
            if left in per_question.get(question["id"], {})
            and right in per_question.get(question["id"], {})
        ]
        if diffs:
            lower = _bootstrap_lower(diffs)
            comparison = {
                "arms": f"{left} - {right}",
                "n": len(diffs),
                "mean_difference": round(statistics.fmean(diffs), 4),
                "one_sided_95_lower": round(lower, 4),
                "skill_helps": bool(lower > 0),
                "detectable_effect": 0.20,
                "note": (
                    "Pre-registered: detects a 0.20 F1 gap at n=20 with ~91% "
                    "power and cannot reliably detect 0.10. A null is evidence "
                    "against a large effect, not evidence of no effect."
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
