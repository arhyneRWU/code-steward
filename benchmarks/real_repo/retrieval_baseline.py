from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from benchmarks.guards import Exclusions, checked_rate
from code_steward.db import all_endpoints, all_units, connect
from code_steward.packet import build_packet
from code_steward.retrieval import retrieve_units


def load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_cases(cases: list[dict[str, Any]], unit_ids: set[str]) -> None:
    case_ids: set[str] = set()
    for case in cases:
        case_id = case["id"]
        if case_id in case_ids:
            raise ValueError(f"Duplicate real-repository case ID: {case_id}")
        case_ids.add(case_id)

        relevant = set(case["relevant"])
        traps = set(case.get("traps", []))
        if not relevant:
            raise ValueError(f"Case {case_id!r} has no relevant units")
        if relevant & traps:
            raise ValueError(f"Case {case_id!r} marks a unit relevant and a trap")

        referenced = relevant | traps
        redundancy_members: set[str] = set()
        for group in case.get("redundancy_groups", []):
            members = set(group)
            if len(members) < 2:
                raise ValueError(f"Case {case_id!r} has a redundancy group smaller than two")
            if len(members) != len(group):
                raise ValueError(f"Case {case_id!r} repeats a unit in a redundancy group")
            overlap = redundancy_members & members
            if overlap:
                values = ", ".join(sorted(overlap))
                raise ValueError(f"Case {case_id!r} repeats redundancy members: {values}")
            redundancy_members.update(members)
            referenced.update(members)

        missing = referenced - unit_ids
        if missing:
            values = ", ".join(sorted(missing))
            raise ValueError(f"Case {case_id!r} references unknown units: {values}")


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _known_redundant_candidates(
    candidate_ids: list[str],
    redundancy_groups: list[list[str]],
) -> int:
    selected = set(candidate_ids)
    redundant = 0
    for group in redundancy_groups:
        redundant += max(0, len(selected & set(group)) - 1)
    return redundant


def _hit_at(candidate_ids: list[str], relevant: set[str], k: int) -> bool:
    return bool(relevant & set(candidate_ids[:k]))


def evaluate_case(case: dict[str, Any], units, endpoints) -> dict[str, Any]:
    limit = int(case.get("limit", 8))
    started = time.perf_counter()
    results = retrieve_units(
        units,
        case["query"],
        limit,
        case.get("input_types", []),
        case.get("return_type", ""),
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    candidate_ids = [result.unit.unit_id for result in results]
    relevant = set(case["relevant"])
    traps = set(case.get("traps", []))
    redundancy_groups = case.get("redundancy_groups", [])
    relevant_found = relevant & set(candidate_ids)
    first_relevant_rank = next(
        (rank for rank, unit_id in enumerate(candidate_ids, 1) if unit_id in relevant),
        None,
    )

    packet = build_packet(
        case["query"],
        results,
        endpoints,
        case.get("input_types", []),
        case.get("return_type", ""),
    )
    packet_text = json.dumps(packet, separators=(",", ":"), sort_keys=True)

    return {
        "id": case["id"],
        "category": case["category"],
        "query": case["query"],
        "limit": limit,
        "candidates": candidate_ids,
        "candidate_scores": [round(result.score, 3) for result in results],
        "relevant": sorted(relevant),
        "traps": sorted(traps),
        "redundancy_groups": redundancy_groups,
        "hit_at_1": _hit_at(candidate_ids, relevant, 1),
        "hit_at_3": _hit_at(candidate_ids, relevant, 3),
        "hit_at_5": _hit_at(candidate_ids, relevant, 5),
        "hit_at_k": bool(relevant_found),
        "recall_at_k": len(relevant_found) / len(relevant),
        "reciprocal_rank": 0.0 if first_relevant_rank is None else 1.0 / first_relevant_rank,
        "known_traps_returned": sum(unit_id in traps for unit_id in candidate_ids),
        "known_redundant_candidates": _known_redundant_candidates(
            candidate_ids, redundancy_groups
        ),
        "duplicate_candidates": len(candidate_ids) - len(set(candidate_ids)),
        "candidates_returned": len(candidate_ids),
        "packet_chars": len(packet_text),
        "packet_bytes": len(packet_text.encode("utf-8")),
        "retrieval_ms": elapsed_ms,
        "implementation_bodies_loaded": 0,
    }


def _summary_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Requests production retrieval baseline",
        "",
        f"- Cases: **{summary['case_count']}**",
        f"- Hit@1: **{summary['hit_rate_at_1']:.2%}**",
        f"- Hit@3: **{summary['hit_rate_at_3']:.2%}**",
        f"- Hit@5: **{summary['hit_rate_at_5']:.2%}**",
        f"- Hit@K: **{summary['hit_rate_at_k']:.2%}**",
        f"- Macro recall@K: **{summary['macro_recall_at_k']:.2%}**",
        f"- MRR: **{summary['mrr']:.3f}**",
        f"- Known trap rate: **{summary['known_trap_rate']:.2%}**",
        f"- Known redundancy rate: **{summary['known_redundancy_rate']:.2%}**",
        f"- Mean candidates returned: **{summary['mean_candidates_returned']:.2f}**",
        f"- Candidate fill rate: **{summary['candidate_fill_rate']:.2%}**",
        f"- Mean packet bytes: **{summary['mean_packet_bytes']:.1f}**",
        f"- Mean retrieval time: **{summary['mean_retrieval_ms']:.3f} ms**",
        "",
        "This baseline uses production `retrieve_units()` unchanged and does not consume "
        "CALLS edges.",
        "",
    ]
    return "\n".join(lines)


