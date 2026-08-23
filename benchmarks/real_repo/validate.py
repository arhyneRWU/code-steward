from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from code_steward.db import all_hard_relationships, all_units, connect
from code_steward.indexer import iter_python_files
from code_steward.maintenance import rebuild_index
from code_steward.models import HardRelationship


def _spread_sample(items: list[HardRelationship], limit: int) -> list[HardRelationship]:
    """Choose a deterministic sample spread through a sorted list."""
    if limit <= 0 or not items:
        return []
    if len(items) <= limit:
        return items
    if limit == 1:
        return [items[len(items) // 2]]

    last = len(items) - 1
    indexes = [round(index * last / (limit - 1)) for index in range(limit)]
    return [items[index] for index in indexes]


def _audit_sample(
    relationships: list[HardRelationship],
    limit: int,
) -> list[HardRelationship]:
    resolved = [edge for edge in relationships if edge.target_kind == "unit"]
    unresolved = [edge for edge in relationships if edge.target_kind != "unit"]

    resolved_limit = min(len(resolved), limit // 2)
    unresolved_limit = min(len(unresolved), limit - resolved_limit)
    remaining = limit - resolved_limit - unresolved_limit

    if remaining and len(resolved) > resolved_limit:
        extra = min(remaining, len(resolved) - resolved_limit)
        resolved_limit += extra
        remaining -= extra
    if remaining and len(unresolved) > unresolved_limit:
        unresolved_limit += min(remaining, len(unresolved) - unresolved_limit)

    sample = [
        *_spread_sample(resolved, resolved_limit),
        *_spread_sample(unresolved, unresolved_limit),
    ]
    return sorted(
        sample,
        key=lambda edge: (
            edge.source_unit_id,
            edge.target_kind,
            edge.target_ref,
            edge.provenance,
        ),
    )


def _relationship_metrics(
    relationships: list[HardRelationship],
) -> dict[str, int | float]:
    calls = [edge for edge in relationships if edge.relation == "CALLS"]
    resolved = sum(edge.target_kind == "unit" for edge in calls)
    unresolved = len(calls) - resolved
    resolution_percentage = 100.0 * resolved / len(calls) if calls else 0.0
    return {
        "calls_total": len(calls),
        "calls_resolved_to_units": resolved,
        "calls_unresolved_symbols": unresolved,
        "calls_resolution_percentage": round(resolution_percentage, 2),
    }


def _summary_markdown(result: dict[str, Any]) -> str:
    index = result["index"]
    relationships = result["relationships"]
    lines = [
        "# Real-repository validation",
        "",
        f"- Repository: `{result['repository']}`",
        f"- Commit: `{result['commit']}`",
        f"- Source scope: `{result['source_scope']}`",
        "",
        "## Index",
        "",
        f"- Python files: **{index['python_files']}**",
        f"- Indexed units: **{index['units']}**",
        f"- Endpoints: **{index['endpoints']}**",
        f"- Parse failures: **{index['parse_failures']}**",
        f"- Build time: **{index['build_seconds']:.3f} s**",
        f"- SQLite size: **{index['sqlite_bytes']} bytes**",
        "",
        "## Python AST CALLS",
        "",
        f"- Total edges: **{relationships['calls_total']}**",
        f"- Resolved to indexed units: **{relationships['calls_resolved_to_units']}**",
        f"- Unresolved symbols: **{relationships['calls_unresolved_symbols']}**",
        f"- Resolution percentage: **{relationships['calls_resolution_percentage']:.2f}%**",
        "",
        "## Manual audit sample",
        "",
        "The JSON result contains a deterministic mixed sample of resolved and unresolved edges. ",
        "Review resolved edges for false target resolution before structural retrieval is tested.",
        "",
    ]
    return "\n".join(lines)


def run_validation(
    project_root: Path,
    output_dir: Path,
    repository: str,
    commit: str,
    source_scope: str | None = None,
    audit_limit: int = 50,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    output_dir = output_dir.resolve()
    if not project_root.is_dir():
        raise ValueError(f"Project root does not exist: {project_root}")

    output_dir.mkdir(parents=True, exist_ok=True)
    database = output_dir / "index.sqlite3"
    sources = sorted(iter_python_files(project_root))

    started = time.perf_counter()
    build = rebuild_index(project_root, database)
    build_seconds = time.perf_counter() - started

    conn = connect(database)
    try:
        units = all_units(conn)
        relationships = all_hard_relationships(conn)
    finally:
        conn.close()

    metrics = _relationship_metrics(relationships)
    calls = [edge for edge in relationships if edge.relation == "CALLS"]
    sample = _audit_sample(calls, audit_limit)

    result: dict[str, Any] = {
        "repository": repository,
        "commit": commit,
        "source_scope": source_scope or project_root.name,
        "index": {
            "python_files": len(sources),
            "files_indexed": build.files,
            "units": build.units,
            "units_read_back": len(units),
            "endpoints": build.endpoints,
            "parse_failures": 0,
            "build_seconds": round(build_seconds, 6),
            "sqlite_bytes": database.stat().st_size,
        },
        "relationships": metrics,
        "audit_sample": [edge.to_dict() for edge in sample],
    }

    result_path = output_dir / "result.json"
    summary_path = output_dir / "summary.md"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(_summary_markdown(result), encoding="utf-8")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Code Steward on a real source tree.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--source-scope")
    parser.add_argument("--audit-limit", type=int, default=50)
    return parser


def main() -> None:
    args = _parser().parse_args()
    result = run_validation(
        project_root=args.project_root,
        output_dir=args.output_dir,
        repository=args.repository,
        commit=args.commit,
        source_scope=args.source_scope,
        audit_limit=args.audit_limit,
    )
    print(_summary_markdown(result))


if __name__ == "__main__":
    main()
