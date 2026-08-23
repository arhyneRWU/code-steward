"""Score a small model's DRY judgement against the blind labels.

The premise this scores is the project's whole reason to exist: that
a cheap model can do useful work on a large codebase if something
hands it the right small bundle. If a small model cannot make this
judgement from a bundle, no amount of better bundling helps, and the
pipeline needs a large model at the point where it was supposed to
save one.

A positive bundle is correct only when the model names **both**
members of the labelled pair. Naming one of the two and one
distractor is wrong: acting on it would merge the wrong functions.

A negative bundle is correct only when the model returns no pair.
Inventing one is the expensive failure -- the same failure the packet
measurement found, where a reviewer shown plausible candidates picks
one rather than declining.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_answers(directory: Path) -> dict[str, dict[str, Any]]:
    """Read every answer file into one map by bundle ID."""
    answers: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("answer-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload["answers"]:
            answers[row["id"]] = row
    return answers


def score(key: list[dict[str, Any]], answers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Tally judgements against the labels."""
    tally: dict[str, int] = defaultdict(int)
    misses: list[dict[str, Any]] = []

    for row in key:
        answer = answers.get(row["bundle_id"])
        if answer is None:
            tally["missing"] += 1
            continue
        given = sorted(str(value).strip().upper() for value in answer.get("duplicate_pair") or [])
        expected = sorted(row["expected"])

        if row["kind"] == "duplicate-present":
            tally["positives"] += 1
            if given == expected:
                tally["positive_correct"] += 1
            elif not given:
                tally["positive_missed"] += 1
                misses.append({"bundle": row["bundle_id"], "outcome": "declined"})
            else:
                tally["positive_wrong_pair"] += 1
                misses.append({"bundle": row["bundle_id"], "outcome": "wrong-pair", "gave": given})
        else:
            tally["negatives"] += 1
            if given:
                tally["negative_invented"] += 1
                misses.append({"bundle": row["bundle_id"], "outcome": "invented", "gave": given})
            else:
                tally["negative_correct"] += 1

    positives = tally["positives"]
    negatives = tally["negatives"]
    total = positives + negatives
    return {
        "counts": dict(sorted(tally.items())),
        "positive_accuracy": round(tally["positive_correct"] / positives, 3) if positives else 0.0,
        "negative_accuracy": round(tally["negative_correct"] / negatives, 3) if negatives else 0.0,
        "overall_accuracy": round(
            (tally["positive_correct"] + tally["negative_correct"]) / total, 3
        )
        if total
        else 0.0,
        "misses": misses,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score small-model DRY judgement.")
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--model", default="unknown")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    key = json.loads(args.prompts.read_text(encoding="utf-8"))["answer_key"]
    payload = {
        "schema_version": 1,
        "model": args.model,
        "ground_truth": "blind pair labels, not this project's similarity scores",
        "bundles": len(key),
        **score(key, load_answers(args.answers)),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
