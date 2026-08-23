"""Run the pre-registered context-cost measurement.

`docs/context-cost.md` fixes the design; this executes it. Four arms
per target, paired, over a hash-ordered sample of functions both
tools resolve to the same declaration.

Nothing here decides anything. It writes bytes, tokens and coverage
per target to JSON, and the scoring is a separate step so a bad
result cannot be quietly re-run into a good one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from code_steward.db import all_hard_relationships, all_units, connect
from code_steward.models import CodeUnit
from code_steward.trace import Slice, SliceMember, build_slice, render_markdown

from .arms import PATTERNS, GcrNode, caller_index, query, span_bytes

TARGET_KINDS = frozenset({"function", "async_function", "method"})


def _digest(value: str) -> bytes:
    return hashlib.blake2b(value.encode(), digest_size=8).digest()


def _their_nodes(graph_db: Path, root: Path) -> dict[tuple[str, str], str]:
    """Map (relative path, name) to their qualified name."""
    conn = sqlite3.connect(graph_db)
    out: dict[tuple[str, str], str] = {}
    for name, qualified, file_path in conn.execute(
        "select name, qualified_name, file_path from nodes where kind in ('Function', 'Test')"
    ):
        try:
            relative = str(Path(file_path).relative_to(root))
        except ValueError:
            relative = str(file_path)
        out[(relative, name)] = qualified
    conn.close()
    return out


def _as_slice(
    target: CodeUnit,
    nodes: list[GcrNode],
    by_key: dict[tuple[str, str], CodeUnit],
    roles: dict[str, str],
) -> Slice:
    """Render their selection through our bundle, for arm D."""
    members: list[SliceMember] = []
    seen: set[str] = {target.unit_id}
    for node in nodes:
        unit = by_key.get((node.path, node.name))
        if unit is None or unit.unit_id in seen:
            continue
        seen.add(unit.unit_id)
        # No call sites: their nodes carry spans, not the line inside
        # a caller where the call happens. Disclosed in the design.
        members.append(
            SliceMember(unit=unit, role=roles.get(node.qualified_name, "caller"), depth=1)
        )
    return Slice(target=target, members=members, edges_walked=len(members))


def measure(
    root: Path,
    units: list[CodeUnit],
    relationships: list[Any],
    target: CodeUnit,
    their_name: str,
    key: set[tuple[str, str]],
) -> dict[str, Any]:
    """One target, four arms, scored against an independent key."""
    by_key = {(unit.path, unit.name): unit for unit in units}

    ours = build_slice(target.unit_id, units, relationships)
    arm_a = render_markdown(root, ours) if ours is not None else ""
    our_callers = (
        [m.unit for m in ours.members if m.role in {"caller", "test"}] if ours is not None else []
    )

    raw_total = 0
    their_nodes: list[GcrNode] = []
    their_callers: list[GcrNode] = []
    roles: dict[str, str] = {}
    for pattern in PATTERNS:
        raw, nodes = query(root, pattern, their_name)
        raw_total += len(raw.encode("utf-8"))
        role = {"callers_of": "caller", "callees_of": "callee"}[pattern]
        for node in nodes:
            roles.setdefault(node.qualified_name, role)
        if role == "caller":
            their_callers.extend(nodes)
        their_nodes.extend(nodes)

    arm_c_bytes = raw_total + span_bytes(root, their_nodes)
    hybrid = _as_slice(target, their_nodes, by_key, roles)
    arm_d = render_markdown(root, hybrid)
    # The hybrid can only carry nodes that map onto one of our units.
    # Assuming it inherits their recall would beg the question the
    # decision table asks, so it is scored on what it actually holds.
    hybrid_callers = {
        (m.unit.path, m.unit.name) for m in hybrid.members if m.role in {"caller", "test"}
    }

    ours_claimed = {(unit.path, unit.name) for unit in our_callers}
    theirs_claimed = {(node.path, node.name) for node in their_callers}

    def recall(claimed: set[tuple[str, str]]) -> float | None:
        return round(len(claimed & key) / len(key), 4) if key else None

    return {
        "target": target.unit_id,
        "their_target": their_name,
        "key_size": len(key),
        "arms": {
            "A_code_steward": {"bytes": len(arm_a.encode("utf-8")), "named": len(our_callers)},
            "B_gcr_delivered": {"bytes": raw_total, "named": len(their_callers)},
            "C_gcr_sufficient": {"bytes": arm_c_bytes, "named": len(their_callers)},
            "D_hybrid": {"bytes": len(arm_d.encode("utf-8")), "named": len(their_nodes)},
        },
        "recall": {
            "A_code_steward": recall(ours_claimed),
            "C_gcr_sufficient": recall(theirs_claimed),
            "D_hybrid": recall(hybrid_callers),
        },
        # Claims absent from the independent key. Reported, not
        # folded into a score: the key misses dynamic dispatch too.
        "outside_key": {
            "A_code_steward": len(ours_claimed - key),
            "C_gcr_sufficient": len(theirs_claimed - key),
            "D_hybrid": len(hybrid_callers - key),
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the context-cost measurement.")
    parser.add_argument("--root", type=Path, required=True, help="corpus checkout")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    root = args.root.resolve()
    conn = connect(root / ".code-steward" / "index.sqlite3")
    units = all_units(conn)
    relationships = all_hard_relationships(conn)
    conn.close()

    theirs = _their_nodes(root / ".code-review-graph" / "graph.db", root)
    files = sorted({Path(unit.path) for unit in units})
    index = caller_index(root, files)

    counts: dict[str, int] = {}
    for unit in units:
        if unit.kind in TARGET_KINDS:
            counts[unit.name] = counts.get(unit.name, 0) + 1

    eligible = [unit for unit in units if unit.kind in TARGET_KINDS]
    # Unique names only: the key is name-based and is exact only
    # where the name is. Disclosed in the pre-registration, along
    # with the fact that it favours their arm.
    matched = [
        (unit, theirs[(unit.path, unit.name)])
        for unit in eligible
        if (unit.path, unit.name) in theirs and counts.get(unit.name) == 1
    ]
    matched.sort(key=lambda pair: _digest(pair[0].unit_id))

    rows = []
    for position, (unit, their_name) in enumerate(matched[: args.limit], start=1):
        key = {pair for pair in index.get(unit.name, set()) if pair != (unit.path, unit.name)}
        rows.append(measure(root, units, relationships, unit, their_name, key))
        if position % 25 == 0:
            print(f"{position} / {min(args.limit, len(matched))}", flush=True)

    payload = {
        "schema_version": 1,
        "corpus": str(root.name),
        "eligible_units": len(eligible),
        "matched_units": len(matched),
        "unique_name_units": sum(1 for u in eligible if counts.get(u.name) == 1),
        "match_rate": round(len(matched) / len(eligible), 4) if eligible else 0.0,
        "targets": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(rows)} targets, match rate {payload['match_rate']:.1%}")


if __name__ == "__main__":
    main()
