from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from code_steward.db import all_hard_relationships, all_units, connect
from code_steward.retrieval import retrieve_units


def load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _adjacency(relationships):
    outgoing: dict[str, set[str]] = defaultdict(set)
    incoming: dict[str, set[str]] = defaultdict(set)
    for edge in relationships:
        if edge.relation != "CALLS" or edge.target_kind != "unit":
            continue
        outgoing[edge.source_unit_id].add(edge.target_ref)
        incoming[edge.target_ref].add(edge.source_unit_id)
    return outgoing, incoming


def _neighbors(seeds: list[str], adjacency: dict[str, set[str]]) -> set[str]:
    result: set[str] = set()
    for seed in seeds:
        result.update(adjacency.get(seed, set()))
    return result


def _connections(
    seeds: list[str],
    relevant: set[str],
    outgoing: dict[str, set[str]],
    incoming: dict[str, set[str]],
) -> list[dict[str, str]]:
    connections: list[dict[str, str]] = []
    for seed in seeds:
        for gold in sorted(relevant & outgoing.get(seed, set())):
            connections.append({"direction": "outgoing", "source": seed, "target": gold})
        for gold in sorted(relevant & incoming.get(seed, set())):
            connections.append({"direction": "incoming", "source": gold, "target": seed})
    return connections


def evaluate_case(case, units, outgoing, incoming) -> dict[str, Any]:
    results = retrieve_units(
        units,
        case["query"],
        int(case.get("limit", 8)),
        case.get("input_types", []),
        case.get("return_type", ""),
    )
    seeds = [result.unit.unit_id for result in results]
    relevant = set(case["relevant"])
    baseline_hit = bool(relevant & set(seeds))

    outgoing_neighbors = _neighbors(seeds, outgoing) - set(seeds)
    incoming_neighbors = _neighbors(seeds, incoming) - set(seeds)
    union_neighbors = outgoing_neighbors | incoming_neighbors

    return {
        "id": case["id"],
        "query": case["query"],
        "relevant": sorted(relevant),
        "baseline_candidates": seeds,
        "baseline_hit": baseline_hit,
        "outgoing_neighbor_count": len(outgoing_neighbors),
        "incoming_neighbor_count": len(incoming_neighbors),
        "union_neighbor_count": len(union_neighbors),
        "gold_reachable_outgoing": bool(relevant & outgoing_neighbors),
        "gold_reachable_incoming": bool(relevant & incoming_neighbors),
        "gold_reachable_union": bool(relevant & union_neighbors),
        "connecting_edges": _connections(seeds, relevant, outgoing, incoming),
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def run_analysis(database: Path, cases_path: Path) -> dict[str, Any]:
    conn = connect(database)
    try:
        units = all_units(conn)
        relationships = all_hard_relationships(conn)
    finally:
        conn.close()

    outgoing, incoming = _adjacency(relationships)
    cases = load_cases(cases_path)
    results = [evaluate_case(case, units, outgoing, incoming) for case in cases]
    misses = [result for result in results if not result["baseline_hit"]]
    resolved_calls = sum(
        edge.relation == "CALLS" and edge.target_kind == "unit" for edge in relationships
    )

    return {
        "schema_version": 1,
        "strategy": "one-hop-reachability-existing-resolved-calls",
        "resolved_calls": resolved_calls,
        "summary": {
            "case_count": len(results),
            "baseline_miss_count": len(misses),
            "misses_reachable_outgoing": sum(
                result["gold_reachable_outgoing"] for result in misses
            ),
            "misses_reachable_incoming": sum(
                result["gold_reachable_incoming"] for result in misses
            ),
            "misses_reachable_union": sum(result["gold_reachable_union"] for result in misses),
            "potential_hit_rate_with_union": (
                (
                    len(results)
                    - len(misses)
                    + sum(result["gold_reachable_union"] for result in misses)
                )
                / len(results)
                if results
                else 0.0
            ),
            "mean_outgoing_neighbors_for_misses": _mean(
                [float(result["outgoing_neighbor_count"]) for result in misses]
            ),
            "mean_incoming_neighbors_for_misses": _mean(
                [float(result["incoming_neighbor_count"]) for result in misses]
            ),
            "mean_union_neighbors_for_misses": _mean(
                [float(result["union_neighbor_count"]) for result in misses]
            ),
        },
        "cases": results,
    }


def _summary_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Trusted CALLS one-hop reachability",
        "",
        f"- Existing resolved CALLS edges: **{report['resolved_calls']}**",
        f"- Baseline misses: **{summary['baseline_miss_count']}**",
        f"- Misses reachable by outgoing edge: **{summary['misses_reachable_outgoing']}**",
        f"- Misses reachable by incoming edge: **{summary['misses_reachable_incoming']}**",
        f"- Misses reachable by union: **{summary['misses_reachable_union']}**",
        f"- Potential hit rate if every reachable gold were selected: "
        f"**{summary['potential_hit_rate_with_union']:.2%}**",
        f"- Mean one-hop union size for misses: "
        f"**{summary['mean_union_neighbors_for_misses']:.2f}**",
        "",
        "This is a reachability probe, not a new retrieval ranking strategy. It uses only the "
        "currently resolved CALLS edges and leaves production retrieval unchanged.",
        "",
    ]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure one-hop retrieval reachability from existing resolved CALLS edges."
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report = run_analysis(args.database.resolve(), args.cases.resolve())
    (output_dir / "calls-reachability.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = _summary_markdown(report)
    (output_dir / "calls-reachability.md").write_text(summary, encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
