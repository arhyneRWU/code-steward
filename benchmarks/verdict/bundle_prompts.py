"""Build DRY-judgement bundles for a small model, from real labels.

The project's premise is that a cheap model can do useful work on a
large codebase if something hands it the right small bundle. Every
figure produced so far measures whether the right bytes *reach* a
reader. None measures whether a cheaper model then succeeds. That is
the same gap that made the packet's reuse evidence look valuable
until the verdict was scored and came back null.

So this builds the acceptance test. Each bundle holds eight
functions. A positive bundle contains one pair the blind labelling
called `same-behaviour`; a negative contains none. The model is asked
which two, if any, do the same work.

**Ground truth is the labels, not this project's own similarity.**
Scoring a model against our Jaccard would measure whether it can
reproduce our arithmetic, which is not the question. The 170
`same-behaviour` and 86 `unrelated` pairs were labelled blind, before
any arm was scored against them.

**`overlapping` pairs are excluded entirely.** They are the ambiguous
middle of the label set, and a model that calls one a duplicate is
neither right nor wrong. Including them would make the score depend
on where a judgement call was made rather than on the model.

Distractors are drawn from the same corpus so the task cannot be won
by noticing that one function looks out of place.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.guards import Exclusions
from benchmarks.similarity.corpus import CORPORA, corpus_files, hash_order
from benchmarks.similarity.units import CorpusUnit, load_units

BUNDLE_SIZE = 8
PER_CORPUS = 20
BATCH_SIZE = 4

INSTRUCTIONS = """\
Each bundle below contains eight Python functions from one codebase, \
labelled A through H.

For each bundle, decide whether any two of them do substantially the \
same work -- one is a duplicate or near-duplicate of the other, such \
that a maintainer would want them merged.

Judge behaviour, not surface text. Two functions with different names \
and variables can be duplicates. Two functions that look similar but \
serve genuinely different purposes are not.

At most one pair per bundle. If no two functions duplicate each \
other, say so -- that is a common and correct answer, and guessing a \
pair when none exists is worse than declining.

Return JSON only, no prose:

{"answers": [{"id": "<bundle id>", "duplicate_pair": ["A", "D"], \
"confidence": "high|low"}]}

Use "duplicate_pair": [] when nothing in the bundle duplicates \
anything else.
"""


def _source(unit: CorpusUnit, checkout: Path) -> str:
    try:
        lines = (checkout / unit.path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""
    return "\n".join(lines[unit.start_line - 1 : unit.end_line])


def _take(pool: list[str], start: int, count: int) -> list[str]:
    """Take ``count`` distractors, wrapping when the pool runs out.

    Distractors are reused across bundles once the pool is exhausted;
    within a bundle they are always distinct. Reuse risks an
    unlabelled distractor pair being a real duplicate, which would
    count against the model rather than for it, so the bias runs the
    safe way.
    """
    if not pool:
        return []
    return [pool[(start + offset) % len(pool)] for offset in range(count)]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build DRY bundles for a small model.")
    parser.add_argument("--checkouts", type=Path, required=True)
    parser.add_argument(
        "--labels",
        type=Path,
        default=Path("benchmarks/similarity/reuse_pair_labels.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    pairs = json.loads(args.labels.read_text(encoding="utf-8"))["pairs"]

    bundles: list[dict[str, Any]] = []
    key: list[dict[str, Any]] = []

    for corpus in CORPORA:
        checkout = (args.checkouts / corpus.name).resolve()
        units = load_units(corpus.name, checkout, corpus_files(corpus, checkout), Exclusions())
        by_id = {unit.unit_id: unit for unit in units}

        rows = [row for row in pairs if row["corpus"] == corpus.name]
        positives = [
            row
            for row in rows
            if row["label"] == "same-behaviour" and row["left"] in by_id and row["right"] in by_id
        ]
        # A unit is only safe as a distractor if the labels never call
        # it a duplicate of anything: an unlabelled pair could easily
        # be a real duplicate nobody looked at.
        implicated = {
            unit
            for row in rows
            if row["label"] in {"same-behaviour", "overlapping"}
            for unit in (row["left"], row["right"])
        }
        clean = {
            unit
            for row in rows
            if row["label"] == "unrelated"
            for unit in (row["left"], row["right"])
            if unit not in implicated and unit in by_id
        }
        pool = hash_order(clean)
        if len(pool) < BUNDLE_SIZE:
            print(f"{corpus.name}: only {len(pool)} clean units, skipping", flush=True)
            continue

        index = {f"{row['pair_id']}": row for row in positives}
        chosen = hash_order(index)[: PER_CORPUS // 2]
        cursor = 0

        for pair_id in chosen:
            row = index[pair_id]
            members = [by_id[row["left"]], by_id[row["right"]]]
            fillers = [
                unit
                for unit in _take(pool, cursor, BUNDLE_SIZE - 2)
                if unit not in {row["left"], row["right"]}
            ][: BUNDLE_SIZE - 2]
            cursor += BUNDLE_SIZE - 2
            if len(fillers) < BUNDLE_SIZE - 2:
                continue
            members += [by_id[unit] for unit in fillers]
            bundles.append(_bundle(f"pos-{pair_id}", members, checkout))
            labels = _labels(members)
            key.append(
                {
                    "bundle_id": f"pos-{pair_id}",
                    "corpus": corpus.name,
                    "kind": "duplicate-present",
                    "expected": sorted([labels[row["left"]], labels[row["right"]]]),
                }
            )

        for number in range(PER_CORPUS // 2):
            fillers = _take(pool, cursor, BUNDLE_SIZE)
            cursor += BUNDLE_SIZE
            if len(fillers) < BUNDLE_SIZE:
                break
            members = [by_id[unit] for unit in fillers]
            bundle_id = f"neg-{corpus.name}-{number}"
            bundles.append(_bundle(bundle_id, members, checkout))
            key.append(
                {
                    "bundle_id": bundle_id,
                    "corpus": corpus.name,
                    "kind": "no-duplicate",
                    "expected": [],
                }
            )
        print(f"{corpus.name}: {len(bundles)} bundles so far", flush=True)

    batches: dict[int, list[dict[str, Any]]] = {}
    for position, bundle in enumerate(bundles):
        batches.setdefault(position // BATCH_SIZE, []).append(bundle)

    payload = {
        "schema_version": 1,
        "instructions": INSTRUCTIONS,
        "bundle_size": BUNDLE_SIZE,
        "batches": [
            {"batch": number, "bundles": rows} for number, rows in sorted(batches.items())
        ],
        "answer_key": key,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(bundles)} bundles in {len(batches)} batches -> {args.output}")


def _labels(members: list[CorpusUnit]) -> dict[str, str]:
    """Assign A..H in hash order, so position carries no signal."""
    order = hash_order([unit.unit_id for unit in members])
    return {unit_id: chr(ord("A") + index) for index, unit_id in enumerate(order)}


def _bundle(bundle_id: str, members: list[CorpusUnit], checkout: Path) -> dict[str, Any]:
    labels = _labels(members)
    return {
        "bundle_id": bundle_id,
        "functions": [
            {"label": labels[unit.unit_id], "code": _source(unit, checkout)}
            for unit in sorted(members, key=lambda entry: labels[entry.unit_id])
        ],
    }


if __name__ == "__main__":
    main()
