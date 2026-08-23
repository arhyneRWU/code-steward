from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from .lexical import query_terms, term_coverage
from .models import CodeUnit, SearchResult

# Optional dependency. Declared as Any first so the real module and
# the None fallback can share a name without redefining it.
fuzz: Any
try:
    from rapidfuzz import fuzz as fuzz
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


# Field weights. `body` was added after the text-search control arm
# beat the five metadata fields on every retrieval metric measured on
# `psf/requests`: Hit@1 46.67% against 53.33%, MRR 0.550 against
# 0.667. The signal the control finds is in code identifiers, which no
# metadata field reads.
#
# The split is 0.50 to the body and 0.50 shared by the five fields in
# their previous proportions. The rationale is stated here because it
# was decided **before** the change was measured and has not been
# revisited since: a control consisting of nothing but body term
# coverage outscored all five fields together, so weighting the body
# equal to the whole existing stack is the least presumptuous reading
# of that result. No weight search was run. Tuning these against the
# benchmark would convert it into a target.
WEIGHTS = {
    "body": 0.500,
    "purpose": 0.175,
    "signature": 0.100,
    "concepts": 0.100,
    "name": 0.075,
    "qualname": 0.050,
}


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
    terms = query_terms(query)
    results: list[SearchResult] = []

    for unit in units:
        concept_text = " ".join(unit.concepts + unit.owns)
        scores = {
            "body": term_coverage(terms, unit.body_terms),
            "name": _ratio(query, unit.name),
            "purpose": max(
                _ratio(query, unit.purpose, "token_set"),
                _ratio(query, unit.doc_text, "token_set") if unit.doc_text else 0.0,
            ),
            "signature": _ratio(query, unit.signature, "token_set"),
            "concepts": _ratio(query, concept_text, "token_set"),
            "qualname": _ratio(query, unit.qualname),
        }
        base = sum(scores[field] * weight for field, weight in WEIGHTS.items())

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
