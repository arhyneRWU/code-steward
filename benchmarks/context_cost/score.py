"""Score the context-cost run against the pre-registered rules.

`docs/context-cost.md` fixes the test: a one-sided paired sign-flip
permutation test at alpha 0.05, on bytes and on recall, and a win
requires not losing on the other. This file exists separately from
the runner so a result cannot be quietly re-run into a better one.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from benchmarks.skill.score import permutation_p

ARMS = ("A_code_steward", "B_gcr_delivered", "C_gcr_sufficient", "D_hybrid")


def _paired(rows: list[dict[str, Any]], left: str, right: str, field: str) -> list[float]:
    """Differences, left minus right, over targets both arms scored."""
    out: list[float] = []
    for row in rows:
        source = row["arms"] if field == "bytes" else row["recall"]
        a = source.get(left, {}).get(field) if field == "bytes" else source.get(left)
        b = source.get(right, {}).get(field) if field == "bytes" else source.get(right)
        if a is None or b is None:
            continue
        out.append(float(a) - float(b))
    return out


def _test(diffs: list[float], *, lower_is_better: bool) -> dict[str, Any]:
    if not diffs:
        return {"n": 0}
    # The permutation test is one-sided on a positive sum, so a
    # "fewer bytes is better" question is asked with the sign flipped
    # rather than by reading the p value backwards.
    oriented = [-value for value in diffs] if lower_is_better else diffs
    ties = sum(1 for value in diffs if abs(value) < 1e-9)
    return {
        "n": len(diffs),
        "ties": ties,
        "tie_rate": round(ties / len(diffs), 3),
        "mean_difference": round(statistics.fmean(diffs), 4),
        "median_difference": round(statistics.median(diffs), 4),
        "permutation_p": round(permutation_p(oriented), 4),
    }


def score(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload["targets"]
    per_arm = {
        arm: {
            "mean_bytes": round(statistics.fmean(r["arms"][arm]["bytes"] for r in rows), 1),
            "median_bytes": round(statistics.median(r["arms"][arm]["bytes"] for r in rows), 1),
            "total_bytes": sum(r["arms"][arm]["bytes"] for r in rows),
        }
        for arm in ARMS
    }
    scored = [r for r in rows if r["recall"]["A_code_steward"] is not None]
    for arm in ("A_code_steward", "C_gcr_sufficient"):
        per_arm[arm]["mean_recall"] = round(statistics.fmean(r["recall"][arm] for r in scored), 4)
        per_arm[arm]["outside_key_total"] = sum(r["outside_key"][arm] for r in rows)

    return {
        "schema_version": 1,
        "targets": len(rows),
        "scored_targets": len(scored),
        "per_arm": per_arm,
        "primary": {
            "bytes_A_minus_C": _test(
                _paired(rows, "A_code_steward", "C_gcr_sufficient", "bytes"), lower_is_better=True
            ),
            "recall_A_minus_C": _test(
                _paired(scored, "A_code_steward", "C_gcr_sufficient", "recall"),
                lower_is_better=False,
            ),
        },
        "hybrid": {
            "bytes_D_minus_A": _test(
                _paired(rows, "D_hybrid", "A_code_steward", "bytes"), lower_is_better=True
            ),
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score the context-cost run.")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    report = score(json.loads(args.run.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
