# Retrieval benchmark

This benchmark is the common measuring stick for Code Steward retrieval experiments.
It exists so that lexical search, query expansion, structural similarity, graph signals,
and later semantic approaches can be compared against the same synthetic repository and
gold queries.

The benchmark deliberately does **not** endorse the current RapidFuzz-based search. The
current implementation is simply the first baseline.

## Design goals

The suite should answer four questions before a retrieval strategy is promoted into the
main architecture:

1. Did retrieval include the code units a reviewer actually needs?
2. Did useful units rank ahead of known traps and unrelated implementations?
3. How much candidate context did retrieval create before any implementation body was
   loaded?
4. Did the retrieval method create redundant candidates that waste reviewer attention
   and context?

The benchmark repository is entirely synthetic. It contains no private or proprietary
source material.

## Cases represented

The v1 corpus includes cases where:

- names are similar but behavior differs
- names differ while behavior overlaps
- a useful function has no docstring
- signatures are similar but intent differs
- a wrapper delegates to a shared implementation
- independent implementations perform overlapping work
- a conceptual Code Steward region spans multiple functions
- queries use `read`/`settings` while code uses `load`/`configuration`
- queries use `save`/`settings` while code uses `write`/`preferences`
- a logout request must connect to session revocation
- related operations such as cache eviction and record deletion must remain distinct
- an abbreviation such as `repo` must connect to `repository`
- several thin wrappers can crowd a packet while sharing one implementation

The vocabulary-mismatch cases are intentionally difficult. They should not be rewritten
to make the current baseline look better. They exist so abbreviation, synonym, project
alias, and query-expansion experiments have a stable target.

## Gold-set format

`cases.json` stores the human-defined retrieval intent for every case.

Each case may provide:

- `id`: stable benchmark case identifier
- `query`: task wording presented to the retriever
- `relevant`: one or more acceptable code-unit IDs
- `traps`: explicitly known false-similarity candidates
- `redundancy_groups`: units known to be substitutable or repetitious in one packet
- `input_types`: optional expected input types
- `return_type`: optional expected return type
- `limit`: candidate-set size
- `category`: the behavior the case is designed to test

A candidate not listed in `relevant` is not automatically declared wrong. The benchmark
uses `traps` only where a particular result is known to be misleading. Likewise,
`redundancy_groups` do not say the units are globally equivalent. They identify a
case-specific set where returning several members wastes candidate slots.

## Metrics

The first evaluator reports:

- `hit_rate_at_k`: fraction of cases with at least one relevant candidate
- `macro_recall_at_k`: mean fraction of relevant units retrieved per case
- `mrr`: mean reciprocal rank of the first relevant candidate
- `known_trap_rate`: fraction of returned candidates that are explicit traps
- `known_redundancy_rate`: fraction of candidate slots consumed by extra members of
  case-specific redundancy groups
- `duplicate_candidate_rate`: fraction of returned slots that repeat the same unit ID
- candidate packet characters and UTF-8 bytes
- indexing and retrieval latency as observational measurements

Exact duplicate IDs are primarily an integrity check. The case-specific redundancy
metric is the more useful measure for future candidate-diversity experiments.

Packet size is reported in characters and bytes, not fake token estimates. Token counts
are model/tokenizer specific. A later benchmark layer can add an explicit tokenizer or
capture actual agent usage, but this suite should not present `characters / 4` as
measured tokens.

Likewise, reviewer decision quality and reviewer/subagent token use are not yet scored.
Those require a controlled reviewer protocol and belong in a later benchmark phase.

## Run the baseline

From the repository root after installing Code Steward:

```bash
python benchmarks/retrieval/run.py
```

The command prints a JSON report. Results are intended to be compared between experiment
branches rather than committed as claims of project performance.

## CI behavior

CI verifies that:

- every gold, trap, and redundancy-group ID exists in the indexed fixture repository
- case IDs are unique
- `relevant` and `traps` do not overlap
- redundancy groups contain at least two unique, non-overlapping members per case
- metric values have valid ranges
- candidate packets contain no exact duplicate unit IDs in the current baseline

CI does **not** require a minimum recall or MRR yet. Establishing a quality threshold
before we have compared plausible retrieval strategies would turn the current baseline
into an accidental architectural commitment.
