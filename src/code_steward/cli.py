from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from . import __version__
from .check import alarm_rate, changed_python_files, check_files
from .config import resolve_excludes
from .db import all_endpoints, all_hard_relationships, all_units, connect, get_unit
from .indexer import index_python_file, is_excluded
from .maintenance import rebuild_index, update_index_file
from .packet import DUPLICATE_LIMIT, build_packet
from .retrieval import rank_units, retrieve_units
from .similarity import (
    REUSE_FLOOR,
    draft_shingles,
    rank_with_floor,
    unit_shingles,
)
from .trace import (
    build_slice,
    path_duplication,
    render_duplication,
    render_markdown,
    slice_to_dict,
    undocumented_units,
)


def root_from(value: str | None) -> Path:
    return Path(value or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()


def db_path(root: Path) -> Path:
    return root / ".code-steward" / "index.sqlite3"


def cmd_build(args: argparse.Namespace) -> int:
    root = root_from(args.root)
    destination = db_path(root)
    try:
        stats = rebuild_index(root, destination, resolve_excludes(root, args.exclude))
    except (OSError, sqlite3.Error, SyntaxError, UnicodeDecodeError, ValueError) as exc:
        if not args.quiet:
            print(f"build failed: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(
            f"indexed {stats.units} units, {stats.endpoints} endpoints "
            f"from {stats.files} Python files"
        )
        if stats.skipped:
            # Reported, never silent: an index that quietly covers
            # less than the tree cannot be told from one that covers
            # all of it, and "not found" would then mean two things.
            print(f"skipped {len(stats.skipped)} file(s) that could not be indexed:")
            for entry in stats.skipped[:10]:
                print(f"  {entry.path}: {entry.reason}")
            if len(stats.skipped) > 10:
                print(f"  ... and {len(stats.skipped) - 10} more")
        print(destination)
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    root = root_from(args.root)
    db = db_path(root)
    if args.if_exists and not db.exists():
        return 0

    path = Path(args.path).resolve()
    if path.suffix != ".py":
        return 0
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return 0

    if is_excluded(root, path, resolve_excludes(root, args.exclude)):
        return 0

    if not path.exists() and not db.exists():
        return 0

    conn = connect(db)
    try:
        stats = update_index_file(conn, root, path)
    except (OSError, sqlite3.Error, SyntaxError, UnicodeDecodeError, ValueError) as exc:
        if not args.quiet:
            print(f"could not update {path}: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    if not args.quiet:
        if path.exists():
            print(f"updated {stats.primary_units} units from {rel}")
        else:
            print(f"removed {rel} from index")
    return 0


def _load(root: Path):
    db = db_path(root)
    if not db.exists():
        raise SystemExit(f"index not found: {db}\nRun: code-steward build")
    conn = connect(db)
    return conn, all_units(conn), all_endpoints(conn)


def _search(args: argparse.Namespace, *, compact: bool = False):
    root = root_from(args.root)
    _, units, endpoints = _load(root)
    retriever = retrieve_units if compact else rank_units
    results = retriever(units, args.query, args.limit, args.input, args.returns)
    return endpoints, results


def cmd_search(args: argparse.Namespace) -> int:
    _, results = _search(args)
    if args.json:
        print(json.dumps([result.to_dict() for result in results], indent=2))
        return 0
    for result in results:
        unit = result.unit
        signature = f" | {unit.signature}" if unit.signature else ""
        print(
            f"{result.score:5.1f}  {unit.unit_id}  [{unit.body_hash}]\n"
            f"       {unit.purpose}{signature}"
        )
    return 0


def cmd_packet(args: argparse.Namespace) -> int:
    endpoints, results = _search(args, compact=True)
    duplicates = None
    if args.reuse:
        root = root_from(args.root)
        conn, units, _ = _load(root)
        conn.close()
        prepared = unit_shingles(root, units, cache=True)
        duplicates = {}
        for result in results:
            near = rank_with_floor(
                prepared.get(result.unit.unit_id, frozenset()),
                units,
                prepared,
                DUPLICATE_LIMIT,
                result.unit.unit_id,
            )
            if near.matches:
                duplicates[result.unit.unit_id] = near.matches
    packet = build_packet(args.query, results, endpoints, args.input, args.returns, duplicates)
    print(json.dumps(packet, indent=2))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Compare functions changed in this tree against the index."""
    root = root_from(args.root)
    conn, units, _ = _load(root)
    conn.close()

    if args.rate:
        fired, total = alarm_rate(root, units, floor=args.floor)
        share = fired / total if total else 0.0
        print(
            f"{fired} of {total} indexed function(s) overlap another "
            f"at floor {args.floor:.2f} ({share:.1%})"
        )
        print(
            "This is your repository's baseline duplication, not a fault. "
            "A high share means `check` will fire often on new code, and "
            "--fail-on-overlap is probably not worth switching on."
        )
        return 0

    paths = (
        [Path(name).resolve() for name in args.paths]
        if args.paths
        else changed_python_files(root, args.base)
    )
    if not paths:
        print("no changed Python files")
        return 0

    findings, checked = check_files(
        root,
        paths,
        units,
        floor=args.floor,
        limit=args.limit,
        base="" if args.all_overlaps else args.base,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "checked": checked,
                    "floor": args.floor,
                    "findings": [finding.to_dict() for finding in findings],
                },
                indent=2,
            )
        )
        return 1 if findings and args.fail_on_overlap else 0

    scope = "overlap existing code" if args.all_overlaps else "introduce new overlap"
    if not findings:
        # An assertion, not a failed search. The floor is what makes
        # it one: spurious matches were measured at roughly 0.6%.
        print(f"{checked} changed function(s) checked, none {scope}")
        return 0

    for finding in findings:
        print(f"{finding.unit.path}:{finding.unit.start_line}  {finding.unit.name}")
        for row in finding.matches:
            print(
                f"    {row.score:.2f}  {row.unit.unit_id}  ({row.unit.path}:{row.unit.start_line})"
            )
    print(f"\n{len(findings)} of {checked} changed function(s) {scope}")
    if not args.all_overlaps:
        print("Overlaps that predate the change are hidden; --all-overlaps shows them.")
    return 1 if args.fail_on_overlap else 0


def cmd_similar(args: argparse.Namespace) -> int:
    """Find indexed units whose body overlaps a unit or a draft."""
    root = root_from(args.root)
    conn, units, _ = _load(root)
    conn.close()
    prepared = unit_shingles(root, units, cache=True)

    if args.draft is not None:
        source = sys.stdin.read() if args.draft == "-" else Path(args.draft).read_text("utf-8")
        try:
            needle = draft_shingles(source)
        except SyntaxError as error:
            print(f"draft does not parse: {error}", file=sys.stderr)
            return 2
        if not needle:
            print("draft is too small to compare", file=sys.stderr)
            return 0
        exclude = ""
    else:
        if args.unit not in {unit.unit_id for unit in units}:
            print(f"unknown unit: {args.unit}", file=sys.stderr)
            return 2
        needle = prepared.get(args.unit, frozenset())
        exclude = args.unit

    ranking = rank_with_floor(needle, units, prepared, args.limit, exclude, floor=args.floor)
    matches = ranking.matches

    if args.json:
        print(json.dumps(ranking.to_dict(), indent=2))
        return 0
    if not matches:
        # A complete answer, not a failed search. The floor is what
        # lets the tool assert this rather than hand over its best
        # weak candidates and leave the judgement to the reader.
        if ranking.below_floor:
            noun = "candidate" if ranking.below_floor == 1 else "candidates"
            print(
                f"nothing above the {ranking.floor:.2f} floor "
                f"({ranking.below_floor} weaker {noun} suppressed)"
            )
        else:
            print("no existing unit overlaps this one")
        return 0
    for match in matches:
        unit = match.unit
        print(
            f"{match.score:5.2f}  {unit.unit_id}\n"
            f"       {unit.path}:{unit.start_line}-{unit.end_line}"
            f"  ({match.shared_shingles} shared windows)"
        )
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    """Emit one function plus the path around it as a bundle."""
    root = root_from(args.root)
    conn, units, _ = _load(root)
    relationships = all_hard_relationships(conn)
    conn.close()

    def slice_for(unit_id: str):
        return build_slice(
            unit_id,
            units,
            relationships,
            callers_depth=args.callers,
            callees_depth=args.callees,
            include_tests=not args.no_tests,
            limit=args.limit,
        )

    if args.undocumented:
        if args.base:
            # A changed file's indexed units carry line numbers from
            # a prior revision, and a function *added* by the change
            # is not in the index at all -- which is the certain case
            # for this command. Re-parse, exactly as `check` does,
            # and let the fresh units win.
            changed = changed_python_files(root, args.base)
            fresh: list = []
            for path in changed:
                try:
                    parsed, _ = index_python_file(root, path)
                except (SyntaxError, UnicodeDecodeError, ValueError):
                    # A file that does not parse is the author's
                    # problem, not this command's.
                    continue
                fresh.extend(parsed)
            changed_paths = {path.resolve() for path in changed}
            units = [
                unit for unit in units if (root / unit.path).resolve() not in changed_paths
            ] + fresh
            targets = undocumented_units(fresh)
        else:
            targets = undocumented_units(units)
        if not targets:
            print("no undocumented functions in scope")
            return 0
        bundles = [sliced for unit in targets if (sliced := slice_for(unit.unit_id))]
        if args.json:
            print(json.dumps([slice_to_dict(one) for one in bundles], indent=2))
            return 0
        # A separator, because the reader is a model being handed
        # several bundles at once and needs to know where one ends.
        rendered = []
        for one in bundles:
            body = render_markdown(root, one, source=not args.signatures)
            if args.dry:
                body += "\n" + render_duplication(path_duplication(root, one, units))
            rendered.append(body)
        print("\n---\n\n".join(rendered), end="")
        return 0

    if not args.unit:
        print("trace needs a unit ID, or --undocumented", file=sys.stderr)
        return 2

    sliced = slice_for(args.unit)
    if sliced is None:
        print(f"unknown unit: {args.unit}", file=sys.stderr)
        return 2

    overlaps = path_duplication(root, sliced, units) if args.dry else []
    if args.json:
        payload = slice_to_dict(sliced)
        if args.dry:
            payload["duplication"] = [
                {
                    "unit": overlap.unit.unit_id,
                    "overlaps": [
                        {"unit": match.unit.unit_id, "score": round(match.score, 2)}
                        for match in overlap.matches
                    ],
                }
                for overlap in overlaps
            ]
        print(json.dumps(payload, indent=2))
        return 0
    print(render_markdown(root, sliced, source=not args.signatures), end="")
    if args.dry:
        print()
        print(render_duplication(overlaps), end="")
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    root = root_from(args.root)
    conn, _, _ = _load(root)
    unit = get_unit(conn, args.unit)
    if not unit:
        print(f"unknown unit: {args.unit}", file=sys.stderr)
        return 2
    path = root / unit.path
    lines = path.read_text(encoding="utf-8").splitlines()
    selected = lines[unit.start_line - 1 : unit.end_line]
    if args.header:
        print(
            f"# unit: {unit.unit_id}\n"
            f"# source: {unit.path}:{unit.start_line}-{unit.end_line}\n"
            f"# hash: {unit.body_hash}"
        )
    print("\n".join(selected))
    return 0


def cmd_endpoints(args: argparse.Namespace) -> int:
    root = root_from(args.root)
    _, _, endpoints = _load(root)
    if args.json:
        print(json.dumps([endpoint.to_dict() for endpoint in endpoints], indent=2))
    else:
        for endpoint in endpoints:
            print(f"{endpoint.method:7} {endpoint.route:36} {endpoint.unit_id}")
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    root = root_from(args.root)
    _, units, endpoints = _load(root)
    endpoint_map: dict[str, list[str]] = {}
    for endpoint in endpoints:
        endpoint_map.setdefault(endpoint.unit_id, []).append(f"{endpoint.method} {endpoint.route}")
    output = ["# Code Steward Map", "", f"Generated from `{root.name}`.", ""]
    current_path = None
    for unit in units:
        if unit.path != current_path:
            current_path = unit.path
            output.extend([f"## `{current_path}`", ""])
        output.append(f"### `{unit.unit_id}`")
        summary = f"`{unit.kind}` · lines {unit.start_line}-{unit.end_line} · `{unit.body_hash}`"
        if unit.git_file_commit:
            summary += f" · git `{unit.git_file_commit}`"
        output.append(summary)
        if unit.signature:
            output.append(f"`{unit.signature}`")
        output.append("")
        output.append(unit.purpose or "No purpose summary.")
        if endpoint_map.get(unit.unit_id):
            output.append(
                "API: " + ", ".join(f"`{value}`" for value in endpoint_map[unit.unit_id])
            )
        output.append("")
    destination = Path(args.output) if args.output else root / ".code-steward" / "CODEMAP.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(destination)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code-steward",
        description="Context-efficient code intelligence and stewardship for coding agents.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--root", help="project root; defaults to CLAUDE_PROJECT_DIR or cwd")
    sub = parser.add_subparsers(dest="command", required=True)

    exclude_help = (
        "path fragment to skip; repeatable and added to "
        "[tool.code-steward] exclude in pyproject.toml"
    )

    build = sub.add_parser("build", help="build or rebuild the Python code-unit index")
    build.add_argument("--exclude", action="append", default=[], help=exclude_help)
    build.add_argument("--quiet", action="store_true")
    build.set_defaults(func=cmd_build)

    update = sub.add_parser("update", help="incrementally re-index one Python file")
    update.add_argument("path")
    update.add_argument("--exclude", action="append", default=[], help=exclude_help)
    update.add_argument(
        "--if-exists", action="store_true", help="do nothing until an index exists"
    )
    update.add_argument("--quiet", action="store_true")
    update.set_defaults(func=cmd_update)

    def add_search_args(command: argparse.ArgumentParser) -> None:
        command.add_argument("query")
        command.add_argument("--limit", type=int, default=8)
        command.add_argument(
            "--input", action="append", default=[], help="expected input type; repeatable"
        )
        command.add_argument("--returns", default="", help="expected return type")

    search = sub.add_parser("search", help="rank existing code units for an intent")
    add_search_args(search)
    search.add_argument("--json", action="store_true")
    search.set_defaults(func=cmd_search)

    packet = sub.add_parser("packet", help="emit a compact reuse-review packet")
    add_search_args(packet)
    packet.add_argument(
        "--reuse",
        action="store_true",
        help="attach near-duplicate evidence to each candidate",
    )
    packet.set_defaults(func=cmd_packet)

    similar = sub.add_parser(
        "similar", help="find existing units whose body a new one would duplicate"
    )
    similar.add_argument("unit", nargs="?", help="an indexed unit ID")
    similar.add_argument(
        "--draft",
        metavar="FILE",
        help="compare a function you have not written yet; '-' reads stdin",
    )
    similar.add_argument("--limit", type=int, default=8)
    similar.add_argument(
        "--floor",
        type=float,
        default=REUSE_FLOOR,
        metavar="SCORE",
        help=f"discard matches below this overlap (default {REUSE_FLOOR})",
    )
    similar.add_argument("--json", action="store_true")
    similar.set_defaults(func=cmd_similar)

    check = sub.add_parser(
        "check", help="compare functions you changed against the existing index"
    )
    check.add_argument(
        "paths", nargs="*", help="files to check; defaults to what this tree changes"
    )
    check.add_argument("--base", default="main", help="branch to diff against (default main)")
    check.add_argument(
        "--all-overlaps",
        action="store_true",
        help="report every overlap, not only the ones this change introduced",
    )
    check.add_argument("--limit", type=int, default=3)
    check.add_argument(
        "--floor",
        type=float,
        default=REUSE_FLOOR,
        metavar="SCORE",
        help=f"discard overlaps below this score (default {REUSE_FLOOR})",
    )
    check.add_argument(
        "--fail-on-overlap",
        action="store_true",
        help="exit 1 when an overlap is found, for use in a hook or CI",
    )
    check.add_argument(
        "--rate",
        action="store_true",
        help="report how much of the whole index already overlaps, and exit",
    )
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=cmd_check)

    trace = sub.add_parser(
        "trace", help="bundle one function with its callers, callees, and tests"
    )
    trace.add_argument("unit", nargs="?", help="an indexed unit ID")
    trace.add_argument(
        "--undocumented",
        action="store_true",
        help="bundle every function that has no docstring, instead of one unit",
    )
    trace.add_argument(
        "--base",
        default="",
        help="with --undocumented, only functions in files changed since this ref",
    )
    trace.add_argument(
        "--dry",
        action="store_true",
        help="also report duplication across every unit on the path",
    )
    trace.add_argument("--callers", type=int, default=1, help="how far to walk up (default 1)")
    trace.add_argument("--callees", type=int, default=1, help="how far to walk down (default 1)")
    trace.add_argument("--limit", type=int, default=40, help="maximum units in the slice")
    trace.add_argument("--no-tests", action="store_true", help="leave TESTED_BY units out")
    trace.add_argument(
        "--signatures", action="store_true", help="signatures instead of full bodies"
    )
    trace.add_argument("--json", action="store_true")
    trace.set_defaults(func=cmd_trace)

    read = sub.add_parser("read", help="extract exactly one indexed code unit")
    read.add_argument("unit")
    read.add_argument("--header", action="store_true")
    read.set_defaults(func=cmd_read)

    endpoints = sub.add_parser("endpoints", help="show FastAPI endpoints found by AST")
    endpoints.add_argument("--json", action="store_true")
    endpoints.set_defaults(func=cmd_endpoints)

    code_map = sub.add_parser("map", help="export a compact Markdown code map")
    code_map.add_argument("--output")
    code_map.set_defaults(func=cmd_map)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "similar" and not args.unit and args.draft is None:
        parser.error("similar needs a unit ID or --draft")
    return int(args.func(args))
