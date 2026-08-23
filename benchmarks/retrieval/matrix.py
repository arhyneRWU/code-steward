"""Retrieval validity matrix (benchmark v2, additive to frozen v1).

Benchmark v1 reports one number on one corpus with one query style.
That single number cannot distinguish "retrieval works" from "the
fixture is easy". This harness reports the same metric surface across
a grid instead:

    documentation  x  query style  x  corpus scale

Nothing here modifies v1. ``benchmarks/retrieval/run.py``,
``benchmarks/retrieval/cases.json``, and
``benchmarks/retrieval/fixture_repo`` are read-only inputs, and
retrieval itself is untouched.

The default pipeline is production ``retrieve_units`` -- the same entry
point ``benchmarks/real_repo/retrieval_baseline.py`` measures -- so
matrix cells are directly comparable to the real-repository baseline.
Pass ``--pipeline search`` to measure bare ``search_units``, which is
what frozen v1 calls.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from code_steward.indexer import index_python_file, iter_python_files
from code_steward.models import CodeUnit, Endpoint, SearchResult
from code_steward.packet import build_packet
from code_steward.retrieval import retrieve_units
from code_steward.search import search_units

from .corpus import ALL_VARIANTS, build_corpus
from .run import CASES_PATH, validate_cases

HERE = Path(__file__).resolve().parent
VERBOSE_CASES_PATH = HERE / "cases_verbose.json"

Pipeline = Callable[[list[CodeUnit], str, int, list[str], str], list[SearchResult]]

PIPELINES: dict[str, Pipeline] = {
    "retrieve": retrieve_units,
    "search": search_units,
}

QUERY_SETS: dict[str, Path] = {
    "short": CASES_PATH,
    "verbose": VERBOSE_CASES_PATH,
}

# Label fields that must be identical between the short and verbose
# sets. Only `query` is allowed to differ; otherwise the two sets
# measure different tasks and the comparison is meaningless.
LABEL_FIELDS = (
    "category",
    "relevant",
    "traps",
    "redundancy_groups",
    "input_types",
    "return_type",
    "limit",
)


def load_case_set(name: str) -> list[dict[str, Any]]:
    """Load one named query set."""
    return json.loads(QUERY_SETS[name].read_text(encoding="utf-8"))


def _labels(case: dict[str, Any]) -> dict[str, Any]:
    return {field: case.get(field) for field in LABEL_FIELDS}


def assert_label_parity() -> None:
    """Fail unless the verbose set differs only in wording.

    Every gold label must be identical to the short set.
    """
    short = {case["id"]: case for case in load_case_set("short")}
    verbose = {case["id"]: case for case in load_case_set("verbose")}
    if short.keys() != verbose.keys():
        missing = sorted(short.keys() ^ verbose.keys())
        raise ValueError(f"Verbose query set case IDs diverge from the gold set: {missing}")
    for case_id, case in short.items():
        if _labels(case) != _labels(verbose[case_id]):
            raise ValueError(f"Verbose case {case_id!r} changed a gold label, not just wording")
        if case["query"] == verbose[case_id]["query"]:
            raise ValueError(f"Verbose case {case_id!r} did not rephrase the query")


def index_tree(root: Path) -> tuple[list[CodeUnit], list[Endpoint]]:
    """Index a corpus tree with the production indexer."""
    units: list[CodeUnit] = []
    endpoints: list[Endpoint] = []
    for path in sorted(iter_python_files(root)):
        file_units, file_endpoints = index_python_file(root, path)
        units.extend(file_units)
        endpoints.extend(file_endpoints)
    return units, endpoints


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _known_redundant_candidates(
    candidate_ids: list[str],
    redundancy_groups: list[list[str]],
) -> int:
    selected = set(candidate_ids)
    return sum(max(0, len(selected & set(group)) - 1) for group in redundancy_groups)


def _hit_at(candidate_ids: list[str], relevant: set[str], k: int) -> bool:
    return bool(relevant & set(candidate_ids[:k]))


def evaluate_case(
    case: dict[str, Any],
    units: list[CodeUnit],
    endpoints: list[Endpoint],
    pipeline: Pipeline,
) -> dict[str, Any]:
    """Run one gold query through ``pipeline`` against one corpus."""
    limit = int(case.get("limit", 5))
    started = time.perf_counter()
    results = pipeline(
        units,
        case["query"],
        limit,
        case.get("input_types", []),
        case.get("return_type", ""),
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    candidate_ids = [result.unit.unit_id for result in results]
    relevant = set(case["relevant"])
    traps = set(case.get("traps", []))
    redundancy_groups = case.get("redundancy_groups", [])
    relevant_found = relevant & set(candidate_ids)
    first_relevant_rank = next(
        (rank for rank, unit_id in enumerate(candidate_ids, 1) if unit_id in relevant),
        None,
    )

    packet = build_packet(
        case["query"],
        results,
        endpoints,
        case.get("input_types", []),
        case.get("return_type", ""),
    )
    packet_text = json.dumps(packet, separators=(",", ":"), sort_keys=True)

    return {
        "id": case["id"],
        "category": case["category"],
        "query": case["query"],
        "query_words": len(case["query"].split()),
        "limit": limit,
        "candidates": candidate_ids,
        "candidate_scores": [round(result.score, 3) for result in results],
        "relevant": sorted(relevant),
        "traps": sorted(traps),
        "redundancy_groups": redundancy_groups,
        "hit_at_1": _hit_at(candidate_ids, relevant, 1),
        "hit_at_3": _hit_at(candidate_ids, relevant, 3),
        "hit_at_5": _hit_at(candidate_ids, relevant, 5),
        "hit_at_k": bool(relevant_found),
        "recall_at_k": len(relevant_found) / len(relevant),
        "reciprocal_rank": 0.0 if first_relevant_rank is None else 1.0 / first_relevant_rank,
        "known_traps_returned": sum(unit_id in traps for unit_id in candidate_ids),
        "known_redundant_candidates": _known_redundant_candidates(
            candidate_ids, redundancy_groups
        ),
        "duplicate_candidates": len(candidate_ids) - len(set(candidate_ids)),
        "candidates_returned": len(candidate_ids),
        "packet_chars": len(packet_text),
        "packet_bytes": len(packet_text.encode("utf-8")),
        "retrieval_ms": elapsed_ms,
        "implementation_bodies_loaded": 0,
    }


def evaluate_cell(
    cases: list[dict[str, Any]],
    units: list[CodeUnit],
    endpoints: list[Endpoint],
    pipeline: Pipeline,
) -> dict[str, Any]:
    """Aggregate one matrix cell over the whole gold set."""
    results = [evaluate_case(case, units, endpoints, pipeline) for case in cases]

    total_candidates = sum(result["candidates_returned"] for result in results)
    total_requested = sum(result["limit"] for result in results)
    total_traps = sum(result["known_traps_returned"] for result in results)
    total_redundant = sum(result["known_redundant_candidates"] for result in results)
    total_duplicates = sum(result["duplicate_candidates"] for result in results)
    unit_count = len(units)

    summary = {
        "case_count": len(results),
        "hit_rate_at_1": _mean([float(result["hit_at_1"]) for result in results]),
        "hit_rate_at_3": _mean([float(result["hit_at_3"]) for result in results]),
        "hit_rate_at_5": _mean([float(result["hit_at_5"]) for result in results]),
        "hit_rate_at_k": _mean([float(result["hit_at_k"]) for result in results]),
        "macro_recall_at_k": _mean([result["recall_at_k"] for result in results]),
        "mrr": _mean([result["reciprocal_rank"] for result in results]),
        "known_trap_rate": total_traps / total_candidates if total_candidates else 0.0,
        "known_redundancy_rate": total_redundant / total_candidates if total_candidates else 0.0,
        "duplicate_candidate_rate": total_duplicates / total_candidates
        if total_candidates
        else 0.0,
        "mean_candidates_returned": _mean(
            [float(result["candidates_returned"]) for result in results]
        ),
        "candidate_fill_rate": total_candidates / total_requested if total_requested else 0.0,
        "mean_packet_chars": _mean([float(result["packet_chars"]) for result in results]),
        "mean_packet_bytes": _mean([float(result["packet_bytes"]) for result in results]),
        "mean_retrieval_ms": _mean([result["retrieval_ms"] for result in results]),
        "mean_query_words": _mean([float(result["query_words"]) for result in results]),
        # The share of the corpus a single packet can show. v1's 20-unit
        # fixture makes this 25-30%; a real repository is nearer 4%.
        "candidate_window": _mean([result["limit"] / unit_count for result in results])
        if unit_count
        else 0.0,
    }
    return {"summary": summary, "cases": results}


def run_matrix(pipeline_name: str = "retrieve") -> dict[str, Any]:
    """Evaluate every corpus variant against every query set."""
    assert_label_parity()
    pipeline = PIPELINES[pipeline_name]

    cells: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="cs-bench-matrix-") as tmp:
        destination = Path(tmp)
        for variant in ALL_VARIANTS:
            root = build_corpus(variant, destination)
            index_started = time.perf_counter()
            units, endpoints = index_tree(root)
            index_ms = (time.perf_counter() - index_started) * 1000.0
            unit_ids = {unit.unit_id for unit in units}
            documented = sum(1 for unit in units if _is_documented(unit))

            for query_set in QUERY_SETS:
                cases = load_case_set(query_set)
                validate_cases(cases, unit_ids)
                cell = evaluate_cell(cases, units, endpoints, pipeline)
                cells.append(
                    {
                        "documentation": variant.documentation,
                        "query_style": query_set,
                        "scale": variant.scale,
                        "corpus": {
                            "files": len(list(iter_python_files(root))),
                            "units": len(units),
                            "documented_units": documented,
                            "documented_share": documented / len(units) if units else 0.0,
                            "endpoints": len(endpoints),
                            "index_ms": index_ms,
                        },
                        **cell,
                    }
                )

    return {
        "schema_version": 1,
        "strategy": f"validity-matrix-{pipeline_name}",
        "pipeline": pipeline_name,
        "axes": {
            "documentation": ["documented", "undocumented"],
            "query_style": list(QUERY_SETS),
            "scale": ["core", "scaled"],
        },
        "cells": cells,
    }


def _is_documented(unit: CodeUnit) -> bool:
    """True when ``purpose`` came from a docstring.

    False when the indexer fell back to the identifier.
    """
    if unit.explicit_region:
        return False
    return unit.purpose.strip().lower() != unit.name.replace("_", " ").strip().lower()


def _matrix_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Retrieval validity matrix ({report['pipeline']})",
        "",
        "| scale | units | window | documentation | query style | words | Hit@1 | Hit@3 "
        "| Hit@5 | Hit@K | recall@K | MRR | traps | redundancy | cands | bytes |",
        "| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: "
        "| ---: | ---: | ---: | ---: |",
    ]
    for cell in report["cells"]:
        summary = cell["summary"]
        lines.append(
            "| {scale} | {units} | {window:.1%} | {doc} | {style} | {words:.1f} "
            "| {h1:.1%} | {h3:.1%} | {h5:.1%} | {hk:.1%} | {rec:.1%} | {mrr:.3f} "
            "| {trap:.1%} | {red:.1%} | {cands:.2f} | {bytes:.0f} |".format(
                scale=cell["scale"],
                units=cell["corpus"]["units"],
                window=summary["candidate_window"],
                doc=cell["documentation"],
                style=cell["query_style"],
                words=summary["mean_query_words"],
                h1=summary["hit_rate_at_1"],
                h3=summary["hit_rate_at_3"],
                h5=summary["hit_rate_at_5"],
                hk=summary["hit_rate_at_k"],
                rec=summary["macro_recall_at_k"],
                mrr=summary["mrr"],
                trap=summary["known_trap_rate"],
                red=summary["known_redundancy_rate"],
                cands=summary["mean_candidates_returned"],
                bytes=summary["mean_packet_bytes"],
            )
        )
    lines.extend(
        [
            "",
            "`window` is `limit / units`: the share of the corpus one packet can show. "
            "The frozen v1 fixture sits near 27%; a real repository is nearer 4%.",
            "",
        ]
    )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pipeline", choices=sorted(PIPELINES), default="retrieve")
    parser.add_argument("--json", action="store_true", help="Emit the full JSON report")
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = run_matrix(args.pipeline)
    markdown = _matrix_markdown(report)

    if args.output_dir is not None:
        output_dir = args.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "retrieval-matrix.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (output_dir / "retrieval-matrix.md").write_text(markdown, encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
