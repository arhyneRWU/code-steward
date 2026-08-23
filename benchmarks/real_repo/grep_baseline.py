"""Measure a plain text-search control arm on the real cases.

Code Steward's value claim is that structured retrieval beats what an
agent gets from plain text search. That claim is untested until plain
text search is measured on the same cases with the same metrics.

This harness is the control arm. It never imports Code Steward's
retrieval or scoring code. It reads unit boundaries from the index only
to attribute a matched source line to an enclosing code unit, which is
segmentation rather than ranking: the question is whether keyword
matching can find the right code, not whether ripgrep can parse Python.
Every ranking input below comes from the source text alone.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Words that carry no discriminating signal in a code-search query.
# "Find", "code", and "helper" appear in nearly every case prompt, so a
# baseline that searched for them would rank by file size.
_STOPWORD_TEXT = """
    a an and are as at be been being but by can code could did do does
    doing done for from get gets given handle handles has have having
    how in into is it its like make makes of on or over per put return
    returns should so some such take takes than that the their them then
    there these they this those to use used uses using was were what
    when where which while who why will with would
    find locate search identify show where's wheres helper helpers
    function functions method methods class classes reusable existing
    logic implementation implementations piece part area thing
"""

STOPWORDS = frozenset(_STOPWORD_TEXT.split())

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")


@dataclass(slots=True, frozen=True)
class UnitSpan:
    unit_id: str
    path: str
    start_line: int
    end_line: int


def load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_spans(database: Path) -> dict[str, list[UnitSpan]]:
    """Group unit line spans by source path, innermost span last."""
    conn = sqlite3.connect(database)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT unit_id, path, start_line, end_line FROM units").fetchall()
    finally:
        conn.close()

    by_path: dict[str, list[UnitSpan]] = defaultdict(list)
    for row in rows:
        by_path[row["path"]].append(
            UnitSpan(row["unit_id"], row["path"], row["start_line"], row["end_line"])
        )
    # Widest span first means a nested method wins over its class when
    # both contain the matched line.
    for spans in by_path.values():
        spans.sort(key=lambda span: (span.start_line, -span.end_line))
    return dict(by_path)


def enclosing_unit(spans: list[UnitSpan], line: int) -> str | None:
    """Return the innermost unit containing ``line``, if any."""
    index = bisect_right([span.start_line for span in spans], line)
    best: UnitSpan | None = None
    for span in spans[:index]:
        if span.end_line < line:
            continue
        if best is None or span.start_line >= best.start_line:
            best = span
    return None if best is None else best.unit_id


def query_terms(query: str) -> list[str]:
    """Extract discriminating terms from a natural-language query."""
    seen: dict[str, None] = {}
    for match in TOKEN_RE.finditer(query):
        term = match.group(0).lower()
        if term in STOPWORDS:
            continue
        seen.setdefault(term, None)
    return list(seen)


def python_files(root: Path) -> list[Path]:
    """List indexable Python files, in a stable order."""
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def search_lines(term: str, root: Path) -> list[tuple[str, int]]:
    """Return ``(relative_path, lineno)`` for each matching line.

    This replicates ``rg --ignore-case --fixed-strings --glob '*.py'``
    on the same tree and returns identical hits. It is implemented in
    Python so the control arm carries no system dependency: a control
    that only runs where ripgrep happens to be installed is a control
    that stops running.
    """
    needle = term.lower()
    hits: list[tuple[str, int]] = []
    for path in python_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # ripgrep skips files it cannot decode rather than failing.
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if needle in line.lower():
                hits.append((rel, lineno))
    return hits


def rank_units(
    terms: list[str],
    root: Path,
    spans: dict[str, list[UnitSpan]],
) -> tuple[list[str], int]:
    """Rank units by distinct query terms matched, then by hit count.

    This is the strongest ranking a mechanical grep baseline can make
    from term hits alone: coverage of the query first, then density.
    Ties break on unit ID so the report is reproducible.
    """
    distinct: dict[str, set[str]] = defaultdict(set)
    density: dict[str, int] = defaultdict(int)
    total_hits = 0

    for term in terms:
        for rel_path, lineno in search_lines(term, root):
            total_hits += 1
            unit_id = enclosing_unit(spans.get(rel_path, []), lineno)
            if unit_id is None:
                continue
            distinct[unit_id].add(term)
            density[unit_id] += 1

    ordered = sorted(
        distinct,
        key=lambda unit_id: (-len(distinct[unit_id]), -density[unit_id], unit_id),
    )
    return ordered, total_hits


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _hit_at(candidate_ids: list[str], relevant: set[str], k: int) -> bool:
    return bool(relevant & set(candidate_ids[:k]))


def _known_redundant_candidates(
    candidate_ids: list[str],
    redundancy_groups: list[list[str]],
) -> int:
    selected = set(candidate_ids)
    redundant = 0
    for group in redundancy_groups:
        redundant += max(0, len(selected & set(group)) - 1)
    return redundant


def _read_bytes(
    candidate_ids: list[str],
    span_index: dict[str, UnitSpan],
    root: Path,
    cache: dict[str, list[str]],
) -> int:
    """Bytes an agent must read to inspect every returned candidate.

    Code Steward hands the reviewer a packet. Grep hands the reviewer a
    file and a line number, so the comparable cost is the source of each
    candidate unit.
    """
    total = 0
    for unit_id in candidate_ids:
        span = span_index.get(unit_id)
        if span is None:
            continue
        lines = cache.get(span.path)
        if lines is None:
            lines = (root / span.path).read_text(encoding="utf-8").splitlines(keepends=True)
            cache[span.path] = lines
        body = "".join(lines[span.start_line - 1 : span.end_line])
        total += len(body.encode("utf-8"))
    return total


def evaluate_case(
    case: dict[str, Any],
    root: Path,
    spans: dict[str, list[UnitSpan]],
    span_index: dict[str, UnitSpan],
    cache: dict[str, list[str]],
) -> dict[str, Any]:
    limit = int(case.get("limit", 8))
    terms = query_terms(case["query"])

    started = time.perf_counter()
    ordered, total_hits = rank_units(terms, root, spans)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    candidate_ids = ordered[:limit]
    relevant = set(case["relevant"])
    traps = set(case.get("traps", []))
    redundancy_groups = case.get("redundancy_groups", [])
    relevant_found = relevant & set(candidate_ids)
    first_relevant_rank = next(
        (rank for rank, unit_id in enumerate(candidate_ids, 1) if unit_id in relevant),
        None,
    )
    unbounded_rank = next(
        (rank for rank, unit_id in enumerate(ordered, 1) if unit_id in relevant),
        None,
    )

    return {
        "id": case["id"],
        "category": case["category"],
        "query": case["query"],
        "terms": terms,
        "limit": limit,
        "candidates": candidate_ids,
        "relevant": sorted(relevant),
        "traps": sorted(traps),
        "hit_at_1": _hit_at(candidate_ids, relevant, 1),
        "hit_at_3": _hit_at(candidate_ids, relevant, 3),
        "hit_at_5": _hit_at(candidate_ids, relevant, 5),
        "hit_at_k": bool(relevant_found),
        "recall_at_k": len(relevant_found) / len(relevant),
        "reciprocal_rank": 0.0 if first_relevant_rank is None else 1.0 / first_relevant_rank,
        "unbounded_rank_of_first_relevant": unbounded_rank,
        "known_traps_returned": sum(unit_id in traps for unit_id in candidate_ids),
        "known_redundant_candidates": _known_redundant_candidates(
            candidate_ids, redundancy_groups
        ),
        "candidates_returned": len(candidate_ids),
        "units_matched_total": len(ordered),
        "raw_grep_hits": total_hits,
        "read_bytes": _read_bytes(candidate_ids, span_index, root, cache),
        "retrieval_ms": elapsed_ms,
    }


def run_baseline(project_root: Path, database: Path, cases_path: Path) -> dict[str, Any]:
    spans = load_spans(database)
    span_index = {span.unit_id: span for group in spans.values() for span in group}
    cases = load_cases(cases_path)
    cache: dict[str, list[str]] = {}
    results = [evaluate_case(case, project_root, spans, span_index, cache) for case in cases]

    total_candidates = sum(result["candidates_returned"] for result in results)
    total_requested = sum(result["limit"] for result in results)
    total_traps = sum(result["known_traps_returned"] for result in results)
    total_redundant = sum(result["known_redundant_candidates"] for result in results)

    return {
        "schema_version": 1,
        "strategy": "text-search-term-coverage",
        "cases_path": cases_path.name,
        "summary": {
            "case_count": len(results),
            "hit_rate_at_1": _mean([float(result["hit_at_1"]) for result in results]),
            "hit_rate_at_3": _mean([float(result["hit_at_3"]) for result in results]),
            "hit_rate_at_5": _mean([float(result["hit_at_5"]) for result in results]),
            "hit_rate_at_k": _mean([float(result["hit_at_k"]) for result in results]),
            "macro_recall_at_k": _mean([result["recall_at_k"] for result in results]),
            "mrr": _mean([result["reciprocal_rank"] for result in results]),
            "known_trap_rate": total_traps / total_candidates if total_candidates else 0.0,
            "known_redundancy_rate": (
                total_redundant / total_candidates if total_candidates else 0.0
            ),
            "mean_candidates_returned": _mean(
                [float(result["candidates_returned"]) for result in results]
            ),
            "candidate_fill_rate": total_candidates / total_requested if total_requested else 0.0,
            "mean_units_matched": _mean([float(r["units_matched_total"]) for r in results]),
            "mean_read_bytes": _mean([float(result["read_bytes"]) for result in results]),
            "mean_retrieval_ms": _mean([result["retrieval_ms"] for result in results]),
        },
        "cases": results,
    }


def _summary_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Requests text-search control baseline",
        "",
        f"- Cases: **{summary['case_count']}**",
        f"- Hit@1: **{summary['hit_rate_at_1']:.2%}**",
        f"- Hit@3: **{summary['hit_rate_at_3']:.2%}**",
        f"- Hit@5: **{summary['hit_rate_at_5']:.2%}**",
        f"- Hit@K: **{summary['hit_rate_at_k']:.2%}**",
        f"- Macro recall@K: **{summary['macro_recall_at_k']:.2%}**",
        f"- MRR: **{summary['mrr']:.3f}**",
        f"- Known trap rate: **{summary['known_trap_rate']:.2%}**",
        f"- Mean units matched before truncation: **{summary['mean_units_matched']:.1f}**",
        f"- Mean bytes to read all candidates: **{summary['mean_read_bytes']:.1f}**",
        f"- Mean search time: **{summary['mean_retrieval_ms']:.1f} ms**",
        "",
        "Ranking uses distinct query-term coverage then hit density. No Code Steward "
        "scoring, aliases, or relationships are consumed.",
        "",
    ]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure a plain ripgrep control baseline on the same real-repository cases."
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report = run_baseline(
        args.project_root.resolve(), args.database.resolve(), args.cases.resolve()
    )
    (output_dir / "grep-baseline.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = _summary_markdown(report)
    (output_dir / "grep-baseline.md").write_text(summary, encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
