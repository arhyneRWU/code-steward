"""Generate questions whose answers the call graph already knows.

Stage 1 of `docs/roadmap.md` asks whether an agent **following the
skill** does better work than one without it. Every other number in
this project measures a command; this measures the product.

The questions are chosen so scoring needs no rubric and no labeller.
Each one has a ground-truth answer set of unit IDs derived from the
same `CALLS` and `TESTED_BY` edges the index already stores, so an
answer is scored by set overlap rather than judged.

**The bias this carries, stated before the run rather than after.**
The graph defines truth, and the graph is what the skill exposes, so
the arm using the skill is being scored against its own source. Call
resolution reaches 32.1% of edges, and everything the graph cannot
see -- dynamic dispatch, callables passed as arguments, registry
lookups -- is invisible to the answer key as well. Two mitigations,
both mandatory when reporting:

1. Publish the resolution figure beside the score.
2. Score *extra* units each arm named that the key does not contain,
   separately. An arm that finds real callers the graph missed is
   doing better work, not worse, and a scorer that punishes it is
   measuring the index rather than the agent.

Targets are chosen in hash order so the set is reproducible and was
not picked by looking at the answers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from code_steward.db import all_hard_relationships, all_units, connect
from code_steward.models import CodeUnit, HardRelationship

# A question is only fair if the answer is small enough to state and
# large enough to be worth asking.
MIN_ANSWER = 2
MAX_ANSWER = 12


def _digest(value: str) -> bytes:
    return hashlib.blake2b(value.encode(), digest_size=8).digest()


def _hash_order(unit_ids: list[str]) -> list[str]:
    """Order stably by digest.

    Selection then cannot follow the answers.
    """
    return sorted(unit_ids, key=_digest)


def _edges(relationships: list[HardRelationship], relation: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for edge in relationships:
        if edge.relation == relation and edge.target_kind == "unit":
            out.setdefault(edge.source_unit_id, set()).add(edge.target_ref)
    return out


def _closure(graph: dict[str, set[str]], start: str, depth: int) -> set[str]:
    seen: set[str] = set()
    frontier = {start}
    for _ in range(depth):
        nxt: set[str] = set()
        for node in frontier:
            for neighbour in graph.get(node, ()):
                if neighbour != start and neighbour not in seen:
                    seen.add(neighbour)
                    nxt.add(neighbour)
        frontier = nxt
    return seen


def build_questions(
    units: list[CodeUnit],
    relationships: list[HardRelationship],
    *,
    prefix: str = "",
    limit: int = 15,
    min_answer: int = MIN_ANSWER,
) -> list[dict[str, Any]]:
    """Build questions with a ground-truth answer set for each.

    ``min_answer`` is a parameter rather than a rewritten constant so
    that run 1, which used a floor of two, stays reproducible.
    """
    by_id = {unit.unit_id: unit for unit in units}
    callees = _edges(relationships, "CALLS")
    callers: dict[str, set[str]] = {}
    for source, targets in callees.items():
        for target in targets:
            callers.setdefault(target, set()).add(source)

    eligible = [
        unit.unit_id
        for unit in units
        if unit.kind in {"function", "async_function"} and unit.unit_id.startswith(prefix)
    ]

    questions: list[dict[str, Any]] = []
    for unit_id in _hash_order(eligible):
        if len(questions) >= limit:
            break
        unit = by_id[unit_id]
        for kind, graph, depth, text in (
            (
                "calls",
                callees,
                2,
                "Which functions run as a result of calling `{name}` "
                "({path}:{line})? Include what it calls directly and "
                "what those call in turn.",
            ),
            (
                "impact",
                callers,
                1,
                "Which functions would be affected if the behaviour of "
                "`{name}` ({path}:{line}) changed? Name its direct callers.",
            ),
        ):
            answer = {value for value in _closure(graph, unit_id, depth) if value in by_id}
            if not (min_answer <= len(answer) <= MAX_ANSWER):
                continue
            questions.append(
                {
                    "id": f"{kind}:{unit_id}",
                    "kind": kind,
                    "target": unit_id,
                    "question": text.format(name=unit.name, path=unit.path, line=unit.start_line),
                    "answer": sorted(answer),
                }
            )
            break
    return questions


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build skill A/B questions from an index.")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--prefix", default="", help="restrict targets to this unit-ID prefix")
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument(
        "--min-answer",
        type=int,
        default=MIN_ANSWER,
        help="smallest answer set worth asking about",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    conn = connect(args.root / ".code-steward" / "index.sqlite3")
    units = all_units(conn)
    relationships = all_hard_relationships(conn)
    conn.close()

    questions = build_questions(
        units,
        relationships,
        prefix=args.prefix,
        limit=args.limit,
        min_answer=args.min_answer,
    )
    resolved = sum(
        1 for edge in relationships if edge.relation == "CALLS" and edge.target_kind == "unit"
    )
    total = sum(1 for edge in relationships if edge.relation == "CALLS")
    payload = {
        "schema_version": 1,
        "note": (
            "Ground truth comes from the same graph the skill exposes. "
            "Report edge resolution beside any score, and count units an "
            "arm named that the key does not contain rather than "
            "punishing them."
        ),
        "edge_resolution": round(resolved / total, 4) if total else 0.0,
        "questions": questions,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(questions)} questions, edge resolution {payload['edge_resolution']:.1%}")


if __name__ == "__main__":
    main()
