from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

from benchmarks.retrieval.run import index_fixture_repo, load_cases, validate_cases
from code_steward.models import CodeUnit, SearchResult
from code_steward.packet import build_packet
from code_steward.search import search_units

EXPANSION_GAIN_WEIGHT = 0.45


@dataclass(frozen=True, slots=True)
class Alias:
    """One weighted replacement used only by this experiment."""

    target: str
    weight: float


@dataclass(frozen=True, slots=True)
class QueryVariant:
    """One expanded query and the relation that produced it."""

    query: str
    weight: float
    source: str
    target: str


AliasTable = dict[str, tuple[Alias, ...]]

ABBREVIATIONS: AliasTable = {
    "app": (Alias("application", 0.95),),
    "repo": (Alias("repository", 0.95),),
    "cfg": (Alias("config", 0.95), Alias("configuration", 0.85)),
    "auth": (Alias("authentication", 0.90),),
}

PROGRAMMING_ALIASES: AliasTable = {
    "save": (Alias("persist", 0.90), Alias("write", 0.85), Alias("store", 0.75)),
    "read": (Alias("load", 0.90), Alias("retrieve", 0.85), Alias("fetch", 0.80)),
    "remove": (Alias("delete", 0.90), Alias("evict", 0.85)),
    "log out": (
        Alias("revoke session", 0.90),
        Alias("invalidate session", 0.85),
        Alias("logout", 0.80),
        Alias("sign out", 0.80),
    ),
    "inventory": (Alias("catalog", 0.85), Alias("enumerate", 0.80)),
}

CONCEPT_ALIASES: AliasTable = {
    "settings": (Alias("configuration", 0.90), Alias("preferences", 0.85)),
    "cached": (Alias("cache", 0.95),),
    "files": (Alias("source files", 0.80),),
}

STRATEGIES: dict[str, tuple[AliasTable, ...]] = {
    "baseline": (),
    "abbreviations": (ABBREVIATIONS,),
    "programming_aliases": (PROGRAMMING_ALIASES,),
    "concept_aliases": (CONCEPT_ALIASES,),
    "combined": (ABBREVIATIONS, PROGRAMMING_ALIASES, CONCEPT_ALIASES),
}


def _term_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)


def expand_query(query: str, tables: tuple[AliasTable, ...]) -> list[QueryVariant]:
    """Generate weighted substitutions without model inference."""
    variants: dict[str, QueryVariant] = {}
    for table in tables:
        for source, aliases in table.items():
            pattern = _term_pattern(source)
            if not pattern.search(query):
                continue
            for alias in aliases:
                expanded = pattern.sub(alias.target, query)
                if expanded.lower() == query.lower():
                    continue
                candidate = QueryVariant(expanded, alias.weight, source, alias.target)
                previous = variants.get(expanded.lower())
                if previous is None or candidate.weight > previous.weight:
                    variants[expanded.lower()] = candidate
    return sorted(variants.values(), key=lambda item: (-item.weight, item.query))


def search_with_aliases(
    units: list[CodeUnit],
    query: str,
    limit: int,
    input_types: list[str] | None,
    return_type: str | None,
    tables: tuple[AliasTable, ...],
) -> list[SearchResult]:
    """Fuse baseline search with conservative expansion bonuses."""
    baseline = search_units(units, query, len(units), input_types, return_type)
    if not tables:
        return baseline[:limit]

    rows: dict[str, dict[str, Any]] = {
        result.unit.unit_id: {
            "result": result,
            "bonus": 0.0,
            "weight": 0.0,
        }
        for result in baseline
    }

    for variant in expand_query(query, tables):
        expanded = search_units(
            units,
            variant.query,
            len(units),
            input_types,
            return_type,
        )
        for expanded_result in expanded:
            row = rows[expanded_result.unit.unit_id]
            baseline_result: SearchResult = row["result"]
            improvement = max(0.0, expanded_result.score - baseline_result.score)
            bonus = improvement * variant.weight * EXPANSION_GAIN_WEIGHT
            if bonus > row["bonus"]:
                row["bonus"] = bonus
                row["weight"] = variant.weight

    results: list[SearchResult] = []
    for row in rows.values():
        baseline_result: SearchResult = row["result"]
        bonus = float(row["bonus"])
        evidence = dict(baseline_result.evidence)
        evidence["alias_bonus"] = bonus
        evidence["alias_weight"] = float(row["weight"])
        results.append(
            SearchResult(
                unit=baseline_result.unit,
                score=min(100.0, baseline_result.score + bonus),
                evidence=evidence,
            )
        )

    results.sort(key=lambda result: (-result.score, result.unit.path, result.unit.start_line))
    return results[:limit]


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


def evaluate_strategy(name: str, tables: tuple[AliasTable, ...]) -> dict[str, Any]:
    """Evaluate one strategy against the frozen retrieval gold set."""
    units, endpoints = index_fixture_repo()
    cases = load_cases()
    validate_cases(cases, {unit.unit_id for unit in units})

    rows: list[dict[str, Any]] = []
    for case in cases:
        started = time.perf_counter()
        results = search_with_aliases(
            units,
            case["query"],
            case.get("limit", 5),
            case.get("input_types", []),
            case.get("return_type", ""),
            tables,
        )
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

    total_candidates = sum(len(row["candidates"]) for row in rows)
    total_traps = sum(row["known_traps_returned"] for row in rows)
    total_redundant = sum(row["known_redundant_candidates"] for row in rows)
    return {
        "strategy": name,
        "summary": {
            "case_count": len(rows),
            "hit_rate_at_k": _mean([float(row["hit"]) for row in rows]),
            "macro_recall_at_k": _mean([row["recall_at_k"] for row in rows]),
            "mrr": _mean([row["reciprocal_rank"] for row in rows]),
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
    """Run every alias strategy without changing Benchmark v1."""
    return {
        "schema_version": 1,
        "experiment": "retrieval-aliases-v1",
        "expansion_gain_weight": EXPANSION_GAIN_WEIGHT,
        "strategies": {
            name: evaluate_strategy(name, tables) for name, tables in STRATEGIES.items()
        },
    }


def main() -> int:
    print(json.dumps(run_comparison(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
