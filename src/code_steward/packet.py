from __future__ import annotations

from typing import Any

from .models import Endpoint, SearchResult
from .similarity import SimilarUnit

# How many near-duplicates to name per candidate. The point is to tell
# a reviewer that a candidate is one of several copies, not to list
# every copy: three is enough to change a REUSE into a REFACTOR, and
# the rest are bytes the reviewer pays for and does not act on.
DUPLICATE_LIMIT = 3


def build_packet(
    task: str,
    results: list[SearchResult],
    endpoints: list[Endpoint],
    input_types: list[str] | None = None,
    return_type: str | None = None,
    duplicates: dict[str, list[SimilarUnit]] | None = None,
) -> dict[str, Any]:
    """Assemble a compact reviewer packet from ranked candidates.

    ``duplicates`` is optional reuse evidence keyed by unit ID. When
    present, each candidate carries the indexed units its body already
    overlaps. That is the difference between "this function does what
    you need" and "this function does what you need and there are
    three more like it" -- the first is a REUSE, the second is closer
    to a REFACTOR, and a reviewer cannot tell them apart from the
    candidate alone.
    """
    endpoint_by_unit: dict[str, list[str]] = {}
    for endpoint in endpoints:
        endpoint_by_unit.setdefault(endpoint.unit_id, []).append(
            f"{endpoint.method} {endpoint.route}"
        )

    overlaps = duplicates or {}
    candidates = []
    for result in results:
        unit = result.unit
        near = overlaps.get(unit.unit_id, [])
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
                # Omitted rather than empty when no evidence was
                # gathered. An empty list would claim "checked, found
                # none", which is a different fact from "not checked".
                **(
                    {
                        "duplicates": [
                            {
                                "unit": row.unit.unit_id,
                                "overlap": round(row.score, 2),
                            }
                            for row in near[:DUPLICATE_LIMIT]
                        ]
                    }
                    if near
                    else {}
                ),
            }
        )

    return {
        "task": task,
        "expected": {"inputs": input_types or [], "returns": return_type or ""},
        "candidates": candidates,
        "review_contract": {
            "decisions": ["REUSE", "EXTEND", "REFACTOR", "CREATE", "UNCERTAIN"],
            "instruction": "Read implementation bodies only when summaries are insufficient.",
            **(
                {
                    "duplicates_note": (
                        "A candidate with duplicates already exists more than once. "
                        "Prefer REFACTOR over REUSE when reusing it would add a copy."
                    )
                }
                if duplicates
                else {}
            ),
        },
    }
