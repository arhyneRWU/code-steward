from __future__ import annotations

from typing import Any

from .models import Endpoint, SearchResult


def build_packet(
    task: str,
    results: list[SearchResult],
    endpoints: list[Endpoint],
    input_types: list[str] | None = None,
    return_type: str | None = None,
) -> dict[str, Any]:
    endpoint_by_unit: dict[str, list[str]] = {}
    for endpoint in endpoints:
        endpoint_by_unit.setdefault(endpoint.unit_id, []).append(
            f"{endpoint.method} {endpoint.route}"
        )

    candidates = []
    for result in results:
        unit = result.unit
        candidates.append(
            {
                "unit": unit.unit_id,
                "score": round(result.score, 1),
                "kind": unit.kind,
                "path": unit.path,
                "lines": f"{unit.start_line}:{unit.end_line}",
                "signature": unit.signature,
                "purpose": unit.purpose,
                "concepts": unit.concepts[:8],
                "owns": unit.owns[:6],
                "not_owns": unit.not_owns[:6],
                "dependencies": unit.dependencies[:8],
                "endpoints": endpoint_by_unit.get(unit.unit_id, []),
                "hash": unit.body_hash,
                "git": unit.git_file_commit,
            }
        )

    return {
        "task": task,
        "expected": {"inputs": input_types or [], "returns": return_type or ""},
        "candidates": candidates,
        "review_contract": {
            "decisions": ["REUSE", "EXTEND", "REFACTOR", "CREATE", "UNCERTAIN"],
            "instruction": "Read implementation bodies only when summaries are insufficient.",
        },
    }