def run_baseline(database: Path, cases_path: Path) -> dict[str, Any]:
    conn = connect(database)
    try:
        units = all_units(conn)
        endpoints = all_endpoints(conn)
    finally:
        conn.close()

    cases = load_cases(cases_path)
    validate_cases(cases, {unit.unit_id for unit in units})

    # Nothing is dropped today -- validate_cases raises rather than
    # skipping. The block is emitted anyway so that a future skip
    # cannot be added without appearing in the report.
    exclusions = Exclusions()
    results = [evaluate_case(case, units, endpoints) for case in cases]

    total_candidates = sum(result["candidates_returned"] for result in results)
    total_requested = sum(result["limit"] for result in results)
    total_traps = sum(result["known_traps_returned"] for result in results)
    total_redundant = sum(result["known_redundant_candidates"] for result in results)
    total_duplicates = sum(result["duplicate_candidates"] for result in results)

    return {
        "schema_version": 1,
        "strategy": "production-retrieve-unmodified",
        "cases_path": cases_path.name,
        "fixture": {
            "units": len(units),
            "endpoints": len(endpoints),
        },
        "summary": {
            "case_count": len(results),
            "hit_rate_at_1": _mean([float(result["hit_at_1"]) for result in results]),
            "hit_rate_at_3": _mean([float(result["hit_at_3"]) for result in results]),
            "hit_rate_at_5": _mean([float(result["hit_at_5"]) for result in results]),
            "hit_rate_at_k": _mean([float(result["hit_at_k"]) for result in results]),
            "macro_recall_at_k": _mean([result["recall_at_k"] for result in results]),
            "mrr": _mean([result["reciprocal_rank"] for result in results]),
            # checked_rate, not a guarded division. Every one of these
            # improves as it shrinks, so an arm that returned nothing
            # would otherwise publish a perfect zero on all three.
            "known_trap_rate": checked_rate(
                total_traps, total_candidates, metric="known_trap_rate"
            ),
            "known_redundancy_rate": checked_rate(
                total_redundant, total_candidates, metric="known_redundancy_rate"
            ),
            "duplicate_candidate_rate": checked_rate(
                total_duplicates, total_candidates, metric="duplicate_candidate_rate"
            ),
            "mean_candidates_returned": _mean(
                [float(result["candidates_returned"]) for result in results]
            ),
            "candidate_fill_rate": checked_rate(
                total_candidates, total_requested, metric="candidate_fill_rate"
            ),
            "mean_packet_chars": _mean([float(result["packet_chars"]) for result in results]),
            "mean_packet_bytes": _mean([float(result["packet_bytes"]) for result in results]),
            "mean_retrieval_ms": _mean([result["retrieval_ms"] for result in results]),
        },
        "cases": results,
        "excluded": exclusions.to_dict(),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure unchanged production retrieval on a real-repository index."
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report = run_baseline(args.database.resolve(), args.cases.resolve())
    (output_dir / "retrieval-baseline.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = _summary_markdown(report)
    (output_dir / "retrieval-baseline.md").write_text(summary, encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
