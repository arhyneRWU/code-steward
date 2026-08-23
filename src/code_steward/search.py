from __future__ import annotations

from difflib import SequenceMatcher

from .models import CodeUnit, SearchResult

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover
    fuzz = None


def _ratio(a: str, b: str, mode: str = "wratio") -> float:
    if not a or not b:
        return 0.0
    if fuzz is None:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100.0
    if mode == "token_set":
        return float(fuzz.token_set_ratio(a, b))
    return float(fuzz.WRatio(a, b))


def _types(unit: CodeUnit) -> set[str]:
    return {row.get("type", "") for row in unit.parameters if row.get("type")}


def search_units(
    units: list[CodeUnit],
    query: str,
    limit: int = 8,
    input_types: list[str] | None = None,
    return_type: str | None = None,
) -> list[SearchResult]:
    """Score code units by lexical and typed metadata similarity."""
    input_types = [value for value in (input_types or []) if value]
    results: list[SearchResult] = []

    for unit in units:
        concept_text = " ".join(unit.concepts + unit.owns)
        scores = {
            "name": _ratio(query, unit.name),
            "purpose": _ratio(query, unit.purpose, "token_set"),
            "signature": _ratio(query, unit.signature, "token_set"),
            "concepts": _ratio(query, concept_text, "token_set"),
            "qualname": _ratio(query, unit.qualname),
        }
        base = (
            scores["name"] * 0.15
            + scores["purpose"] * 0.35
            + scores["signature"] * 0.20
            + scores["concepts"] * 0.20
            + scores["qualname"] * 0.10
        )

        bonus = 0.0
        unit_types = _types(unit)
        if input_types:
            matches = sum(
                1
                for expected in input_types
                if expected in unit_types or any(expected in actual for actual in unit_types)
            )
            bonus += min(12.0, matches * 6.0)
        if return_type and unit.returns:
            if return_type == unit.returns:
                bonus += 12.0
            elif return_type in unit.returns or unit.returns in return_type:
                bonus += 6.0

        score = min(100.0, base + bonus)
        results.append(
            SearchResult(unit=unit, score=score, evidence={**scores, "type_bonus": bonus})
        )

    results.sort(key=lambda result: (-result.score, result.unit.path, result.unit.start_line))
    return results[:limit]
