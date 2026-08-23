"""Guards against a benchmark harness flattering itself.

Three of the numbers this project reports get *better* as they get
smaller: the trap rate, the redundancy rate, and the duplicate rate.
Every one of them is a ratio over the candidates an arm returned, so
an arm that returns nothing at all scores a perfect zero on all three.
A crash caught in the wrong place, a mistyped limit, or an empty index
would therefore be published as a clean sheet.

Graph Code Review shipped two bugs of exactly this shape, where a
thrown exception scored as a win. This project had no guard at all
until these were added. The rule here is that a denominator of zero is
never a score -- it is a harness failure, and it raises.

Exclusions get the same treatment from the other direction. A case or
a file dropped from a run must appear in the report as dropped. A
benchmark that silently skips what it could not parse reports a
smaller, cleaner population than the one it claimed to measure.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


class DegenerateBenchmark(RuntimeError):
    """A harness produced a score it has no evidence for."""


def checked_rate(numerator: float, denominator: float, *, metric: str) -> float:
    """Divide, and refuse to call an empty run a perfect score.

    ``metric`` names the figure so the failure says which number was
    about to be invented.
    """
    if denominator == 0:
        raise DegenerateBenchmark(
            f"{metric} has no denominator: the arm returned nothing, "
            f"so a rate of 0.0 would be a claim the run cannot support"
        )
    return numerator / denominator


@dataclass(slots=True)
class Exclusions:
    """Everything a run dropped, counted by reason."""

    reasons: Counter[str] = field(default_factory=Counter)
    examples: dict[str, list[str]] = field(default_factory=dict)

    # Enough to identify the problem, not enough to become a log.
    example_limit: int = 5

    def record(self, reason: str, subject: str) -> None:
        """Note one dropped row and keep a bounded sample of them."""
        self.reasons[reason] += 1
        shown = self.examples.setdefault(reason, [])
        if len(shown) < self.example_limit:
            shown.append(subject)

    @property
    def total(self) -> int:
        return sum(self.reasons.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "by_reason": dict(sorted(self.reasons.items())),
            "examples": {reason: list(rows) for reason, rows in sorted(self.examples.items())},
        }


def assert_reports_exclusions(report: dict[str, Any]) -> None:
    """Fail if a report omits its exclusion block entirely.

    An absent block and a zero block are different claims. The first
    means nobody counted.
    """
    if "excluded" not in report:
        raise DegenerateBenchmark(
            "report carries no 'excluded' block; a run that drops rows "
            "without counting them reports a cleaner population than it measured"
        )
