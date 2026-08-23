"""Check the code you just wrote against the code already there.

This is the workflow the measurements actually support. Comparing a
*drafted sketch* against the repository finds the existing duplicate
0.460 of the time end to end. Comparing the **real body** finds it
1.000 of the time on the same sample, and 0.994 over the larger one.
The difference is not the comparison; it is how much of the function
exists when you run it.

So the useful moment is not before the code is written. It is after
it is written and before it is kept -- at which point a real body
exists, the comparison is at its strongest, and the finding is still
cheap to act on. `docs/verdict.md` carries both numbers.

Nothing here is new machinery. It is the same index, the same
five-token comparison, and the same relevance floor, pointed at the
working tree instead of at a sketch.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .indexer import index_python_file
from .models import CodeUnit
from .similarity import (
    FUNCTION_KINDS,
    MIN_LINES,
    REUSE_FLOOR,
    Ranking,
    SimilarUnit,
    rank_with_floor,
    unit_shingles,
)


@dataclass(slots=True, frozen=True)
class Finding:
    """One changed function and what it already overlaps."""

    unit: CodeUnit
    matches: list[SimilarUnit]
    below_floor: int

    def to_dict(self) -> dict[str, object]:
        return {
            "unit": self.unit.unit_id,
            "path": self.unit.path,
            "lines": f"{self.unit.start_line}:{self.unit.end_line}",
            "signature": self.unit.signature,
            "overlaps": [
                {
                    "unit": row.unit.unit_id,
                    "path": row.unit.path,
                    "lines": f"{row.unit.start_line}:{row.unit.end_line}",
                    "score": round(row.score, 2),
                }
                for row in self.matches
            ],
        }


def changed_python_files(project_root: Path, base: str) -> list[Path]:
    """List Python files this working tree changes against ``base``.

    Deleted files are excluded -- there is nothing to compare -- and
    so is anything outside the project root. A repository without the
    base ref yields nothing rather than raising: a missing branch is
    a normal state, not a failure of the check.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=d", f"{base}...HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        tracked = result.stdout.splitlines() if result.returncode == 0 else []
        # Uncommitted work is the common case for this command, so the
        # unstaged and staged diffs are included alongside the branch.
        for extra in (
            ["git", "diff", "--name-only", "--diff-filter=d"],
            ["git", "diff", "--name-only", "--diff-filter=d", "--cached"],
        ):
            more = subprocess.run(
                extra, cwd=project_root, capture_output=True, text=True, check=False
            )
            if more.returncode == 0:
                tracked.extend(more.stdout.splitlines())
    except OSError:
        return []

    seen: dict[str, Path] = {}
    for name in tracked:
        if not name.endswith(".py"):
            continue
        path = (project_root / name).resolve()
        if path.is_file():
            seen[name] = path
    return [seen[name] for name in sorted(seen)]


def alarm_rate(
    project_root: Path,
    indexed: list[CodeUnit],
    *,
    floor: float = REUSE_FLOOR,
) -> tuple[int, int]:
    """Count how many indexed functions overlap another one.

    This is the number that decides whether `check` is worth leaving
    switched on, and it is a property of the repository rather than
    of the tool. Measured at the shipped floor it ranges from 14% on
    a small single-purpose codebase to 63% on Airflow's providers,
    where near-identical operators are the intended design.

    A user should not have to take that range on trust, so the tool
    reports it for their repository rather than the doc quoting
    someone else's.
    """
    prepared = unit_shingles(project_root, indexed, cache=True)
    functions = [unit for unit in indexed if unit.kind in FUNCTION_KINDS]
    fired = 0
    for unit in functions:
        needle = prepared.get(unit.unit_id, frozenset())
        if not needle:
            continue
        if rank_with_floor(needle, indexed, prepared, 1, unit.unit_id, floor=floor).matches:
            fired += 1
    return fired, len(functions)


def _baseline_units(project_root: Path, path: Path, base: str) -> dict[str, frozenset[int]] | None:
    """Shingle every function in ``path`` as it exists at ``base``.

    Returns None when there is no baseline -- a new file, an
    unreadable ref, or a version that does not parse. None and an
    empty dict mean different things to the caller: None is "this
    function had no previous version, so every overlap it has is
    new", and an empty dict is "it had one and it contained nothing".
    """
    try:
        rel = path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return None
    result = subprocess.run(
        ["git", "show", f"{base}:{rel}"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None

    # The scratch file must survive until the shingles are built:
    # unit_shingles re-reads each unit's path from disk rather than
    # holding the source it was parsed from.
    scratch = project_root / ".code-steward" / "_baseline.py"
    try:
        scratch.parent.mkdir(parents=True, exist_ok=True)
        scratch.write_text(result.stdout, encoding="utf-8")
        units, _ = index_python_file(project_root, scratch)
        prepared = unit_shingles(project_root, units, cache=False)
    except (SyntaxError, UnicodeDecodeError, ValueError, OSError):
        return None
    finally:
        scratch.unlink(missing_ok=True)
    # Key on the bare function name. The unit ID embeds the module
    # path, which the scratch file changes, and a rename is meant to
    # read as a new function anyway.
    return {unit.name: prepared[unit.unit_id] for unit in units if unit.unit_id in prepared}


def check_files(
    project_root: Path,
    paths: list[Path],
    indexed: list[CodeUnit],
    *,
    floor: float = REUSE_FLOOR,
    limit: int = 3,
    base: str = "",
) -> tuple[list[Finding], int]:
    """Compare every function in ``paths`` against the index.

    Returns the findings and the number of functions checked. A
    function is compared against the index with **itself excluded by
    unit ID**: a file already indexed at an older revision would
    otherwise match its own previous version at close to 1.0 and
    report every edit as a duplicate.

    When ``base`` is set, only overlaps the change *introduced* are
    reported. A function that already duplicated something before it
    was touched is not the author's finding, and on a repository
    whose baseline duplication runs to 30-60% -- measured, see
    `docs/check.md` -- that distinction is most of the difference
    between a report worth reading and noise.

    An overlap counts as introduced when the previous version of the
    same function did not have it. A function with no previous
    version has introduced all of them.
    """
    prepared = unit_shingles(project_root, indexed, cache=True)
    findings: list[Finding] = []
    checked = 0

    for path in paths:
        try:
            units, _ = index_python_file(project_root, path)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            # A file that does not parse is the author's problem and
            # not this command's. Skip it rather than failing the run.
            continue
        local = unit_shingles(project_root, units, cache=False)
        before = _baseline_units(project_root, path, base) if base else None

        for unit in units:
            if unit.kind not in FUNCTION_KINDS:
                continue
            if unit.end_line - unit.start_line + 1 < MIN_LINES:
                continue
            needle = local.get(unit.unit_id, frozenset())
            if not needle:
                continue
            checked += 1
            ranking: Ranking = rank_with_floor(
                needle, indexed, prepared, limit, unit.unit_id, floor=floor
            )
            matches = ranking.matches
            if base and before is not None and unit.name in before:
                already = {
                    row.unit.unit_id
                    for row in rank_with_floor(
                        before[unit.name],
                        indexed,
                        prepared,
                        # Unlimited, so a pre-existing overlap pushed
                        # off the end of the old top-N does not come
                        # back looking newly introduced.
                        len(indexed),
                        unit.unit_id,
                        floor=floor,
                    ).matches
                }
                matches = [row for row in matches if row.unit.unit_id not in already]
            if matches:
                findings.append(Finding(unit, matches, ranking.below_floor))

    findings.sort(key=lambda row: -row.matches[0].score)
    return findings, checked
