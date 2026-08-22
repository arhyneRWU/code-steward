from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from rapidfuzz import fuzz

from benchmarks.retrieval.run import index_fixture_repo, load_cases, validate_cases
from code_steward.models import CodeUnit, SearchResult
from code_steward.packet import build_packet
from code_steward.search import search_units

SIMILARITY_THRESHOLD = 0.78
MMR_RELEVANCE_WEIGHT = 0.90
Selector = Callable[[list[SearchResult], int], list[SearchResult]]


def _metadata_text(unit: CodeUnit) -> str:
    values = [unit.name, unit.qualname, unit.purpose, *unit.concepts]
    return " ".join(value for value in values if value)


def metadata_similarity(left: CodeUnit, right: CodeUnit) -> float:
    """Estimate candidate similarity from indexed metadata only."""
    semantic = fuzz.token_set_ratio(_metadata_text(left), _metadata_text(right)) / 100.0
    signature = fuzz.token_set_ratio(left.signature, right.signature) / 100.0
    return semantic * 0.85 + signature * 0.15


def top_n(results: list[SearchResult], limit: int) -> list[SearchResult]:
    """Return the unmodified baseline top-N packet."""
    return results[:limit]


def similarity_cap(results: list[SearchResult], limit: int) -> list[SearchResult]:
    """Compress the baseline top-N by removing near-duplicates."""
    selected: list[SearchResult] = []
    for candidate in results[:limit]:
        if any(
            metadata_similarity(candidate.unit, existing.unit) >= SIMILARITY_THRESHOLD
            for existing in selected
        ):
            continue
        selected.append(candidate)
    return selected


def mmr_select(results: list[SearchResult], limit: int) -> list[SearchResult]:
    """Rerank a pool using relevance and metadata diversity."""
    if not results or limit <= 0:
        return []

    remaining = list(results)
    selected = [remaining.pop(0)]
    while remaining and len(selected) < limit:
        best_index = 0
        best_utility = float("-inf")
        for index, candidate in enumerate(remaining):
            relevance = candidate.score / 100.0
            redundancy = max(
                metadata_similarity(candidate.unit, existing.unit) for existing in selected
            )
            utility = MMR_RELEVANCE_WEIGHT * relevance - (1.0 - MMR_RELEVANCE_WEIGHT) * redundancy
            if utility > best_utility:
                best_utility = utility
                best_index = index
        selected.append(remaining.pop(best_index))
    return selected


STRATEGIES: dict[str, Selector] = {
    "baseline": top_n,
    "similarity_cap": similarity_cap,
    "mmr": mmr_select,
}


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


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate_strategy(name: str, selector: Selector) -> dict[str, Any]:
    """Evaluate one selector against the frozen retrieval benchmark."""
    units, endpoints = index_fixture_repo()
    cases = load_cases()
    validate_cases(cases, {unit.unit_id for unit in units})

    rows: list[dict[str, Any]] = []
    for case in cases:
        started = time.perf_counter()
        ranked = search_units(
            units,
            case["query"],
            len(units),
            case.get("input_types", []),
            case.get("return_type", ""),
        )
        results = selector(ranked, case.get("limit", 5))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        candidate_ids = [result.unit.unit_id for result in results]
        relevant = set(case["relevant"])
        traps = set(case.get("traps", []))
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
        rows.append(
            {
                "id": case["id"],
                "candidates": candidate_ids,
                "candidate_count": len(candidate_ids),
                "hit": bool(relevant_found),
                "recall_at_k": len(relevant_found) / len(relevant),
                "reciprocal_rank": (
                    0.0 if first_relevant_rank is None else 1.0 / first_relevant_rank
                ),
                "known_traps_returned": sum(unit_id in traps for unit_id in candidate_ids),
                "known_redundant_candidates": _known_redundant_candidates(
                    candidate_ids,
                    case.get("redundancy_groups", []),
                ),
                "packet_chars": len(packet_text),
                "packet_bytes": len(packet_text.encode("utf-8")),
                "retrieval_ms": elapsed_ms,
            }
        )

    total_candidates = sum(row["candidate_count"] for row in rows)
    total_traps = sum(row["known_traps_returned"] for row in rows)
    total_redundant = sum(row["known_redundant_candidates"] for row in rows)
    return {
        "strategy": name,
        "summary": {
            "case_count": len(rows),
            "hit_rate_at_k": _mean([float(row["hit"]) for row in rows]),
            "macro_recall_at_k": _mean([row["recall_at_k"] for row in rows]),
            "mrr": _mean([row["reciprocal_rank"] for row in rows]),
            "mean_candidate_count": _mean([float(row["candidate_count"]) for row in rows]),
            "known_trap_rate": total_traps / total_candidates if total_candidates else 0.0,
            "known_redundancy_rate": (
                total_redundant / total_candidates if total_candidates else 0.0
            ),
            "mean_packet_chars": _mean([float(row["packet_chars"]) for row in rows]),
            "mean_packet_bytes": _mean([float(row["packet_bytes"]) for row in rows]),
            "mean_retrieval_ms": _mean([row["retrieval_ms"] for row in rows]),
        },
        "cases": rows,
    }


def run_comparison() -> dict[str, Any]:
    """Compare selectors without changing production retrieval."""
    return {
        "schema_version": 1,
        "experiment": "retrieval-diversity-v1",
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "mmr_relevance_weight": MMR_RELEVANCE_WEIGHT,
        "strategies": {
            name: evaluate_strategy(name, selector) for name, selector in STRATEGIES.items()
        },
    }


def main() -> int:
    print(json.dumps(run_comparison(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
