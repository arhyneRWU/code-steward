"""Follow one function through its callers, callees, and tests.

The oldest idea in this project and the last one built: take a
function, walk out to everything that calls it and everything it
calls, and hand the whole path over as one self-contained bundle.

It exists for a specific job -- **handing a slice of a repository to a
model that cannot hold the repository.** A smaller or cheaper model
can reason about a function it can see in full, together with the
callers whose expectations it must not break. It cannot do that from
a file list, and it should not have to read six files to assemble
what the index already knows.

This is deterministic graph traversal over the `CALLS` and
`TESTED_BY` edges the indexer already extracts. Nothing here ranks,
scores, or guesses.

**What the graph can and cannot see.** Call resolution is AST-based
and conservative: a call is an edge only when the target resolves to
an indexed unit. Dynamic dispatch, callables passed as arguments, and
registry lookups produce no edge. Absolute imports into a
``src/``-layout package also fail to resolve, which costs test edges
in particular. So a slice is a **lower bound on the real path** and
the header says how many edges it walked, so the reader can tell a
small slice from a broken one.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .models import CodeUnit, HardRelationship

# Roles a unit can hold in a slice, in the order they are rendered.
# The target first, then what it depends on, then what depends on it,
# then the tests that pin it.
ROLE_ORDER = ("target", "callee", "caller", "test")


@dataclass(slots=True, frozen=True)
class SliceMember:
    """One unit in a slice, and why it is there."""

    unit: CodeUnit
    role: str
    depth: int
    # Lines where the call actually happens: in this unit for a
    # caller, in the target for a callee. A reader handed a
    # forty-line caller should not have to hunt for the one line
    # that matters, which is the whole point of a follower.
    call_lines: tuple[int, ...] = ()


@dataclass(slots=True)
class Slice:
    """A function and the path around it."""

    target: CodeUnit
    members: list[SliceMember]
    edges_walked: int
    truncated: bool = False

    @property
    def by_role(self) -> dict[str, list[SliceMember]]:
        grouped: dict[str, list[SliceMember]] = {role: [] for role in ROLE_ORDER}
        for member in self.members:
            grouped.setdefault(member.role, []).append(member)
        return grouped


def _call_edges(
    relationships: list[HardRelationship],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Index resolved CALLS edges in both directions."""
    callees: dict[str, list[str]] = {}
    callers: dict[str, list[str]] = {}
    for edge in relationships:
        if edge.relation != "CALLS" or edge.target_kind != "unit":
            continue
        callees.setdefault(edge.source_unit_id, []).append(edge.target_ref)
        callers.setdefault(edge.target_ref, []).append(edge.source_unit_id)
    return callees, callers


def _call_sites(relationships: list[HardRelationship]) -> dict[tuple[str, str], tuple[int, ...]]:
    """Map each (caller, callee) pair to the lines where it calls."""
    sites: dict[tuple[str, str], tuple[int, ...]] = {}
    for edge in relationships:
        if edge.relation != "CALLS" or edge.target_kind != "unit":
            continue
        lines = edge.evidence.get("lines") if isinstance(edge.evidence, dict) else None
        if not lines:
            continue
        key = (edge.source_unit_id, edge.target_ref)
        merged = sorted({*sites.get(key, ()), *(int(value) for value in lines)})
        sites[key] = tuple(merged)
    return sites


def _tests_for(relationships: list[HardRelationship], unit_id: str) -> list[str]:
    return [
        edge.target_ref
        for edge in relationships
        if edge.relation == "TESTED_BY"
        and edge.target_kind == "unit"
        and edge.source_unit_id == unit_id
    ]


