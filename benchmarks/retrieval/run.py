from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from code_steward.indexer import index_python_file, iter_python_files
from code_steward.packet import build_packet
from code_steward.search import search_units

HERE = Path(__file__).resolve().parent
FIXTURE_ROOT = HERE / "fixture_repo"
CASES_PATH = HERE / "cases.json"


def load_cases() -> list[dict[str, Any]]:
    """Load the human-defined retrieval gold set."""
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def index_fixture_repo():
    """Index the synthetic repository with the production indexer."""
    units = []
    endpoints = []
    for path in iter_python_files(FIXTURE_ROOT):
        file_units, file_endpoints = index_python_file(FIXTURE_ROOT, path)
        units.extend(file_units)
        endpoints.extend(file_endpoints)
    return units, endpoints


def validate_cases(cases: list[dict[str, Any]], unit_ids: set[str]) -> None:
    """Reject malformed benchmark cases before calculating metrics."""
    case_ids: set[str] = set()
    for case in cases:
        case_id = case["id"]
        if case_id in case_ids:
            raise ValueError(f"Duplicate benchmark case ID: {case_id}")
        case_ids.add(case_id)

        relevant = set(case["relevant"])
        traps = set(case.get("traps", []))
        if not relevant:
            raise ValueError(f"Benchmark case {case_id!r} has no relevant units")
        if relevant & traps:
            raise ValueError(f"Benchmark case {case_id!r} marks a unit relevant and a trap")

        referenced = relevant | traps
        redundancy_members: set[str] = set()
        for group in case.get("redundancy_groups", []):
            members = set(group)
            if len(members) < 2:
                raise ValueError(
                    f"Benchmark case {case_id!r} has a redundancy group with fewer than two units"
                )
            if len(members) != len(group):
                raise ValueError(
                    f"Benchmark case {case_id!r} repeats a unit inside a redundancy group"
                )
            overlap = redundancy_members & members
            if overlap:
                values = ", ".join(sorted(overlap))
                raise ValueError(
                    f"Benchmark case {case_id!r} repeats redundancy members: {values}"
                )
            redundancy_members.update(members)
            referenced.update(members)

        missing = referenced - unit_ids
        if missing:
            values = ", ".join(sorted(missing))
            raise ValueError(f"Benchmark case {case_id!r} references unknown units: {values}")


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _known_redundant_candidates(
    candidate_ids: list[str],
    redundancy_groups: list[list[str]],
) -> int:
    selected = set(candidate_ids)
    redundant = 0
    for group in redundancy_groups:
        selected_from_group = len(selected & set(group))
        redundant += max(0, selected_from_group - 1)
    return redundant


def evaluate_case(
    case: dict[str, Any],
    units,
    endpoints,
) -> dict[str, Any]:
    """Run one gold query through the current retrieval baseline."""
    started = time.perf_counter()
    results = search_units(
        units,
        case["query"],
        case.get("limit", 5),
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
    duplicate_count = len(candidate_ids) - len(set(candidate_ids))
    trap_count = sum(unit_id in traps for unit_id in candidate_ids)
    redundant_count = _known_redundant_candidates(candidate_ids, redundancy_groups)

    return {
        "id": case["id"],
        "category": case["category"],
        "query": case["query"],
        "candidates": candidate_ids,
        "relevant": sorted(relevant),
        "traps": sorted(traps),
        "redundancy_groups": redundancy_groups,
        "hit": bool(relevant_found),
        "recall_at_k": len(relevant_found) / len(relevant),
        "reciprocal_rank": 0.0 if first_relevant_rank is None else 1.0 / first_relevant_rank,
        "known_traps_returned": trap_count,
        "known_redundant_candidates": redundant_count,
        "duplicate_candidates": duplicate_count,
        "packet_chars": len(packet_text),
        "packet_bytes": len(packet_text.encode("utf-8")),
        "retrieval_ms": elapsed_ms,
        "implementation_bodies_loaded": 0,
    }


def run_benchmark() -> dict[str, Any]:
    """Run current search against the complete retrieval gold set."""
    index_started = time.perf_counter()
    units, endpoints = index_fixture_repo()
    index_ms = (time.perf_counter() - index_started) * 1000.0
    cases = load_cases()
    validate_cases(cases, {unit.unit_id for unit in units})

    results = [evaluate_case(case, units, endpoints) for case in cases]
    total_candidates = sum(len(result["candidates"]) for result in results)
    total_traps = sum(result["known_traps_returned"] for result in results)
    total_redundant = sum(result["known_redundant_candidates"] for result in results)
    total_duplicates = sum(result["duplicate_candidates"] for result in results)

    return {
        "schema_version": 1,
        "strategy": "current-search-baseline",
        "fixture": {
            "files": len(list(iter_python_files(FIXTURE_ROOT))),
            "units": len(units),
            "endpoints": len(endpoints),
            "index_ms": index_ms,
        },
        "summary": {
            "case_count": len(results),
            "hit_rate_at_k": _mean([float(result["hit"]) for result in results]),
            "macro_recall_at_k": _mean([result["recall_at_k"] for result in results]),
            "mrr": _mean([result["reciprocal_rank"] for result in results]),
            "known_trap_rate": total_traps / total_candidates if total_candidates else 0.0,
            "known_redundancy_rate": (
                total_redundant / total_candidates if total_candidates else 0.0
            ),
            "duplicate_candidate_rate": (
                total_duplicates / total_candidates if total_candidates else 0.0
            ),
            "mean_packet_chars": _mean([float(result["packet_chars"]) for result in results]),
            "mean_packet_bytes": _mean([float(result["packet_bytes"]) for result in results]),
            "mean_retrieval_ms": _mean([result["retrieval_ms"] for result in results]),
        },
        "cases": results,
    }


def main() -> int:
    print(json.dumps(run_benchmark(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
