"""Emit prompts asking an agent to draft a held-out function.

`docs/verdict.md` reports that comparing a draft against the index
surfaces the existing duplicate 0.994 of the time. That number is an
upper bound and the doc says so: it compares the *actual* removed
body, not an approximation an agent would write. Every claim the
reframed project makes rests on how far the real figure sits below
it, and nothing has measured that.

This builds the input for measuring it. Each prompt carries what a
developer genuinely has before writing a function -- its name,
signature, and docstring -- and nothing else. The agent writes a
plausible body. That body is then compared against the repository in
place of the real one.

**What the agent must not see.** The body, the file, the module path,
and any sibling code. A drafting agent that can find the original is
measuring the corpus rather than the draft. The prompt carries no
path, and the corpora are checked out well away from the working
directory, but the function name is in the signature and a name is
searchable -- so the instruction not to search is load-bearing here in
a way it was not for the reviewer runs. `docs/verdict.md` records
that as a limitation rather than a solved problem.

**Only positive cases are drafted.** The question is whether a
realistic draft still finds a duplicate that exists. Negative cases
would measure something different and are left to the floor work.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.guards import Exclusions
from benchmarks.similarity.corpus import CORPORA, corpus_files, hash_order
from benchmarks.similarity.units import load_units
from benchmarks.verdict.cases import build_cases, load_pairs

# Positive cases drafted per corpus. Sixty drafts is what an agent
# run costs at a size worth reporting; it is a budget, not a power
# calculation.
SAMPLE_PER_CORPUS = 20

# Drafts per agent.
BATCH_SIZE = 10

INSTRUCTIONS = """\
Write a plausible Python implementation for each function below.

You are given exactly what a developer has before writing it: the \
function's name, its signature, and its docstring. Write the body you \
would write from that.

CRITICAL:
- Do NOT search the filesystem, grep, or try to find an existing \
implementation of any of these functions. They are drawn from open \
source projects and finding the original would invalidate the \
measurement entirely.
- Write what a competent developer would write from the description. \
Do not try to guess the original author's exact wording.
- A realistic first draft is what is wanted, not a polished one. Do \
not add error handling, logging, or validation the docstring does \
not mention.
- Keep the given signature exactly. Include the docstring.
- If a docstring is too vague to implement, write your best guess \
anyway and set "confident" to false.

Return JSON only, no prose:

{"drafts": [{"id": "<task id>", "code": "<the complete function, \
including its def line>", "confident": true}]}
"""


def _signature_of(unit: Any) -> str:
    return unit.signature or f"{unit.name}(...)"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build drafting prompts.")
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

    tasks: list[dict[str, Any]] = []
    key: list[dict[str, Any]] = []

    for corpus in CORPORA:
        checkout = (args.checkouts / corpus.name).resolve()
        corpus_units = load_units(
            corpus.name, checkout, corpus_files(corpus, checkout), Exclusions()
        )
        by_id = {unit.unit_id: unit for unit in corpus_units}

        eligible: dict[str, Any] = {}
        for case in cases:
            if case.corpus != corpus.name or case.kind != "reuse-available":
                continue
            target = by_id.get(case.target)
            if target is None or case.expected not in by_id:
                continue
            purpose = target.unit.purpose.strip()
            fallback = target.unit.name.replace("_", " ").strip().lower()
            if not purpose or purpose.lower() == fallback:
                continue
            eligible[case.case_id] = case

        for case_id in hash_order(eligible)[:SAMPLE_PER_CORPUS]:
            case = eligible[case_id]
            target = by_id[case.target]
            task_id = case_id.replace(":", "-")
            tasks.append(
                {
                    "task_id": task_id,
                    "name": target.unit.name,
                    "signature": _signature_of(target.unit),
                    "docstring": target.unit.doc_text or target.unit.purpose,
                }
            )
            key.append(
                {
                    "task_id": task_id,
                    "case_id": case_id,
                    "corpus": corpus.name,
                    "target": case.target,
                    "expected": case.expected,
                }
            )
        print(f"{corpus.name}: {len(tasks)} prompts so far", flush=True)

    batches: dict[int, list[dict[str, Any]]] = {}
    for index, task in enumerate(tasks):
        batches.setdefault(index // BATCH_SIZE, []).append(task)

    payload = {
        "schema_version": 1,
        "instructions": INSTRUCTIONS,
        "sample_per_corpus": SAMPLE_PER_CORPUS,
        "batches": [{"batch": number, "tasks": rows} for number, rows in sorted(batches.items())],
        "answer_key": key,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(tasks)} prompts in {len(batches)} batches -> {args.output}")


if __name__ == "__main__":
    main()
