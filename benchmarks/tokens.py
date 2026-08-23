"""Calibrate the byte figures this project publishes against tokens.

Every cost number here is measured in bytes -- packet bytes, wasted
bytes per query, bytes returned per similarity arm. Bytes are a proxy.
What actually costs money and context is tokens, and the conversion is
not a constant: it moves with how much of the text is identifiers,
punctuation, or English prose.

Nothing had ever checked the size of that error. This module measures
it with ``tiktoken`` and publishes the spread, including the corpora
where the proxy is worst. A single flattering average would hide
exactly the cases a reader needs.

``tiktoken`` is an optional dependency. It is deliberately not
required to run the benchmarks: calibration is a periodic check whose
output is committed, not a step in every measurement.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The encoding current Claude and GPT-class models are closest to. The
# point of this table is the size of the error, not a per-vendor
# token count, so one modern encoding is enough.
ENCODING = "o200k_base"


@dataclass(slots=True, frozen=True)
class Calibration:
    """Bytes-per-token for one population of text."""

    population: str
    samples: int
    total_bytes: int
    total_tokens: int

    @property
    def bytes_per_token(self) -> float:
        return self.total_bytes / self.total_tokens if self.total_tokens else 0.0

    def error_against(self, assumed: float) -> float:
        """Signed relative error of a fixed bytes-per-token guess."""
        actual = self.bytes_per_token
        return 0.0 if not actual else (assumed - actual) / actual

    def to_dict(self, assumed: float) -> dict[str, Any]:
        return {
            "population": self.population,
            "samples": self.samples,
            "total_bytes": self.total_bytes,
            "total_tokens": self.total_tokens,
            "bytes_per_token": round(self.bytes_per_token, 3),
            "relative_error_of_assumption": round(self.error_against(assumed), 4),
        }


def calibrate(population: str, texts: Iterable[str]) -> Calibration:
    """Count real tokens for a population of text."""
    import tiktoken

    encoder = tiktoken.get_encoding(ENCODING)
    total_bytes = 0
    total_tokens = 0
    samples = 0
    for text in texts:
        samples += 1
        total_bytes += len(text.encode("utf-8"))
        total_tokens += len(encoder.encode(text, disallowed_special=()))
    return Calibration(population, samples, total_bytes, total_tokens)


def pooled(calibrations: list[Calibration]) -> float:
    """Bytes per token across every population, weighted by size."""
    total_bytes = sum(entry.total_bytes for entry in calibrations)
    total_tokens = sum(entry.total_tokens for entry in calibrations)
    return total_bytes / total_tokens if total_tokens else 0.0


def _markdown(calibrations: list[Calibration], assumed: float) -> str:
    lines = [
        "| Population | Samples | Bytes | Tokens | Bytes/token | Error of the pooled assumption |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in calibrations:
        lines.append(
            f"| {entry.population} | {entry.samples:,} | {entry.total_bytes:,} | "
            f"{entry.total_tokens:,} | {entry.bytes_per_token:.3f} | "
            f"{entry.error_against(assumed):+.1%} |"
        )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calibrate byte figures against tiktoken.")
    parser.add_argument("--checkouts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    from benchmarks.retrieval.run import run_benchmark
    from benchmarks.similarity.corpus import CORPORA, corpus_files
    from benchmarks.similarity.units import load_units

    calibrations: list[Calibration] = []
    for corpus in CORPORA:
        checkout = (args.checkouts / corpus.name).resolve()
        units = load_units(corpus.name, checkout, corpus_files(corpus, checkout))
        calibrations.append(calibrate(corpus.name, (unit.normalised for unit in units)))

    report = run_benchmark()
    packets = [json.dumps(case, separators=(",", ":"), sort_keys=True) for case in report["cases"]]
    calibrations.append(calibrate("frozen-benchmark-packets", packets))

    assumed = pooled(calibrations)
    payload = {
        "schema_version": 1,
        "encoding": ENCODING,
        "pooled_bytes_per_token": round(assumed, 3),
        "populations": [entry.to_dict(assumed) for entry in calibrations],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(_markdown(calibrations, assumed))
    print(f"\npooled bytes/token: {assumed:.3f} -> {args.output}")


if __name__ == "__main__":
    main()
