"""Measure how often `check` fires on ordinary unchanged code.

`docs/floor.md` chose the relevance floor against a *cross-corpus*
null and said plainly what that leaves open: two functions in one
codebase share idioms, helpers, and house style, so within-repository
coincidence is probably higher than between two unrelated projects.
That caveat matters much more now that `code-steward check` runs over
a working tree, because the number a user feels is not a false
positive rate on paper -- it is how often the command interrupts
them.

So this measures the alarm rate: treat every function in a held-out
sample as though it had just been written, compare it against the
rest of its own repository, and count how many report an overlap.

**This is not a false-positive rate and must not be quoted as one.**
Within a repository many overlaps are real -- Home Assistant's
integrations are template-duplicated on purpose, and finding those is
the tool working. Nothing here is labelled, so an alarm cannot be
sorted into correct and incorrect. What it bounds is noise: a command
that fires on half of all functions is unusable whether or not it is
right, and one that fires on 3% is worth running.

The sample is the same held-out slice the floor was chosen on, which
was never labelled and never used for tuning.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace as dataclass_replace
from pathlib import Path

from benchmarks.guards import Exclusions, assert_reports_exclusions
from benchmarks.similarity.corpus import CORPORA_BY_NAME, corpus_files, held_out_files
from benchmarks.similarity.floor import HELD_OUT_SIZE
from benchmarks.similarity.units import load_units
from code_steward.similarity import REUSE_FLOOR, rank_with_floor, shingles

# Floors to report alongside the shipped one, so the trade is visible
# without anyone having to re-run this to see it.
REPORTED_FLOORS = (0.20, REUSE_FLOOR, 0.35, 0.50)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure the check alarm rate.")
    parser.add_argument("--checkouts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    per_corpus: dict[str, dict[str, object]] = {}

    # Django is included even though it has no held-out slice. Nothing
    # is being chosen here, only observed, and it is the one corpus in
    # the set that is not deliberately duplication-heavy -- which
    # turns out to be the difference that matters most.
    targets = [(name, size) for name, size in HELD_OUT_SIZE.items()] + [("django", 0)]

    dropped = Exclusions()
    for name, size in targets:
        corpus = CORPORA_BY_NAME[name]
        checkout = (args.checkouts / name).resolve()
        files = held_out_files(corpus, checkout, size) if size else corpus_files(corpus, checkout)
        entries = load_units(name, checkout, files, dropped)
        prepared = {entry.unit_id: shingles(entry.tokens) for entry in entries}
        units = [dataclass_replace(entry.unit, unit_id=entry.unit_id) for entry in entries]

        alarms = dict.fromkeys(REPORTED_FLOORS, 0)
        for entry in entries:
            ranking = rank_with_floor(
                prepared[entry.unit_id],
                units,
                prepared,
                3,
                entry.unit_id,
                floor=min(REPORTED_FLOORS),
            )
            for floor in REPORTED_FLOORS:
                if any(row.score >= floor for row in ranking.matches):
                    alarms[floor] += 1

        total = len(entries)
        per_corpus[name] = {
            "functions": total,
            "held_out": bool(size),
            "role": corpus.role,
            "alarm_rate": {
                str(floor): round(count / total, 4) if total else 0.0
                for floor, count in sorted(alarms.items())
            },
        }
        print(f"{name}: {total} functions", flush=True)

    payload = {
        "schema_version": 1,
        "shipped_floor": REUSE_FLOOR,
        "note": "Alarm rate, not false-positive rate. Nothing here is labelled.",
        "per_corpus": per_corpus,
        "excluded": dropped.to_dict(),
    }
    # An absent block and a zero block are different claims, and
    # this report used to carry neither. See
    # guards.assert_reports_exclusions.
    assert_reports_exclusions(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
