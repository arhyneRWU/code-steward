"""Simulate the run-2 criterion before fixing it.

The reason this file exists: two criteria in this project were wrong
in ways no amount of reading the formula would have caught. One
asymptoted at about 51% power at any n. One could not fail, because
the sample had no negative values and a one-sided bootstrap lower
bound on such a sample is positive by construction.

Both were found by simulating the criterion against a known truth,
so run 2's criterion is simulated here and the table is pasted into
`docs/skill-ab-run2.md` before any arm runs.

The model: each paired question either ties, or is discordant with a
recall difference drawn uniform on [0.10, 0.50]. ``p_up`` is the
probability a discordant pair favours the skill, so ``p_up = 0.5`` is
the null and the power reported there should be about alpha. If it
is not, the criterion is broken and the run must not happen.
"""

from __future__ import annotations

import argparse
import random
import statistics

from .score import permutation_p

ALPHA = 0.05
MAG_LOW = 0.10
MAG_HIGH = 0.50


def sample(n: int, tie_rate: float, p_up: float, rng: random.Random) -> list[float]:
    """One simulated set of paired recall differences."""
    diffs: list[float] = []
    for _ in range(n):
        if rng.random() < tie_rate:
            diffs.append(0.0)
            continue
        magnitude = rng.uniform(MAG_LOW, MAG_HIGH)
        diffs.append(magnitude if rng.random() < p_up else -magnitude)
    return diffs


def power(n: int, tie_rate: float, p_up: float, trials: int, seed: int) -> float:
    """Share of trials in which the criterion fires."""
    rng = random.Random(seed)
    fired = [
        1.0 if permutation_p(sample(n, tie_rate, p_up, rng)) < ALPHA else 0.0
        for _ in range(trials)
    ]
    return statistics.fmean(fired)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simulate the run-2 criterion.")
    parser.add_argument("--trials", type=int, default=400)
    parser.add_argument("--seed", type=int, default=7)
    return parser


def main() -> None:
    args = _parser().parse_args()
    print(f"{'n':>4} {'tie':>5} {'p_up':>5} {'power':>6}")
    for n in (30, 40, 60):
        for tie_rate in (0.3, 0.5, 0.7):
            for p_up in (0.5, 0.7, 0.85, 1.0):
                value = power(n, tie_rate, p_up, args.trials, args.seed)
                print(f"{n:>4} {tie_rate:>5.2f} {p_up:>5.2f} {value:>6.2f}")


if __name__ == "__main__":
    main()
