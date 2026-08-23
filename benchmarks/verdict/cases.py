"""Derive held-out reuse cases from the frozen similarity labels.

The similarity benchmark measured an arm: given a function, does the
comparison find the ones that duplicate it. That is a component
number. The product claim is different and larger -- that an agent
reaches a better REUSE / EXTEND / REFACTOR decision *before* writing
code -- and it has never been measured.

This is the first half of measuring it. A case is built by taking a
function whose duplicate is already labelled, hiding the function
itself, and using its docstring summary as the task an agent would
type. The right answer is known in advance: the labelled duplicate.

**What this measures and what it does not.** Running an actual
reviewer agent per case is not done here, so nothing below scores a
verdict. What is scored is whether the evidence needed to reach the
right verdict reaches the reviewer at all. That is a necessary
condition for the product claim and not the claim itself: evidence
being present does not prove an agent uses it. The agent-in-the-loop
half is deferred, and `docs/verdict.md` says so rather than letting
the weaker number stand in for the stronger one.

Negative cases matter as much as positive ones. A function with no
labelled duplicate should produce no reuse evidence, and an arm that
invents some is paying bytes for noise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# A purpose is the docstring's first line, or the identifier with
# underscores replaced when there is no docstring. An identifier is
# not a task description -- an agent typing "device info" is asking a
# different question from an agent typing the function's own name --
# so those cases are excluded and counted.
UNDOCUMENTED = "undocumented"


@dataclass(slots=True, frozen=True)
class VerdictCase:
    """One held-out function and the answer known in advance."""

    case_id: str
    corpus: str
    target: str
    # The labelled duplicate, or "" for a negative case where the
    # correct outcome is that nothing is surfaced.
    expected: str
    kind: str


def _purpose_is_identifier(purpose: str, name: str) -> bool:
    return purpose.strip().lower() == name.replace("_", " ").strip().lower()


def load_pairs(path: Path) -> list[dict[str, str]]:
    """Read the frozen similarity labels."""
    return json.loads(path.read_text(encoding="utf-8"))["pairs"]


def build_cases(pairs: list[dict[str, str]]) -> list[VerdictCase]:
    """Turn labelled pairs into held-out reuse cases.

    Each `same-behaviour` pair yields one positive case in each
    direction: either function could have been the one about to be
    written. Units that appear only in `unrelated` pairs yield
    negative cases.
    """
    positive: list[VerdictCase] = []
    seen_positive: set[str] = set()
    for row in pairs:
        if row["label"] != "same-behaviour":
            continue
        for target, expected in ((row["left"], row["right"]), (row["right"], row["left"])):
            key = f"{target}\x00{expected}"
            if key in seen_positive:
                continue
            seen_positive.add(key)
            positive.append(
                VerdictCase(
                    case_id=f"pos:{len(positive):04d}",
                    corpus=row["corpus"],
                    target=target,
                    expected=expected,
                    kind="reuse-available",
                )
            )

    in_positive = {case.target for case in positive}
    negative_units: dict[str, str] = {}
    for row in pairs:
        if row["label"] != "unrelated":
            continue
        for unit in (row["left"], row["right"]):
            if unit not in in_positive:
                negative_units.setdefault(unit, row["corpus"])

    negative = [
        VerdictCase(
            case_id=f"neg:{index:04d}",
            corpus=corpus,
            target=unit,
            expected="",
            kind="no-reuse-available",
        )
        for index, (unit, corpus) in enumerate(sorted(negative_units.items()))
    ]
    return positive + negative
