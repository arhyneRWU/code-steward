"""Build blinded reviewer prompts, one per case per arm.

`benchmarks.verdict.run` measures whether the right evidence reaches
the reviewer. It stops there deliberately: evidence arriving is a
necessary condition for the product claim, not the claim itself. This
module builds the other half -- the prompts an actual reviewer agent
answers -- so the verdict can be scored rather than the retrieval.

Three things keep the measurement honest.

**The candidates are blinded.** Unit IDs and file paths are replaced
with opaque labels. A reviewer that can read a real path can open the
file, find the held-out function, and answer from the source instead
of from the packet -- which would measure the corpus, not the packet.
Blinding costs the reviewer information it would have in production,
so the resulting numbers are a floor rather than an estimate.

**The arms are not named.** A prompt does not say whether it carries
reuse evidence, and the two arms of one case never land in the same
batch, so a reviewer cannot answer one by remembering the other.

**The sample is drawn before anything is run.** Cases are taken in
hash order of the case ID, the same rule the corpora use, so the
sample cannot drift toward cases an arm happens to win.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import Any

from benchmarks.similarity.corpus import CORPORA, corpus_files, hash_order
from benchmarks.similarity.units import load_units
from benchmarks.verdict.cases import VerdictCase, build_cases, load_pairs
from benchmarks.verdict.run import DUPLICATE_LIMIT, PACKET_LIMIT
from code_steward.packet import build_packet
from code_steward.retrieval import retrieve_units
from code_steward.similarity import rank_similar_units, shingles

# Sampled per corpus per polarity, so no corpus dominates. Ten gives
# sixty cases and a hundred and twenty judgements -- what a reviewer
# run costs at a size worth reporting. The figure is a budget, not a
# power calculation, and the doc says so.
SAMPLE_PER_KIND = 10

# Judgements per agent. The two arms of one case are placed half a
# batch apart so they never share a reviewer.
BATCH_SIZE = 10

INSTRUCTIONS = """\
You are reviewing a change before it is written. A developer has \
described a function they are about to add. Below is what a code \
search returned from the existing repository.

Decide, for each task, one of:

- REUSE   -- an existing candidate already does this. Call it instead.
- EXTEND  -- an existing candidate nearly does this. Modify it.
- NEW     -- nothing here does this. Write the new function.

Answer only from what is shown. Do not use any tools, do not search \
the filesystem, and do not guess at code you cannot see. If the \
evidence does not support REUSE or EXTEND, answer NEW.

Return JSON only, no prose:

{"answers": [{"id": "<task id>", "verdict": "REUSE|EXTEND|NEW", \
"candidate": "<label, or empty for NEW>", "confidence": "high|low"}]}
"""


def _safe_concepts(concepts: list[str]) -> list[str]:
    """Drop concepts that name the unit's own module or qualname.

    The indexer emits the dotted qualname as a concept. Left in, it
    hands a reviewer the exact import path of a candidate, which is
    the one thing blinding is meant to withhold.
    """
    return [term for term in concepts if "::" not in term and "." not in term]


def _blind(packet: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Relabel every unit reference and drop anything traceable."""
    labels: dict[str, str] = {}
    for index, candidate in enumerate(packet["candidates"], start=1):
        labels[candidate["unit"]] = f"C{index}"
    extra = 0
    for candidate in packet["candidates"]:
        for row in candidate.get("duplicates", []):
            if row["unit"] not in labels:
                extra += 1
                labels[row["unit"]] = f"X{extra}"

    blinded = []
    for candidate in packet["candidates"]:
        row = {
            "label": labels[candidate["unit"]],
            "kind": candidate["kind"],
            "signature": candidate["signature"],
            "purpose": candidate["purpose"],
            "concepts": _safe_concepts(candidate["concepts"]),
            "owns": candidate["owns"],
            "not_owns": candidate["not_owns"],
            "dependencies": candidate["dependencies"],
        }
        if candidate.get("duplicates"):
            row["near_duplicates"] = [
                {"label": labels[near["unit"]], "overlap": near["overlap"]}
                for near in candidate["duplicates"]
            ]
        blinded.append(row)
    return {"candidates": blinded}, labels


