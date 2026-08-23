from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from code_steward.db import all_endpoints, all_hard_relationships, all_units, connect
from code_steward.models import SearchResult
from code_steward.packet import build_packet
from code_steward.retrieval import rank_units, select_review_candidates

DIRECTIONS = ("outgoing", "incoming", "union")


def load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_cases(cases: list[dict[str, Any]], unit_ids: set[str]) -> None:
    seen: set[str] = set()
    for case in cases:
        case_id = case["id"]
        if case_id in seen:
            raise ValueError(f"Duplicate real-repository case ID: {case_id}")
        seen.add(case_id)

        relevant = set(case["relevant"])
        traps = set(case.get("traps", []))
        if not relevant:
            raise ValueError(f"Case {case_id!r} has no relevant units")
        if relevant & traps:
            raise ValueError(f"Case {case_id!r} marks a unit relevant and a trap")

        referenced = relevant | traps
        for group in case.get("redundancy_groups", []):
            referenced.update(group)

        missing = referenced - unit_ids
        if missing:
            values = ", ".join(sorted(missing))
            raise ValueError(f"Case {case_id!r} references unknown units: {values}")


def _adjacency(relationships):
    outgoing: dict[str, set[str]] = defaultdict(set)
    incoming: dict[str, set[str]] = defaultdict(set)
    for edge in relationships:
        if edge.relation != "CALLS" or edge.target_kind != "unit":
            continue
        outgoing[edge.source_unit_id].add(edge.target_ref)
        incoming[edge.target_ref].add(edge.source_unit_id)
    return outgoing, incoming


def _neighbors(
    seed_id: str,
    direction: str,
    outgoing: dict[str, set[str]],
    incoming: dict[str, set[str]],
) -> set[str]:
    if direction == "outgoing":
        return set(outgoing.get(seed_id, set()))
    if direction == "incoming":
        return set(incoming.get(seed_id, set()))
    if direction == "union":
        return set(outgoing.get(seed_id, set())) | set(incoming.get(seed_id, set()))
    raise ValueError(f"Unknown graph direction: {direction}")


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _hit_at(candidate_ids: list[str], relevant: set[str], k: int) -> bool:
    return bool(relevant & set(candidate_ids[:k]))


def _known_redundant_candidates(
    candidate_ids: list[str],
    redundancy_groups: list[list[str]],
) -> int:
    selected = set(candidate_ids)
    redundant = 0
    for group in redundancy_groups:
        redundant += max(0, len(selected & set(group)) - 1)
    return redundant


def _evaluate_ids(
    case: dict[str, Any],
    results: list[SearchResult],
    endpoints,
    elapsed_ms: float,
    *,
    candidate_pool_size: int,
    graph_promotions: list[dict[str, Any]],
) -> dict[str, Any]:
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
        "limit": int(case.get("limit", 8)),
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
        "candidate_pool_size": candidate_pool_size,
        "graph_promotions": graph_promotions,
        "packet_chars": len(packet_text),
        "packet_bytes": len(packet_text.encode("utf-8")),
        "retrieval_ms": elapsed_ms,
        "implementation_bodies_loaded": 0,
    }


