"""Replay real commits through `check` and count what it would say.

`docs/check.md` reports that 30-60% of functions in a real repository
already overlap another one. That number is what made `check` a
report rather than a gate. It is also an upper bound on the wrong
thing: a developer does not touch every function in a repository,
they touch a handful, and most of those already had whatever overlap
they have.

So this replays actual commits. For each one the parent is indexed,
the commit's changed files are checked against it, and the findings
are counted twice -- once counting every overlap, once counting only
the overlaps the commit introduced.

The gap between those two columns is what the introduced-only
default is worth. If it is small, the filter is not earning its
complexity.

Nothing here is labelled, so neither column is an error rate. Both
are alarm rates: how often the command would have said something.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from code_steward.check import check_files
from code_steward.db import all_units, connect
from code_steward.maintenance import rebuild_index
from code_steward.similarity import REUSE_FLOOR


def _git(repo: Path, *argv: str) -> str:
    result = subprocess.run(["git", *argv], cwd=repo, capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else ""


def commits_with_python_changes(repo: Path, limit: int) -> list[str]:
    """Most recent commits that touch at least one Python file."""
    out = _git(repo, "log", "--format=%H", "-n", str(limit * 4), "--", "*.py")
    return [line for line in out.splitlines() if line][:limit]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay commits through check.")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--commits", type=int, default=40)
    parser.add_argument("--label", default="")
    # Read from the flag rather than the checked-out tree's config:
    # older commits predate a repository's exclude settings, so the
    # config at the parent is not a reliable source while replaying.
    parser.add_argument(
        "--exclude", action="append", default=[], help="path prefix to keep out of the index"
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    repo = args.repo.resolve()
    original = _git(repo, "rev-parse", "HEAD").strip()
    if not original:
        raise SystemExit(f"not a git repository with history: {repo}")

    totals = {"commits": 0, "functions": 0, "all_overlaps": 0, "introduced": 0}
    per_commit: list[dict[str, Any]] = []
    index = repo / ".code-steward" / "index.sqlite3"

    try:
        for sha in commits_with_python_changes(repo, args.commits):
            parent = _git(repo, "rev-parse", f"{sha}^").strip()
            if not parent:
                continue
            changed = [
                repo / name
                for name in _git(
                    repo, "diff", "--name-only", "--diff-filter=d", parent, sha, "--", "*.py"
                ).splitlines()
            ]
            if not changed:
                continue

            # Index the parent, then check the commit against it --
            # exactly the state a developer is in mid-change.
            _git(repo, "checkout", "-q", "--detach", parent)
            rebuild_index(repo, index, tuple(args.exclude))
            _git(repo, "checkout", "-q", "--detach", sha)

            conn = connect(index)
            units = all_units(conn)
            conn.close()
            present = [path for path in changed if path.is_file()]
            if not present:
                continue

            every, checked = check_files(repo, present, units, floor=REUSE_FLOOR)
            new_only, _ = check_files(repo, present, units, floor=REUSE_FLOOR, base=parent)

            totals["commits"] += 1
            totals["functions"] += checked
            totals["all_overlaps"] += len(every)
            totals["introduced"] += len(new_only)
            per_commit.append(
                {
                    "commit": sha[:12],
                    "functions": checked,
                    "all_overlaps": len(every),
                    "introduced": len(new_only),
                }
            )
            print(f"{sha[:12]}: {checked} fn, {len(every)} all, {len(new_only)} new", flush=True)
    finally:
        _git(repo, "checkout", "-q", "--detach", original)

    functions = totals["functions"]
    payload = {
        "schema_version": 1,
        "label": args.label or repo.name,
        "floor": REUSE_FLOOR,
        "note": "Alarm rates, not error rates. Nothing here is labelled.",
        "totals": totals,
        "rate_all_overlaps": round(totals["all_overlaps"] / functions, 4) if functions else 0.0,
        "rate_introduced": round(totals["introduced"] / functions, 4) if functions else 0.0,
        "commits_with_any_finding": {
            "all_overlaps": sum(1 for row in per_commit if row["all_overlaps"]),
            "introduced": sum(1 for row in per_commit if row["introduced"]),
        },
        "per_commit": per_commit,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {key: value for key, value in payload.items() if key != "per_commit"}
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
