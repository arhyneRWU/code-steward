"""Measure what a trace bundle saves over reading the files.

`code-steward trace` exists to hand a slice of a repository to a
model that cannot hold the repository. That claim reduces to one
number: how much smaller is the bundle than the files a reader would
otherwise open?

The comparison is deliberately generous to the baseline. "Reading the
files" is counted as the whole content of every file the slice
touches -- which is what an agent without an index actually does,
because it cannot know which of a file's forty functions matter until
it has read them. It is not counted as the concatenated bodies of the
sliced units, which would be a comparison against a tool that already
exists.

Also reported is the share of functions with any resolved neighbour.
Call resolution is conservative, so a slice can be empty because the
function is genuinely isolated or because nothing resolved, and a
compression figure computed over mostly-empty slices would be
meaningless.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from code_steward.db import all_hard_relationships, all_units, connect
from code_steward.similarity import FUNCTION_KINDS
from code_steward.trace import build_slice, render_markdown


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure trace bundle size.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--label", default="")
    parser.add_argument("--prefix", default="", help="only trace units with this ID prefix")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    root = args.root.resolve()
    conn = connect(root / ".code-steward" / "index.sqlite3")
    units = all_units(conn)
    relationships = all_hard_relationships(conn)
    conn.close()

    targets = [
        unit
        for unit in units
        if unit.kind in FUNCTION_KINDS and unit.unit_id.startswith(args.prefix)
    ]
    if not targets:
        raise SystemExit("No function units matched; nothing to measure.")

    sizes = {"bundle": 0, "whole_files": 0}
    # Slices with no resolved neighbour are counted separately. Their
    # "bundle" is one function against a whole file, which compresses
    # spectacularly and says nothing about the follower -- averaging
    # them in would inflate the headline with cases where the feature
    # did nothing.
    linked = {"bundle": 0, "whole_files": 0}
    with_neighbours = 0
    members = 0
    for unit in targets:
        sliced = build_slice(unit.unit_id, units, relationships)
        if sliced is None:
            continue
        bundle = render_markdown(root, sliced)
        paths = {unit.path} | {member.unit.path for member in sliced.members}
        sizes["bundle"] += len(bundle.encode("utf-8"))
        sizes["whole_files"] += sum(
            len((root / path).read_bytes()) for path in paths if (root / path).is_file()
        )
        members += len(sliced.members)
        if sliced.members:
            with_neighbours += 1
            linked["bundle"] += len(bundle.encode("utf-8"))
            linked["whole_files"] += sum(
                len((root / path).read_bytes()) for path in paths if (root / path).is_file()
            )

    total = len(targets)
    payload = {
        "schema_version": 1,
        "label": args.label or root.name,
        "functions": total,
        "with_resolved_neighbours": with_neighbours,
        "resolved_share": round(with_neighbours / total, 3),
        "mean_slice_members": round(members / total, 2),
        "bundle_bytes": sizes["bundle"],
        "whole_file_bytes": sizes["whole_files"],
        "compression": round(sizes["whole_files"] / sizes["bundle"], 2)
        if sizes["bundle"]
        else 0.0,
        "mean_bundle_bytes": sizes["bundle"] // total,
        "linked_only": {
            "functions": with_neighbours,
            "bundle_bytes": linked["bundle"],
            "whole_file_bytes": linked["whole_files"],
            "compression": round(linked["whole_files"] / linked["bundle"], 2)
            if linked["bundle"]
            else 0.0,
            "mean_bundle_bytes": linked["bundle"] // with_neighbours if with_neighbours else 0,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