def build_slice(
    unit_id: str,
    units: list[CodeUnit],
    relationships: list[HardRelationship],
    *,
    callers_depth: int = 1,
    callees_depth: int = 1,
    include_tests: bool = True,
    limit: int = 40,
) -> Slice | None:
    """Walk out from ``unit_id`` and collect the path around it.

    Breadth-first in both directions so a shallow, widely-used
    function does not push its own direct callers out of a truncated
    slice. Returns None when the unit is not indexed.
    """
    by_id = {unit.unit_id: unit for unit in units}
    target = by_id.get(unit_id)
    if target is None:
        return None

    callees, callers = _call_edges(relationships)
    sites = _call_sites(relationships)
    seen = {unit_id}
    members: list[SliceMember] = []
    edges_walked = 0
    truncated = False

    for role, graph, max_depth in (
        ("callee", callees, callees_depth),
        ("caller", callers, callers_depth),
    ):
        queue: deque[tuple[str, int]] = deque([(unit_id, 0)])
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbour in graph.get(current, []):
                edges_walked += 1
                if neighbour in seen or neighbour not in by_id:
                    continue
                if len(members) >= limit:
                    truncated = True
                    break
                seen.add(neighbour)
                # For a caller the site is in the neighbour; for a
                # callee it is in the unit doing the calling.
                pair = (neighbour, current) if role == "caller" else (current, neighbour)
                members.append(SliceMember(by_id[neighbour], role, depth + 1, sites.get(pair, ())))
                queue.append((neighbour, depth + 1))
            if truncated:
                break

    if include_tests and not truncated:
        for test_id in _tests_for(relationships, unit_id):
            edges_walked += 1
            if test_id in seen or test_id not in by_id:
                continue
            if len(members) >= limit:
                truncated = True
                break
            seen.add(test_id)
            members.append(SliceMember(by_id[test_id], "test", 1))

    order = {role: index for index, role in enumerate(ROLE_ORDER)}
    members.sort(key=lambda row: (order.get(row.role, 9), row.depth, row.unit.unit_id))
    return Slice(target=target, members=members, edges_walked=edges_walked, truncated=truncated)


def unit_source(project_root: Path, unit: CodeUnit) -> str:
    """Read exactly one unit's lines from the working tree."""
    try:
        lines = (project_root / unit.path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""
    return "\n".join(lines[unit.start_line - 1 : unit.end_line])


def render_markdown(project_root: Path, sliced: Slice, *, source: bool = True) -> str:
    """Render a slice as a bundle a model can be handed directly."""
    out: list[str] = []
    target = sliced.target
    out.append(f"# {target.unit_id}")
    out.append("")
    out.append(f"`{target.path}:{target.start_line}-{target.end_line}`")
    if target.purpose:
        out.append("")
        out.append(target.purpose)

    grouped = sliced.by_role
    counts = ", ".join(
        f"{len(grouped[role])} {role}{'s' if len(grouped[role]) != 1 else ''}"
        for role in ROLE_ORDER
        if role != "target" and grouped[role]
    )
    out.append("")
    out.append(
        f"_Slice: {counts or 'no resolved neighbours'}; {sliced.edges_walked} edge(s) walked._"
    )
    # Call resolution is conservative, so an empty slice is ambiguous
    # between "nothing calls this" and "nothing resolved". Say so
    # rather than letting the reader assume the first.
    if not sliced.members:
        out.append("")
        out.append(
            "> No resolved neighbours. Calls made through dynamic dispatch, "
            "callables passed as arguments, registry lookups, or metaclass "
            "machinery do not resolve, so this may be incomplete rather "
            "than isolated."
        )
    if sliced.truncated:
        out.append("")
        out.append("> Truncated at the slice limit; raise `--limit` to see the rest.")

    out.append("")
    out.append("---")
    out.append("")
    out.append("## target")
    out.append("")
    out.append(f"### {target.unit_id}")
    out.append("")
    if source:
        out.append("```python")
        out.append(unit_source(project_root, target))
        out.append("```")
    else:
        out.append(f"`{target.signature}`")

    for role in ROLE_ORDER:
        if role == "target" or not grouped[role]:
            continue
        out.append("")
        out.append(f"## {role}s")
        for member in grouped[role]:
            unit = member.unit
            out.append("")
            out.append(f"### {unit.unit_id}")
            out.append("")
            location = f"`{unit.path}:{unit.start_line}-{unit.end_line}` · depth {member.depth}"
            if member.call_lines:
                where = ", ".join(str(line) for line in member.call_lines)
                verb = "calls the target at" if role == "caller" else "called from"
                location += f" · {verb} line {where}"
            out.append(location)
            if unit.purpose:
                out.append("")
                out.append(unit.purpose)
            out.append("")
            if source:
                out.append("```python")
                out.append(unit_source(project_root, unit))
                out.append("```")
            else:
                out.append(f"`{unit.signature}`")

    return "\n".join(out) + "\n"


def slice_to_dict(sliced: Slice) -> dict[str, object]:
    """Structured form, for a caller assembling its own prompt."""
    return {
        "target": sliced.target.unit_id,
        "edges_walked": sliced.edges_walked,
        "truncated": sliced.truncated,
        "members": [
            {
                "unit": member.unit.unit_id,
                "role": member.role,
                "depth": member.depth,
                "path": member.unit.path,
                "lines": f"{member.unit.start_line}:{member.unit.end_line}",
                "signature": member.unit.signature,
                "purpose": member.unit.purpose,
                "call_lines": list(member.call_lines),
            }
            for member in sliced.members
        ],
    }
