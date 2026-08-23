from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from .models import CodeUnit, SearchResult
from .search import search_units


@dataclass(frozen=True, slots=True)
class RetrievalPolicy:
    """Deterministic controls for the production retrieval pipeline."""

    expansion_gain_weight: float = 0.45
    similarity_threshold: float = 0.78


DEFAULT_POLICY = RetrievalPolicy()


@dataclass(frozen=True, slots=True)
class Alias:
    """One weighted query replacement."""

    target: str
    weight: float


@dataclass(frozen=True, slots=True)
class QueryVariant:
    """One explainable query expansion."""

    query: str
    weight: float
    source: str
    target: str


AliasTable = dict[str, tuple[Alias, ...]]

_ABBREVIATIONS: AliasTable = {
    "app": (Alias("application", 0.95),),
    "repo": (Alias("repository", 0.95),),
    "cfg": (Alias("config", 0.95), Alias("configuration", 0.85)),
    "auth": (Alias("authentication", 0.90),),
}

_PROGRAMMING_ALIASES: AliasTable = {
    "save": (
        Alias("persist", 0.90),
        Alias("write", 0.85),
        Alias("store", 0.75),
    ),
    "read": (
        Alias("load", 0.90),
        Alias("retrieve", 0.85),
        Alias("fetch", 0.80),
    ),
    "remove": (Alias("delete", 0.90), Alias("evict", 0.85)),
    "log out": (
        Alias("revoke session", 0.90),
        Alias("invalidate session", 0.85),
        Alias("logout", 0.80),
        Alias("sign out", 0.80),
    ),
    "inventory": (Alias("catalog", 0.85), Alias("enumerate", 0.80)),
}

_ALIAS_TABLES = (_ABBREVIATIONS, _PROGRAMMING_ALIASES)


def _term_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)


def expand_query(query: str) -> list[QueryVariant]:
    """Return narrow deterministic query variants."""
    variants: dict[str, QueryVariant] = {}
    for table in _ALIAS_TABLES:
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


def rank_units(
    units: list[CodeUnit],
    query: str,
    limit: int = 8,
    input_types: list[str] | None = None,
    return_type: str | None = None,
    *,
    policy: RetrievalPolicy = DEFAULT_POLICY,
) -> list[SearchResult]:
    """Rank code units with baseline evidence plus query expansion."""
    if limit <= 0 or not units:
        return []

    baseline = search_units(units, query, len(units), input_types, return_type)
    rows: dict[str, dict[str, Any]] = {
        result.unit.unit_id: {
            "result": result,
            "bonus": 0.0,
            "weight": 0.0,
        }
        for result in baseline
    }

    for variant in expand_query(query):
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
            bonus = improvement * variant.weight * policy.expansion_gain_weight
            if bonus > row["bonus"]:
                row["bonus"] = bonus
                row["weight"] = variant.weight

    results: list[SearchResult] = []
    for row in rows.values():
        baseline_result = row["result"]
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


def _metadata_text(unit: CodeUnit) -> str:
    values = [unit.name, unit.qualname, unit.purpose, *unit.concepts]
    return " ".join(value for value in values if value)


def metadata_similarity(left: CodeUnit, right: CodeUnit) -> float:
    """Estimate near-duplicate intent from indexed metadata."""
    semantic = fuzz.token_set_ratio(_metadata_text(left), _metadata_text(right)) / 100.0
    signature = fuzz.token_set_ratio(left.signature, right.signature) / 100.0
    return semantic * 0.85 + signature * 0.15


def select_review_candidates(
    ranked: list[SearchResult],
    limit: int,
    *,
    policy: RetrievalPolicy = DEFAULT_POLICY,
) -> list[SearchResult]:
    """Remove near-duplicate candidates from the top review window."""
    if limit <= 0:
        return []

    selected: list[SearchResult] = []
    for candidate in ranked[:limit]:
        if any(
            metadata_similarity(candidate.unit, existing.unit) >= policy.similarity_threshold
            for existing in selected
        ):
            continue
        selected.append(candidate)
    return selected


def retrieve_units(
    units: list[CodeUnit],
    query: str,
    limit: int = 8,
    input_types: list[str] | None = None,
    return_type: str | None = None,
    *,
    policy: RetrievalPolicy = DEFAULT_POLICY,
) -> list[SearchResult]:
    """Run the production low-context retrieval pipeline."""
    if limit <= 0 or not units:
        return []

    ranked = rank_units(
        units,
        query,
        len(units),
        input_types,
        return_type,
        policy=policy,
    )
    return select_review_candidates(ranked, limit, policy=policy)
