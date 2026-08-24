"""Adjudicate the unique-name rule against an oracle that is not it.

Pre-registered in `docs/unique-name-resolution.md`. For each sampled
`obj.method()` call site whose method name is unique in the index,
Jedi is asked where the attribute actually resolves, and its answer
is compared with the unit the rule would pick.

Jedi infers types. The rule matches names. That difference is the
whole reason this measurement means anything: a name-based key would
have agreed with a name-based rule on every case.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import jedi

from code_steward.db import all_units, connect
from code_steward.models import CodeUnit

from .candidates import Candidate, attribute_call_sites, unique_names

CONFIRMED = "confirmed"
CONTRADICTED = "contradicted"
UNVERIFIED = "unverified"


def _digest(value: str) -> bytes:
    return hashlib.blake2b(value.encode(), digest_size=8).digest()


def classify(
    root: Path,
    project: jedi.Project,
    candidate: Candidate,
    target: CodeUnit,
    sources: dict[str, str],
) -> tuple[str, str]:
    """Ask the oracle, and say which class the answer falls in."""
    source = sources[candidate.path]
    try:
        script = jedi.Script(code=source, path=str(root / candidate.path), project=project)
        found = script.goto(candidate.line, candidate.column, follow_imports=True)
    except Exception as error:  # jedi raises a wide range on odd input
        return UNVERIFIED, f"oracle error: {type(error).__name__}"
    if not found:
        return UNVERIFIED, "oracle resolved nothing"
    for definition in found:
        module = definition.module_path
        if module is None:
            continue
        try:
            relative = str(Path(module).relative_to(root))
        except ValueError:
            # Resolved outside the corpus: stdlib or a third party.
            # The rule would have claimed one of our units for it,
            # so this counts against the rule.
            return CONTRADICTED, f"outside the corpus: {Path(module).name}"
        if relative == target.path and target.start_line <= definition.line <= target.end_line:
            return CONFIRMED, f"{relative}:{definition.line}"
        return CONTRADICTED, f"{relative}:{definition.line} not {target.path}:{target.start_line}"
    return UNVERIFIED, "oracle gave no module path"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Adjudicate the unique-name rule.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument(
        "--exclude",
        type=Path,
        default=None,
        help="a context-cost run whose targets this sample must avoid",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    root = args.root.resolve()
    conn = connect(root / ".code-steward" / "index.sqlite3")
    units = all_units(conn)
    conn.close()

    names = unique_names(units)
    by_name = {unit.name: unit for unit in units if unit.name in names}

    spent: set[str] = set()
    if args.exclude is not None:
        payload = json.loads(args.exclude.read_text(encoding="utf-8"))
        spent = {row["target"] for row in payload["targets"]}

    files = sorted({Path(unit.path) for unit in units})
    candidates = [
        candidate
        for candidate in attribute_call_sites(root, files, names)
        if by_name[candidate.attribute].unit_id not in spent
    ]
    candidates.sort(key=lambda item: _digest(f"{item.path}:{item.line}:{item.column}"))
    sample = candidates[: args.limit]

    project = jedi.Project(str(root))
    sources = {
        candidate.path: (root / candidate.path).read_text(encoding="utf-8") for candidate in sample
    }

    rows: list[dict[str, Any]] = []
    for position, candidate in enumerate(sample, start=1):
        target = by_name[candidate.attribute]
        verdict, detail = classify(root, project, candidate, target, sources)
        rows.append(
            {
                "site": f"{candidate.path}:{candidate.line}",
                "attribute": candidate.attribute,
                "rule_would_pick": target.unit_id,
                "verdict": verdict,
                "detail": detail,
            }
        )
        if position % 25 == 0:
            print(f"{position} / {len(sample)}", flush=True)

    payload = {
        "schema_version": 1,
        "population": len(candidates),
        "sampled": len(rows),
        "excluded_targets": len(spent),
        "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    counts = {
        name: sum(1 for row in rows if row["verdict"] == name)
        for name in (CONFIRMED, CONTRADICTED, UNVERIFIED)
    }
    print(counts)


if __name__ == "__main__":
    main()
