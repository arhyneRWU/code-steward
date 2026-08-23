"""Emit blind labeling sheets so packet precision can be measured.

Hit@K asks only whether the one gold unit appeared. It says nothing
about the other seven units in an eight-unit packet, so a packet of
seven near-misses and a packet of seven unrelated functions score
identically. Precision cannot be computed from the current labels.

This module produces the input for fixing that. For each case it pools
the candidates returned by every arm under test, strips which arm
produced each one, hides which unit is gold, orders them by a hash of
the pair so the sequence carries no ranking signal, and attaches the
real source of each unit.

The blinding is the point. A labeler who can see that a unit was
ranked first by the system under evaluation, or that it is the
recorded gold answer, is no longer an independent judge of relevance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The label vocabulary. Deliberately three-valued: forcing a binary
# choice would push every defensible near-miss into whichever bucket
# the labeler happens to favour, and the near-misses are exactly the
# population this measurement exists to size.
LABELS = ("relevant", "plausible", "irrelevant")

LABEL_GUIDANCE = """\
relevant   -- answers the query; an agent could act on this unit.
plausible  -- related and worth a look, but not the answer; a
              reasonable agent would read it and move on.
irrelevant -- noise; reading this unit was wasted effort.
"""


@dataclass(slots=True, frozen=True)
class UnitSource:
    unit_id: str
    path: str
    start_line: int
    end_line: int
    source: str


def load_unit_sources(database: Path, project_root: Path) -> dict[str, UnitSource]:
    """Read every indexed unit's real source text."""
    conn = sqlite3.connect(database)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT unit_id, path, start_line, end_line FROM units").fetchall()
    finally:
        conn.close()

    cache: dict[str, list[str]] = {}
    sources: dict[str, UnitSource] = {}
    for row in rows:
        path = row["path"]
        lines = cache.get(path)
        if lines is None:
            lines = (project_root / path).read_text(encoding="utf-8").splitlines()
            cache[path] = lines
        body = "\n".join(lines[row["start_line"] - 1 : row["end_line"]])
        sources[row["unit_id"]] = UnitSource(
            unit_id=row["unit_id"],
            path=path,
            start_line=row["start_line"],
            end_line=row["end_line"],
            source=body,
        )
    return sources


def blind_order(case_id: str, unit_ids: set[str]) -> list[str]:
    """Order candidates by a hash of the pair, not by any arm's rank.

    Sorting by unit ID would leak nothing about rank but would cluster
    a module's units together, which is its own nudge. Hashing the
    (case, unit) pair gives a stable order that carries no signal and
    reproduces exactly on every machine.
    """
    return sorted(
        unit_ids,
        key=lambda unit_id: hashlib.sha256(f"{case_id}\x00{unit_id}".encode()).hexdigest(),
    )


def build_sheet(
    cases: list[dict[str, Any]],
    arms: dict[str, list[dict[str, Any]]],
    sources: dict[str, UnitSource],
) -> dict[str, Any]:
    """Build one blind sheet per case from the union of all arms."""
    by_case: dict[str, set[str]] = {}
    for arm_cases in arms.values():
        for case in arm_cases:
            by_case.setdefault(case["id"], set()).update(case["candidates"])

    sheets = []
    for case in cases:
        case_id = case["id"]
        candidates = by_case.get(case_id, set())
        missing = sorted(candidates - set(sources))
        if missing:
            values = ", ".join(missing)
            raise ValueError(f"Case {case_id!r} names units absent from the index: {values}")

        sheets.append(
            {
                "case_id": case_id,
                "query": case["query"],
                # No "relevant", no "traps", no arm names, no ranks.
                "candidates": [
                    {
                        "unit_id": unit_id,
                        "path": sources[unit_id].path,
                        "lines": [
                            sources[unit_id].start_line,
                            sources[unit_id].end_line,
                        ],
                        "source": sources[unit_id].source,
                    }
                    for unit_id in blind_order(case_id, candidates)
                ],
            }
        )

    return {
        "schema_version": 1,
        "labels": list(LABELS),
        "guidance": LABEL_GUIDANCE,
        "arms_pooled": sorted(arms),
        "case_count": len(sheets),
        "candidate_count": sum(len(sheet["candidates"]) for sheet in sheets),
        "sheets": sheets,
    }


def _load_arm(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit blind candidate labeling sheets for packet precision."
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument(
        "--arm",
        action="append",
        required=True,
        metavar="NAME=REPORT.json",
        help="a baseline report to pool candidates from; repeatable",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    arms: dict[str, list[dict[str, Any]]] = {}
    for entry in args.arm:
        name, _, report_path = entry.partition("=")
        if not name or not report_path:
            raise SystemExit(f"--arm expects NAME=REPORT.json, got {entry!r}")
        arms[name] = _load_arm(Path(report_path).resolve())

    cases = json.loads(args.cases.resolve().read_text(encoding="utf-8"))
    sources = load_unit_sources(args.database.resolve(), args.project_root.resolve())
    sheet = build_sheet(cases, arms, sources)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sheet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"{sheet['case_count']} cases, {sheet['candidate_count']} candidates "
        f"pooled from {', '.join(sheet['arms_pooled'])} -> {args.output}"
    )


if __name__ == "__main__":
    main()
