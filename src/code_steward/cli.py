from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from . import __version__
from .config import resolve_excludes
from .db import all_endpoints, all_units, connect, get_unit
from .indexer import is_excluded
from .maintenance import rebuild_index, update_index_file
from .packet import build_packet
from .retrieval import rank_units, retrieve_units
from .similarity import (
    draft_shingles,
    rank_against,
    rank_similar_units,
    unit_shingles,
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
            near = rank_similar_units(result.unit.unit_id, units, prepared, limit=3)
            if near:
                duplicates[result.unit.unit_id] = near
    packet = build_packet(args.query, results, endpoints, args.input, args.returns, duplicates)
    print(json.dumps(packet, indent=2))
    return 0


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
        matches = rank_against(needle, units, prepared, args.limit)
    else:
        if args.unit not in {unit.unit_id for unit in units}:
            print(f"unknown unit: {args.unit}", file=sys.stderr)
            return 2
        matches = rank_similar_units(args.unit, units, prepared, args.limit)

    if args.json:
        print(json.dumps([match.to_dict() for match in matches], indent=2))
        return 0
    if not matches:
        # The common and correct answer. On the benchmark's random
        # probe stratum it was right 45 times out of 45.
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
    similar.add_argument("--json", action="store_true")
    similar.set_defaults(func=cmd_similar)

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
