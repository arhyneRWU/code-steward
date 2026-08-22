from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .db import all_endpoints, all_units, connect, get_unit, replace_file
from .indexer import index_python_file, iter_python_files
from .packet import build_packet
from .search import search_units


def root_from(value: str | None) -> Path:
    return Path(value or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()


def db_path(root: Path) -> Path:
    return root / ".code-steward" / "index.sqlite3"


def cmd_build(args: argparse.Namespace) -> int:
    root = root_from(args.root)
    conn = connect(db_path(root))
    count_units = count_files = count_endpoints = 0
    for path in iter_python_files(root, args.exclude):
        try:
            units, endpoints = index_python_file(root, path)
        except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
            if not args.quiet:
                print(f"skip {path}: {exc}", file=sys.stderr)
            continue
        rel = path.relative_to(root).as_posix()
        replace_file(conn, rel, units, endpoints)
        count_files += 1
        count_units += len(units)
        count_endpoints += len(endpoints)
    if not args.quiet:
        print(
            f"indexed {count_units} units, {count_endpoints} endpoints "
            f"from {count_files} Python files"
        )
        print(db_path(root))
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    root = root_from(args.root)
    db = db_path(root)
    if args.if_exists and not db.exists():
        return 0
    path = Path(args.path).resolve()
    if path.suffix != ".py" or not path.exists():
        return 0
    try:
        path.relative_to(root)
    except ValueError:
        return 0
    conn = connect(db)
    try:
        units, endpoints = index_python_file(root, path)
    except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
        if not args.quiet:
            print(f"could not index {path}: {exc}", file=sys.stderr)
        return 1
    replace_file(conn, path.relative_to(root).as_posix(), units, endpoints)
    if not args.quiet:
        print(f"updated {len(units)} units from {path.relative_to(root)}")
    return 0


def _load(root: Path):
    db = db_path(root)
    if not db.exists():
        raise SystemExit(f"index not found: {db}\nRun: code-steward build")
    conn = connect(db)
    return conn, all_units(conn), all_endpoints(conn)


def _search(args: argparse.Namespace):
    root = root_from(args.root)
    _, units, endpoints = _load(root)
    results = search_units(units, args.query, args.limit, args.input, args.returns)
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
    endpoints, results = _search(args)
    packet = build_packet(args.query, results, endpoints, args.input, args.returns)
    print(json.dumps(packet, indent=2))
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
            output.append("API: " + ", ".join(f"`{value}`" for value in endpoint_map[unit.unit_id]))
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

    build = sub.add_parser("build", help="build or rebuild the Python code-unit index")
    build.add_argument("--exclude", action="append", default=[])
    build.add_argument("--quiet", action="store_true")
    build.set_defaults(func=cmd_build)

    update = sub.add_parser("update", help="incrementally re-index one Python file")
    update.add_argument("path")
    update.add_argument("--if-exists", action="store_true", help="do nothing until an index exists")
    update.add_argument("--quiet", action="store_true")
    update.set_defaults(func=cmd_update)

    def add_search_args(command: argparse.ArgumentParser) -> None:
        command.add_argument("query")
        command.add_argument("--limit", type=int, default=8)
        command.add_argument("--input", action="append", default=[], help="expected input type; repeatable")
        command.add_argument("--returns", default="", help="expected return type")

    search = sub.add_parser("search", help="rank existing code units for an intent")
    add_search_args(search)
    search.add_argument("--json", action="store_true")
    search.set_defaults(func=cmd_search)

    packet = sub.add_parser("packet", help="emit a compact reuse-review packet")
    add_search_args(packet)
    packet.set_defaults(func=cmd_packet)

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
    return int(args.func(args))
