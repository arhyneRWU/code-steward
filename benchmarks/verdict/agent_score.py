"""Score reviewer verdicts against the answer key.

`benchmarks.verdict.run` scores retrieval: did the labelled duplicate
reach the reviewer. This scores the decision the reviewer then made,
which is the thing the product actually claims.

A positive case is correct when the reviewer answers REUSE or EXTEND
and names the labelled duplicate. Naming a different candidate is
wrong even though the reviewer had no way to know -- the arm handed
it the wrong evidence, and that is the arm's failure, not the
reviewer's. A positive case where the duplicate never entered the
packet is therefore always wrong, which is the point: it is where
retrieval failure turns into verdict failure.

A negative case is correct when the reviewer answers NEW. Anything
else is the reviewer being talked into reusing code that does not do
the job, which is the expensive failure of the two.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

VERDICTS = frozenset({"REUSE", "EXTEND", "NEW"})


def load_answers(directory: Path) -> dict[str, dict[str, str]]:
    """Read every reviewer answer file into one map by task ID."""
    answers: dict[str, dict[str, str]] = {}
    for path in sorted(directory.glob("answer-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload["answers"]:
            answers[row["id"]] = row
    return answers


def score(
    key: list[dict[str, Any]], answers: dict[str, dict[str, str]]
) -> tuple[dict[str, Any], int]:
    """Tally each arm's verdicts against the key."""
    tally: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    missing = 0
    for row in key:
        answer = answers.get(row["task_id"])
        if answer is None:
            missing += 1
            continue
        arm = tally[row["arm"]]
        verdict = str(answer.get("verdict", "")).upper()
        named = str(answer.get("candidate", "")).strip()
        if verdict not in VERDICTS:
            arm["unparsable"] += 1
            continue
        if row["kind"] == "reuse-available":
            arm["positives"] += 1
            if verdict == "NEW":
                arm["positive_missed"] += 1
            elif row["expected_label"] and named == row["expected_label"]:
                arm["positive_correct"] += 1
            else:
                arm["positive_wrong_unit"] += 1
            if not row["expected_label"]:
                arm["positive_unreachable"] += 1
        else:
            arm["negatives"] += 1
            if verdict == "NEW":
                arm["negative_correct"] += 1
            else:
                arm["negative_talked_into_reuse"] += 1
    return {name: dict(sorted(counts.items())) for name, counts in sorted(tally.items())}, missing


def _rates(counts: dict[str, int]) -> dict[str, float]:
    positives = counts.get("positives", 0)
    negatives = counts.get("negatives", 0)
    return {
        "positive_accuracy": round(counts.get("positive_correct", 0) / positives, 3)
        if positives
        else 0.0,
        "negative_accuracy": round(counts.get("negative_correct", 0) / negatives, 3)
        if negatives
        else 0.0,
        "overall_accuracy": round(
            (counts.get("positive_correct", 0) + counts.get("negative_correct", 0))
            / (positives + negatives),
            3,
        )
        if positives + negatives
        else 0.0,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score reviewer verdicts.")
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    key = json.loads(args.prompts.read_text(encoding="utf-8"))["answer_key"]
    answers = load_answers(args.answers)
    tally, missing = score(key, answers)

    payload = {
        "schema_version": 1,
        "judgements_expected": len(key),
        "judgements_missing": missing,
        "arms": [{"arm": name, **counts, **_rates(counts)} for name, counts in tally.items()],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
