"""Score realistic agent drafts against the real-body upper bound.

Three arms over the same held-out positive cases, all with the target
function removed from the index:

- `real-body` -- compare the actual removed function. This is the
  0.994 arm from `docs/verdict.md`, reproduced here so the comparison
  is like for like on the same sample.
- `agent-draft` -- compare a body an agent wrote from the function's
  name, signature, and docstring alone. This is the honest figure.
- `agent-draft-floored` -- the same, with the shipped relevance floor
  applied, which is what a user actually gets.

The gap between the first two is the cost of the upper bound. It is
the number the reframed project most depends on and the one most
likely to be disappointing, so it is measured directly rather than
bracketed from rename tolerance.

A draft that does not parse is counted as a parse failure, not
silently dropped: an agent that cannot produce compilable code is a
real failure mode of the draft-first workflow.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import Any

from benchmarks.guards import Exclusions
from benchmarks.similarity.corpus import CORPORA, corpus_files
from benchmarks.similarity.units import load_units
from code_steward.similarity import (
    REUSE_FLOOR,
    draft_shingles,
    rank_against,
    shingles,
)

LIMIT = 8


def load_drafts(directory: Path) -> dict[str, dict[str, Any]]:
    """Read every drafting answer file into one map by task ID."""
    drafts: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("answer-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload["drafts"]:
            drafts[row["id"]] = row
    return drafts


def _surfaced(matches, expected: str, floor: float = 0.0) -> bool:
    return any(row.unit.unit_id == expected and row.score >= floor for row in matches)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score realistic drafts.")
    parser.add_argument("--checkouts", type=Path, required=True)
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--drafts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    key = json.loads(args.prompts.read_text(encoding="utf-8"))["answer_key"]
    drafts = load_drafts(args.drafts)

    tally: dict[str, int] = defaultdict(int)
    per_corpus: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    scores: list[dict[str, Any]] = []

    for corpus in CORPORA:
        rows = [row for row in key if row["corpus"] == corpus.name]
        if not rows:
            continue
        checkout = (args.checkouts / corpus.name).resolve()
        corpus_units = load_units(
            corpus.name, checkout, corpus_files(corpus, checkout), Exclusions()
        )
        by_id = {unit.unit_id: unit for unit in corpus_units}
        prepared = {unit.unit_id: shingles(unit.tokens) for unit in corpus_units}
        units = [dataclass_replace(entry.unit, unit_id=entry.unit_id) for entry in corpus_units]

        for row in rows:
            target, expected = row["target"], row["expected"]
            if target not in by_id or expected not in by_id:
                tally["skipped_missing_unit"] += 1
                continue

            visible = [unit for unit in units if unit.unit_id != target]
            visible_shingles = {k: v for k, v in prepared.items() if k != target}

            tally["cases"] += 1
            per_corpus[corpus.name]["cases"] += 1

            real = rank_against(prepared[target], visible, visible_shingles, LIMIT)
            if _surfaced(real, expected):
                tally["real_body_surfaced"] += 1
                per_corpus[corpus.name]["real_body_surfaced"] += 1

            draft = drafts.get(row["task_id"])
            if draft is None:
                tally["draft_missing"] += 1
                continue
            try:
                needle = draft_shingles(draft["code"])
            except SyntaxError:
                tally["draft_unparsable"] += 1
                continue
            if not needle:
                tally["draft_too_small"] += 1
                continue

            tally["draft_scored"] += 1
            per_corpus[corpus.name]["draft_scored"] += 1
            ranked = rank_against(needle, visible, visible_shingles, LIMIT)
            if _surfaced(ranked, expected):
                tally["draft_surfaced"] += 1
                per_corpus[corpus.name]["draft_surfaced"] += 1
            if _surfaced(ranked, expected, REUSE_FLOOR):
                tally["draft_surfaced_floored"] += 1
                per_corpus[corpus.name]["draft_surfaced_floored"] += 1

            best = max((row.score for row in ranked), default=0.0)
            hit = next((r.score for r in ranked if r.unit.unit_id == expected), 0.0)
            scores.append(
                {
                    "task_id": row["task_id"],
                    "best": round(best, 3),
                    "expected_score": round(hit, 3),
                }
            )
        print(f"{corpus.name}: done", flush=True)

    cases = tally["cases"]
    scored = tally["draft_scored"]
    payload = {
        "schema_version": 1,
        "floor": REUSE_FLOOR,
        "counts": dict(sorted(tally.items())),
        "arms": [
            {
                "arm": "real-body",
                "cases": cases,
                "surfaced": tally["real_body_surfaced"],
                "surfaced_rate": round(tally["real_body_surfaced"] / cases, 3) if cases else 0.0,
            },
            {
                "arm": "agent-draft",
                "cases": scored,
                "surfaced": tally["draft_surfaced"],
                "surfaced_rate": round(tally["draft_surfaced"] / scored, 3) if scored else 0.0,
                # A draft too small to compare is a failure of the
                # workflow, not a case that never happened. Reported
                # over every case as well as every usable draft,
                # because the first is what a user experiences.
                "surfaced_rate_all_cases": round(tally["draft_surfaced"] / cases, 3)
                if cases
                else 0.0,
            },
            {
                "arm": "agent-draft-floored",
                "cases": scored,
                "surfaced": tally["draft_surfaced_floored"],
                "surfaced_rate": round(tally["draft_surfaced_floored"] / scored, 3)
                if scored
                else 0.0,
                "surfaced_rate_all_cases": round(tally["draft_surfaced_floored"] / cases, 3)
                if cases
                else 0.0,
            },
        ],
        "per_corpus": {
            name: dict(sorted(rows.items())) for name, rows in sorted(per_corpus.items())
        },
        "scores": scores,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {key: value for key, value in payload.items() if key != "scores"}
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
