"""Build the blind labelling sheet and its provenance key.

Two outputs, deliberately separate files. The sheet is what the
labeller reads. The key holds the corpus, the stratum, and the
generators behind every pair, and it stays closed until the labels are
committed. Keeping them in one file with a "do not look" comment would
not be blinding.

Neither output is committed. The sheet embeds source from the pinned
corpora, and the key is reproducible from the pins in seconds. What
gets committed is the label file: pair IDs, unit IDs, and judgements.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarks.similarity.corpus import CORPORA, corpus_files, corpus_roots
from benchmarks.similarity.generators import (
    ScoredPair,
    jscpd_pairs,
    metadata_pairs,
    run_jscpd,
    shingle_pairs,
)
from benchmarks.similarity.pool import PooledPair, build_sheet, probe_pairs, write_key
from benchmarks.similarity.units import CorpusUnit, load_units

# Pool depth per generator per corpus. Deep enough that the union
# clears the 150-pair floor, shallow enough that one labeller can read
# every pair properly rather than skimming the tail.
POOL_DEPTH = 30

# Probe pairs per corpus. Small, because they are a base-rate estimate
# and not a scored population.
PROBE_COUNT = 15


def generate(
    corpus_name: str, checkout: Path, work: Path
) -> tuple[list[CorpusUnit], dict[str, list[ScoredPair]]]:
    """Run all three generators over one pinned corpus sample."""
    corpus = next(entry for entry in CORPORA if entry.name == corpus_name)
    units = load_units(corpus_name, checkout, corpus_files(corpus, checkout))
    report = run_jscpd(
        checkout,
        [root.relative_to(checkout) for root in corpus_roots(corpus, checkout)],
        work / "jscpd" / corpus_name,
    )
    return units, {
        "shingle": shingle_pairs(units, POOL_DEPTH * 8),
        "metadata": metadata_pairs(units, POOL_DEPTH * 8),
        "jscpd": jscpd_pairs(report, checkout, units),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the blind similarity labelling sheet.")
    parser.add_argument("--checkouts", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    from benchmarks.similarity.pool import pool

    sources: dict[str, CorpusUnit] = {}
    pairs: list[PooledPair] = []
    for corpus in CORPORA:
        checkout = (args.checkouts / corpus.name).resolve()
        units, generated = generate(corpus.name, checkout, args.work.resolve())
        sources.update({unit.unit_id: unit for unit in units})
        pairs.extend(pool(corpus.name, generated, POOL_DEPTH))
        pairs.extend(probe_pairs(units, corpus.name, PROBE_COUNT))
        print(
            f"{corpus.name}: {len(units)} units, "
            + ", ".join(f"{name} {len(rows)}" for name, rows in sorted(generated.items()))
        )

    # A probe pair the pool already holds is not an independent draw.
    seen: set[tuple[str, str, str]] = set()
    unique: list[PooledPair] = []
    for pair in pairs:
        key = (pair.corpus, pair.left, pair.right)
        if key in seen:
            continue
        seen.add(key)
        unique.append(pair)

    args.sheet.parent.mkdir(parents=True, exist_ok=True)
    args.key.parent.mkdir(parents=True, exist_ok=True)
    sheet = build_sheet(unique, sources)
    args.sheet.write_text(json.dumps(sheet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_key(unique, args.key)
    pooled = sum(1 for pair in unique if pair.stratum == "pooled")
    print(f"{len(unique)} pairs ({pooled} pooled, {len(unique) - pooled} probe) -> {args.sheet}")


if __name__ == "__main__":
    main()
