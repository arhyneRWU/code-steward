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

---

# Benchmark v2: the retrieval validity matrix

Benchmark v1 above is **frozen** and stays exactly as it is. It is the regression
guard: `benchmarks/retrieval/run.py`, `cases.json`, and `fixture_repo/` must keep
reproducing their existing numbers. Everything in this section is additive and
separately reported.

## Why v1's single number is not enough

v1 reports one metric set from one corpus with one query style. The same
unchanged pipeline scores far worse on a real repository
(`benchmarks/real_repo/retrieval_baseline.py`, `psf/requests` @ `8f8b212d`:
Hit@K 73.33%, MRR 0.500). Three properties of the v1 fixture hide that gap, and
none of them is a retrieval property:

| Gap | v1 fixture | Real repository |
| --- | --- | --- |
| Documentation | 18 of 20 units carry a docstring (90%) | roughly 17% of `src/` |
| Query length | mean 3.7 words | task intents run 15-25 words |
| Candidate window (`limit / units`) | 25-30% | roughly 4% |

Query length matters more than it looks. RapidFuzz `token_set_ratio` normalizes
by the **target** length, so a long query paired with a short `purpose` string
is scored asymmetrically. At 3.7 words that asymmetry is invisible.

The window matters because on a 20-unit corpus a rank-7 result cannot exist, so
`limit=6` makes Hit@K nearly a recall floor rather than a ranking measurement.

## The matrix

`benchmarks/retrieval/matrix.py` evaluates the same gold labels across three
axes and reports the full v1 metric surface plus `Hit@1/3/5`, mean candidates
returned, candidate fill rate, mean query words, and `candidate_window`:

- **documentation**: `documented` (the v1 sources) vs `undocumented`
- **query style**: `short` (v1 `cases.json`) vs `verbose` (`cases_verbose.json`)
- **scale**: `core` (20 units) vs `scaled` (108 units)

```bash
make bench-matrix                  # production retrieve_units (default)
make bench-matrix PIPELINE=search  # bare search_units, what v1 calls
python -m benchmarks.retrieval.matrix --json
python -m benchmarks.retrieval.matrix --output-dir build/bench
```

### Pipeline note

Frozen v1 calls `search_units`. The real-repository baseline calls production
`retrieve_units` (query expansion plus the near-duplicate filter). The matrix
therefore defaults to `retrieve` so its cells are comparable to the real
baseline, and `--pipeline search` reproduces v1's cell exactly. The
`documented/core/short` cell equals the corresponding frozen v1 numbers under
each pipeline; a test asserts this.

## Corpus variants are generated, not vendored

`benchmarks/retrieval/corpus.py` materializes each variant into a temporary
tree at run time from the single v1 fixture.

A second checked-in tree was rejected. Two copies of the same 20 units drift:
edit v1 and the undocumented twin silently becomes a different corpus, at which
point the ablation is no longer an ablation, because the two corpora differ in
more than the axis under test. Generation makes "docstrings removed" the *only*
difference, provable by construction. `strip_docstrings` removes module, class,
and function docstrings with `ast`, inserts `pass` where a body was nothing but
a docstring, and leaves `# code-steward:` tags anchored above their
declarations.

## The verbose query set

`cases_verbose.json` carries the **same case IDs, `relevant`, `traps`,
`redundancy_groups`, `input_types`, `return_type`, and `limit`** as
`cases.json`. Only `query` differs; `assert_label_parity()` enforces that, and
a test fails if a label moves or a query was not rephrased.

The paraphrases are written as behaviour, by someone who does not know the
function names — mean 22.2 words against v1's 3.7. This is the part that is
easy to get wrong: an identifier-shaped paraphrase ("normalize the taxon name
and resolve its aliases") is exactly the query that already succeeds, so lazy
rewording would measure nothing. A test asserts no verbose query contains the
identifier, the spaced identifier, or the unit ID of any of its own gold units.

## Corpus scale

The `scaled` variant grows the corpus from 20 to **108 units**, moving the
window from 26.7% to 4.9% — real-repository territory. It adds two things on
top of the untouched v1 sources:

- **64 unrelated distractors**: eight business domains crossed with eight
  operations. These occupy corpus slots and nothing else.
- **24 saturating wrappers** (`saturating.py`): near-identical thin wrappers
  that all delegate to the same shared normalization, mirroring the existing
  `api`/`cli` wrapper pair. Distractors alone would raise the unit count without
  making retrieval harder; the saturating namespace is what actually competes
  for the top of the ranking and stresses the near-duplicate filter.

Both are **generated from a small table**, not hand-written. That is the whole
point of the choice: the maintenance cost of the scaled corpus is one
`_DOMAINS` tuple, one `_OPERATIONS` tuple, and one channel list — roughly 40
lines — instead of 88 hand-written functions that a future fixture change would
have to be applied to one by one. Generated units are never gold and never
traps, and a test asserts their IDs cannot collide with any labelled unit.

The `core` rows are kept in the report alongside `scaled` so the contribution of
corpus size alone stays visible rather than being folded into the other two
axes.

## What the matrix still cannot see

- **Repository shape.** The fixture has no classes, no inheritance, no `__init__`
  re-exports, no dead code, and no test files competing with source. Real
  corpora do.
- **Gold-label realism.** Labels are still author-declared on synthetic code. A
  real repository's "what should a reviewer see here" is contested.
- **Reviewer outcome.** Decision quality and reviewer token spend are still
  unscored, exactly as v1 states.
- **Docstring quality.** The axis is binary: present or absent. Real docstrings
  are often stale or wrong, which is worse than absent, and nothing here
  measures that.

As with v1, CI checks structure and metric ranges. It does **not** enforce a
quality threshold on any cell.