def _sample(cases: list[VerdictCase], scorable: set[str]) -> list[VerdictCase]:
    by_kind: dict[str, list[VerdictCase]] = defaultdict(list)
    for case in cases:
        if case.case_id in scorable:
            by_kind[case.kind].append(case)
    chosen: list[VerdictCase] = []
    for kind in sorted(by_kind):
        index = {case.case_id: case for case in by_kind[kind]}
        for case_id in hash_order(index)[:SAMPLE_PER_KIND]:
            chosen.append(index[case_id])
    return chosen


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build blinded reviewer prompts.")
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
    pairs = load_pairs(args.labels.resolve())
    cases = build_cases(pairs)

    prompts: list[dict[str, Any]] = []
    answers: list[dict[str, Any]] = []

    for corpus in CORPORA:
        checkout = (args.checkouts / corpus.name).resolve()
        corpus_units = load_units(corpus.name, checkout, corpus_files(corpus, checkout))
        by_id = {unit.unit_id: unit for unit in corpus_units}
        prepared = {unit.unit_id: shingles(unit.tokens) for unit in corpus_units}
        units = [dataclass_replace(entry.unit, unit_id=entry.unit_id) for entry in corpus_units]

        scorable = set()
        for case in cases:
            if case.corpus != corpus.name:
                continue
            target = by_id.get(case.target)
            if target is None or (case.expected and case.expected not in by_id):
                continue
            purpose = target.unit.purpose.strip()
            fallback = target.unit.name.replace("_", " ").strip().lower()
            if not purpose or purpose.lower() == fallback:
                continue
            scorable.add(case.case_id)

        for case in _sample([c for c in cases if c.corpus == corpus.name], scorable):
            target = by_id[case.target]
            visible = [unit for unit in units if unit.unit_id != case.target]
            visible_shingles = {k: v for k, v in prepared.items() if k != case.target}
            results = retrieve_units(visible, target.unit.purpose, PACKET_LIMIT)

            plain, plain_labels = _blind(build_packet(target.unit.purpose, results, []))
            duplicates = {}
            for result in results:
                near = rank_similar_units(
                    result.unit.unit_id, visible, visible_shingles, limit=DUPLICATE_LIMIT
                )
                if near:
                    duplicates[result.unit.unit_id] = near
            reuse, reuse_labels = _blind(
                build_packet(target.unit.purpose, results, [], duplicates=duplicates)
            )

            for arm, payload, labels in (
                ("packet", plain, plain_labels),
                ("packet-reuse", reuse, reuse_labels),
            ):
                task_id = f"{case.case_id}:{arm}".replace(":", "-")
                prompts.append(
                    {
                        "task_id": task_id,
                        "task": target.unit.purpose,
                        "candidates": payload["candidates"],
                    }
                )
                answers.append(
                    {
                        "task_id": task_id,
                        "case_id": case.case_id,
                        "arm": arm,
                        "corpus": corpus.name,
                        "kind": case.kind,
                        "expected_label": labels.get(case.expected, ""),
                    }
                )
        print(f"{corpus.name}: {len(prompts)} prompts so far", flush=True)

    # Half-batch offset: arm A of a case and arm B of the same case
    # land in different batches, so no reviewer sees both.
    batch_count = max(1, (len(prompts) + BATCH_SIZE - 1) // BATCH_SIZE)
    batches: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, prompt in enumerate(prompts):
        case_index, arm_index = divmod(index, 2)
        batches[(case_index + arm_index * (batch_count // 2)) % batch_count].append(prompt)

    payload = {
        "schema_version": 1,
        "instructions": INSTRUCTIONS,
        "sample_per_kind": SAMPLE_PER_KIND,
        "batches": [{"batch": key, "tasks": batches[key]} for key in sorted(batches)],
        "answer_key": answers,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(prompts)} prompts in {len(batches)} batches -> {args.output}")


if __name__ == "__main__":
    main()