def evaluate_case(
    case: dict[str, Any],
    units,
    endpoints,
    outgoing,
    incoming,
    direction: str,
) -> dict[str, Any]:
    limit = int(case.get("limit", 8))
    started = time.perf_counter()

    ranked = rank_units(
        units,
        case["query"],
        len(units),
        case.get("input_types", []),
        case.get("return_type", ""),
    )
    baseline = select_review_candidates(ranked, limit)
    lexical_by_id = {result.unit.unit_id: result for result in ranked}
    seed_scores = {result.unit.unit_id: result.score for result in baseline}
    baseline_ids = set(seed_scores)

    anchor_scores: dict[str, float] = {}
    anchor_ids: dict[str, list[str]] = defaultdict(list)
    for seed_id, seed_score in seed_scores.items():
        for neighbor_id in _neighbors(seed_id, direction, outgoing, incoming):
            if neighbor_id not in lexical_by_id:
                continue
            previous = anchor_scores.get(neighbor_id, -1.0)
            if seed_score > previous:
                anchor_scores[neighbor_id] = seed_score
            anchor_ids[neighbor_id].append(seed_id)

    pool_ids = baseline_ids | set(anchor_scores)
    fused: list[SearchResult] = []
    promotions: list[dict[str, Any]] = []

    for unit_id in pool_ids:
        lexical = lexical_by_id[unit_id]
        lexical_score = lexical.score
        anchor_score = anchor_scores.get(unit_id, 0.0)
        fused_score = lexical_score
        if anchor_score > 0.0 and lexical_score > 0.0:
            fused_score = max(lexical_score, math.sqrt(lexical_score * anchor_score))

        evidence = dict(lexical.evidence)
        evidence.update(
            {
                "graph_direction": direction,
                "graph_anchor_score": anchor_score,
                "graph_anchor_ids": sorted(set(anchor_ids.get(unit_id, []))),
                "lexical_score": lexical_score,
                "graph_fused_score": fused_score,
            }
        )
        fused.append(
            SearchResult(
                unit=lexical.unit,
                score=fused_score,
                evidence=evidence,
            )
        )

        if unit_id not in baseline_ids and fused_score > lexical_score:
            promotions.append(
                {
                    "unit_id": unit_id,
                    "lexical_score": round(lexical_score, 3),
                    "fused_score": round(fused_score, 3),
                    "anchor_score": round(anchor_score, 3),
                    "anchor_ids": sorted(set(anchor_ids.get(unit_id, []))),
                }
            )

    fused.sort(
        key=lambda result: (
            -result.score,
            -lexical_by_id[result.unit.unit_id].score,
            result.unit.path,
            result.unit.start_line,
        )
    )
    results = select_review_candidates(fused, limit)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    promotions.sort(key=lambda row: (-row["fused_score"], row["unit_id"]))

    return _evaluate_ids(
        case,
        results,
        endpoints,
        elapsed_ms,
        candidate_pool_size=len(pool_ids),
        graph_promotions=promotions,
    )


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total_candidates = sum(result["candidates_returned"] for result in results)
    total_requested = sum(result["limit"] for result in results)
    total_traps = sum(result["known_traps_returned"] for result in results)
    total_redundant = sum(result["known_redundant_candidates"] for result in results)
    total_duplicates = sum(result["duplicate_candidates"] for result in results)

    return {
        "case_count": len(results),
        "hit_rate_at_1": _mean([float(result["hit_at_1"]) for result in results]),
        "hit_rate_at_3": _mean([float(result["hit_at_3"]) for result in results]),
        "hit_rate_at_5": _mean([float(result["hit_at_5"]) for result in results]),
        "hit_rate_at_k": _mean([float(result["hit_at_k"]) for result in results]),
        "macro_recall_at_k": _mean([result["recall_at_k"] for result in results]),
        "mrr": _mean([result["reciprocal_rank"] for result in results]),
        "known_trap_rate": total_traps / total_candidates if total_candidates else 0.0,
        "known_redundancy_rate": total_redundant / total_candidates if total_candidates else 0.0,
        "duplicate_candidate_rate": (
            total_duplicates / total_candidates if total_candidates else 0.0
        ),
        "mean_candidates_returned": _mean(
            [float(result["candidates_returned"]) for result in results]
        ),
        "candidate_fill_rate": total_candidates / total_requested if total_requested else 0.0,
        "mean_candidate_pool_size": _mean(
            [float(result["candidate_pool_size"]) for result in results]
        ),
        "mean_packet_bytes": _mean([float(result["packet_bytes"]) for result in results]),
        "mean_retrieval_ms": _mean([result["retrieval_ms"] for result in results]),
    }


def run_experiment(database: Path, cases_path: Path) -> dict[str, Any]:
    conn = connect(database)
    try:
        units = all_units(conn)
        endpoints = all_endpoints(conn)
        relationships = all_hard_relationships(conn)
    finally:
        conn.close()

    cases = load_cases(cases_path)
    validate_cases(cases, {unit.unit_id for unit in units})
    outgoing, incoming = _adjacency(relationships)

    variants: dict[str, Any] = {}
    for direction in DIRECTIONS:
        results = [
            evaluate_case(case, units, endpoints, outgoing, incoming, direction)
            for case in cases
        ]
        variants[direction] = {
            "summary": _summarize(results),
            "cases": results,
        }

    return {
        "schema_version": 1,
        "strategy": "one-hop-calls-geometric-fusion",
        "formula": "max(lexical_score, sqrt(lexical_score * strongest_anchor_score))",
        "directions": list(DIRECTIONS),
        "cases_path": cases_path.name,
        "resolved_calls": sum(
            edge.relation == "CALLS" and edge.target_kind == "unit" for edge in relationships
        ),
        "variants": variants,
    }


def _summary_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# One-hop CALLS reranking experiment",
        "",
        f"- Resolved CALLS edges: **{report['resolved_calls']}**",
        f"- Fusion: `{report['formula']}`",
        "",
        "| Direction | Hit@1 | Hit@3 | Hit@5 | Hit@8 | MRR | Trap rate | Mean pool | Mean packet bytes |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for direction in DIRECTIONS:
        summary = report["variants"][direction]["summary"]
        lines.append(
            f"| {direction} | {summary['hit_rate_at_1']:.2%} | "
            f"{summary['hit_rate_at_3']:.2%} | {summary['hit_rate_at_5']:.2%} | "
            f"{summary['hit_rate_at_k']:.2%} | {summary['mrr']:.3f} | "
            f"{summary['known_trap_rate']:.2%} | "
            f"{summary['mean_candidate_pool_size']:.2f} | "
            f"{summary['mean_packet_bytes']:.1f} |"
        )

    lines.extend(
        [
            "",
            "This is a benchmark-only reranking experiment. Production `retrieve_units()` "
            "is unchanged.",
            "",
        ]
    )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare deterministic one-hop CALLS reranking variants."
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report = run_experiment(args.database.resolve(), args.cases.resolve())
    (output_dir / "calls-rerank.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = _summary_markdown(report)
    (output_dir / "calls-rerank.md").write_text(summary, encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
