"""Score packet precision and noise from blind candidate labels.

Hit@K measures whether the answer was present. It cannot distinguish a
packet of near-misses from a packet of unrelated code, so it cannot
speak to the project's noise-reduction claim at all.

This module scores what Hit@K cannot: given a label for every
candidate an arm returned, what share of the packet was worth the
agent's attention, and what share was wasted.

The headline number is the noise rate: the fraction of returned
candidates labeled irrelevant. Precision@K is reported both strictly
(relevant only) and leniently (relevant or plausible), because the
strict reading punishes a genuinely useful near-miss and the lenient
reading forgives real padding. A claim that survives only one of the
two readings is not a claim worth making.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

RELEVANT = "relevant"
PLAUSIBLE = "plausible"
IRRELEVANT = "irrelevant"
VALID_LABELS = frozenset({RELEVANT, PLAUSIBLE, IRRELEVANT})

LabelKey = tuple[str, str]


def load_labels(paths: list[Path]) -> dict[LabelKey, str]:
    """Merge label files, rejecting conflicts instead of choosing."""
    labels: dict[LabelKey, str] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        # Accept both the stored label file and a raw labeler dump.
        entries = payload["entries"] if "entries" in payload else payload["labels"]
        for entry in entries:
            key = (entry["case_id"], entry["unit_id"])
            label = entry["label"]
            if label not in VALID_LABELS:
                raise ValueError(f"{path.name}: unknown label {label!r} for {key}")
            if key in labels and labels[key] != label:
                raise ValueError(
                    f"Conflicting labels for {key}: {labels[key]!r} and {label!r}. "
                    "Resolve the disagreement rather than silently keeping one."
                )
            labels[key] = label
    return labels


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _case_bytes(case: dict[str, Any]) -> int:
    """Bytes this arm hands the agent for one case.

    The two arms report their cost under different names because they
    deliver different things: Code Steward a rendered packet, the
    control arm the source of each candidate.
    """
    for key in ("packet_bytes", "read_bytes"):
        if key in case:
            return int(case[key])
    return 0


def score_arm(
    cases: list[dict[str, Any]],
    labels: dict[LabelKey, str],
    arm_name: str,
) -> dict[str, Any]:
    """Score one arm's packets against the shared label set."""
    per_case = []
    unlabeled: list[LabelKey] = []

    for case in cases:
        case_id = case["id"]
        candidates = case["candidates"]
        counts = {RELEVANT: 0, PLAUSIBLE: 0, IRRELEVANT: 0}
        for unit_id in candidates:
            key = (case_id, unit_id)
            label = labels.get(key)
            if label is None:
                unlabeled.append(key)
                continue
            counts[label] += 1

        scored = sum(counts.values())
        case_bytes = _case_bytes(case)
        # Byte cost is reported per case, not per candidate, so the
        # split below assumes each candidate in a packet costs about
        # the same. That holds well for Code Steward's uniform summary
        # entries and less well for raw source, where function length
        # varies. It is an approximation and is labelled as one.
        noise_bytes = (counts[IRRELEVANT] / scored * case_bytes) if scored else 0.0
        per_case.append(
            {
                "id": case_id,
                "case_bytes": case_bytes,
                "approx_noise_bytes": noise_bytes,
                "candidates_returned": len(candidates),
                "scored": scored,
                "relevant": counts[RELEVANT],
                "plausible": counts[PLAUSIBLE],
                "irrelevant": counts[IRRELEVANT],
                "precision_strict": counts[RELEVANT] / scored if scored else 0.0,
                "precision_lenient": (
                    (counts[RELEVANT] + counts[PLAUSIBLE]) / scored if scored else 0.0
                ),
                "noise_rate": counts[IRRELEVANT] / scored if scored else 0.0,
            }
        )

    if unlabeled:
        preview = ", ".join(f"{case}/{unit}" for case, unit in unlabeled[:5])
        raise ValueError(
            f"{arm_name}: {len(unlabeled)} returned candidates have no label ({preview}). "
            "Precision computed over a partial packet would understate noise."
        )

    total_scored = sum(entry["scored"] for entry in per_case)
    total_relevant = sum(entry["relevant"] for entry in per_case)
    total_plausible = sum(entry["plausible"] for entry in per_case)
    total_irrelevant = sum(entry["irrelevant"] for entry in per_case)
    total_bytes = sum(entry["case_bytes"] for entry in per_case)
    total_noise_bytes = sum(entry["approx_noise_bytes"] for entry in per_case)

    return {
        "arm": arm_name,
        "summary": {
            "case_count": len(per_case),
            "candidates_scored": total_scored,
            # Micro-averaged: every candidate counts once, so a case
            # that returned fewer candidates does not get equal weight.
            "precision_strict": total_relevant / total_scored if total_scored else 0.0,
            "precision_lenient": (
                (total_relevant + total_plausible) / total_scored if total_scored else 0.0
            ),
            "noise_rate": total_irrelevant / total_scored if total_scored else 0.0,
            # Macro-averaged: every case counts once, so one long packet
            # cannot dominate the headline.
            "macro_precision_strict": _mean([e["precision_strict"] for e in per_case]),
            "macro_noise_rate": _mean([e["noise_rate"] for e in per_case]),
            "relevant": total_relevant,
            "plausible": total_plausible,
            "irrelevant": total_irrelevant,
            "mean_bytes_per_case": total_bytes / len(per_case) if per_case else 0.0,
            # The headline for a context-stewardship tool: not what
            # share of the packet was wasted, but how much of the
            # agent's context the waste actually consumed.
            "approx_mean_noise_bytes_per_case": (
                total_noise_bytes / len(per_case) if per_case else 0.0
            ),
        },
        "cases": per_case,
    }


def _summary_markdown(reports: list[dict[str, Any]]) -> str:
    lines = [
        "# Packet precision and noise",
        "",
        "| Arm | Precision (strict) | Precision (lenient) | Noise rate | "
        "Wasted bytes/query | Scored |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for report in reports:
        summary = report["summary"]
        lines.append(
            f"| {report['arm']} | {summary['precision_strict']:.2%} | "
            f"{summary['precision_lenient']:.2%} | {summary['noise_rate']:.2%} | "
            f"{summary['approx_mean_noise_bytes_per_case']:,.0f} | "
            f"{summary['candidates_scored']} |"
        )
    lines += [
        "",
        "Strict precision counts only candidates labeled relevant. Lenient also "
        "counts plausible near-misses. Noise rate is the share labeled irrelevant.",
        "",
        "Wasted bytes per query is the noise rate applied to that arm's byte cost. "
        "It assumes candidates within one packet cost about the same, which holds "
        "for uniform summary entries and less well for raw source.",
        "",
        "Labels were assigned blind: the labeler saw the query and the unit source, "
        "never which arm returned a candidate, its rank, or the recorded gold unit.",
        "",
    ]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Score packet precision and noise from blind candidate labels."
    )
    parser.add_argument(
        "--labels", type=Path, action="append", required=True, help="label JSON; repeatable"
    )
    parser.add_argument(
        "--arm",
        action="append",
        required=True,
        metavar="NAME=REPORT.json",
        help="a baseline report to score; repeatable",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    labels = load_labels([path.resolve() for path in args.labels])

    reports = []
    for entry in args.arm:
        name, _, report_path = entry.partition("=")
        if not name or not report_path:
            raise SystemExit(f"--arm expects NAME=REPORT.json, got {entry!r}")
        cases = json.loads(Path(report_path).resolve().read_text(encoding="utf-8"))["cases"]
        reports.append(score_arm(cases, labels, name))

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "precision.json").write_text(
        json.dumps({"schema_version": 1, "arms": reports}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = _summary_markdown(reports)
    (output_dir / "precision.md").write_text(summary, encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
