# Code Steward

**Context-efficient code intelligence and stewardship for Claude Code.**

Code Steward is an early-stage project for helping coding agents work more carefully with existing code while using less long-lived context. The central idea is simple: the main coding session should receive **decisions and selected code units, not the full history of repository exploration**.

Instead of repeatedly searching large files, rediscovering callers and tests, or creating functionality that already exists, Code Steward is designed to build a compact map of a codebase, retrieve the most relevant existing units, and delegate deeper investigation to isolated review agents.

> **Project status:** early development. The architecture is being implemented and tested first against Python and FastAPI codebases. The public API, plugin behavior, and storage format may change.

> **What is measured today:** on `psf/requests`, Code Steward's retrieval is **worse than plain text search** on every ranking metric (see [Measured position](#measured-position)). Its demonstrated value is **compression** — 4,039 bytes of packet against 21,107 bytes of source for the same candidates, and 3.6x fewer wasted bytes per query — not better recall or a cleaner packet. Read the roadmap as a set of open questions, not a set of delivered features.

## Goals

Code Steward is being designed around two forms of stewardship:

1. **Steward the context window.** Keep broad repository exploration, graph traversal, history inspection, and duplicate analysis out of the main coding context whenever they can be handled deterministically or inside a disposable subagent context.
2. **Steward the codebase.** Search before implementation, reuse existing behavior where appropriate, understand the impact of changes, and avoid unnecessary duplication or parallel abstractions.

Both goals reduce to one operational claim: **an agent should read less code, and less irrelevant code, to make the same decision.** Those are two separate claims and the evidence splits between them. Fewer bytes: measured, holds, by a wide margin. A higher *share* of what the agent sees being relevant: measured, and currently false — Code Steward's packets are proportionally noisier than plain keyword search, they are simply much cheaper per unit of noise. See [Measured position](#measured-position).

The intended workflow is:

```text
request
  |
  v
compact code index
  |
  +-- names / signatures / types
  +-- summaries / concepts
  +-- endpoints
  +-- hashes / Git metadata
  |
  v
ranked candidate units
  |
  v
isolated review agent
  |
  +-- REUSE
  +-- EXTEND
  +-- REFACTOR
  +-- CREATE
  +-- UNCERTAIN
  |
  v
main coding agent receives only the selected units and decision
```

## Measured position

Code Steward is validated against `psf/requests` pinned at `8f8b212d`, using 15 hand-verified retrieval cases. Frozen Benchmark v1 runs on a synthetic fixture and reports much better numbers; those numbers are a regression guard against themselves and should not be read as quality on real code.

The control arm is plain text search: drop stopwords from the query, scan every `.py` file case-insensitively for each remaining term, rank units by how many distinct terms they contain. No Code Steward code is involved in its ranking.

| Metric | Code Steward | Text-search control |
| --- | --- | --- |
| Hit@1 | 46.67% | **53.33%** |
| Hit@3 | 60.00% | **80.00%** |
| Hit@K | 73.33% | **86.67%** |
| MRR | 0.550 | **0.667** |
| Bytes handed to the reviewer | **4,039** | 21,107 |

Read that honestly: **the ranker loses on every ranking metric.** The four cases Code Steward missed entirely, the control ranked 1st, 1st, 3rd, and 2nd.

The Code Steward column reflects the current pipeline, which scores whole docstring bodies as well as summaries. Before that change it read Hit@1 40.00% and MRR 0.500; the improvement is real and does not close the gap. `docs/retrieval.md` carries both.

Two things follow.

**What survives is compression, not recall.** 4,039 bytes against 21,107 to inspect the same candidates is a real 5.2x, and it understates the gap: the control arm is handed unit boundaries by the index for free, so an agent with only text search would pay more still to work out where each match begins and ends.

**What does not survive is the premise that fuzzy field scoring is the differentiator.** It is not. The fix is to adopt lexical body matching and fuse it with field scoring, not to keep tuning the weights. Fusing the two candidate lists already reaches Hit@K 100% on all 15 cases, which says the methods are complementary rather than competing.

### Noise: measured, and the answer is split

The project's goal is to reduce what an agent has to read *and* how much of it is irrelevant. Both halves are now measured.

Every candidate either arm returned — 204 across the 15 cases — carries a relevance label. The candidate sets were captured before docstring-body indexing landed, so the precision figures below describe that pipeline; re-running the arms regenerates any candidate the labels do not yet cover, and `precision.py` refuses to score a packet with an unlabeled candidate rather than quietly understating noise. Labels were assigned blind: the labeler saw the query and the unit's source, never which arm produced the candidate, its rank, or the recorded gold unit. As a check on the labels themselves, they independently reproduced the gold key on 15 of 15 cases.

| Arm | Precision (strict) | Precision (lenient) | Noise rate | Wasted bytes per query |
| --- | --- | --- | --- | --- |
| Code Steward | **14.91%** | 43.86% | 56.14% | **2,288** |
| Text-search control | 12.50% | **57.50%** | **42.50%** | 8,124 |

The answer splits cleanly, and neither half should be quoted without the other:

- **By share of the packet, Code Steward is noisier.** 56% of what it returns is judged not worth reading, against 42% for keyword search. It shows the agent a *higher proportion* of junk.
- **By bytes, Code Steward wastes 3.6x less.** 2,288 wasted bytes per query against 8,124. The junk it shows is far cheaper to skip.

So the packet format is doing real work and the ranking is not. Code Steward is currently a good compressor wrapped around a poor selector. That is a fixable shape — the fix is roadmap item 2, and it is why item 1 was to build this measurement first.

One incidental finding: all four units the benchmark had declared "traps" were judged *plausible*, not irrelevant. They are reasonable near-misses, not noise, so the trap rate reported elsewhere in this project was never a noise metric and should not be read as one.

Reproduce with `benchmarks/real_repo/label_sheet.py` (emits blind sheets) and `benchmarks/real_repo/precision.py` (scores them). Labels live in `benchmarks/real_repo/requests_candidate_labels.json`.

### Validity threats on record

- The benchmark queries were written while reading the Requests source, so their wording shares vocabulary with the code. That inflates any lexical method, and it inflates the raw-text control more than the field-based ranker. A query set written from public documentation would test it.
- Frozen Benchmark v1's fixture documents 19 of 20 units and uses queries averaging under four words. Real code does neither.

Full numbers, per-case results, and diagnosis live in [`docs/retrieval.md`](docs/retrieval.md). The control arm is `benchmarks/real_repo/grep_baseline.py`; run it with `make bench-grep`.

## Architecture

Code Steward combines several complementary sources of code intelligence rather than rebuilding all of them. Each subsection below states whether the piece is built, tested and rejected, or not yet implemented.

### Local Python and FastAPI index

The first implementation targets Python and FastAPI and extracts information that is cheap and deterministic to obtain:

- functions, classes, and exact source boundaries
- function signatures and parameter names
- type annotations and return types
- docstrings and compact purpose summaries
- FastAPI routes, response models, and dependencies
- source hashes and Git metadata
- optional stable aliases and conceptual code-unit regions

### Low-context retrieval

Candidate generation should happen before model reasoning whenever possible. The current implementation scores five fields per unit — purpose, signature, concepts, name, and qualname — with RapidFuzz-style similarity. The purpose field scores the better of the docstring summary and the whole docstring body, so documentation below the summary line reaches the ranker without reaching the packet.

The goal is to reduce a large repository to a small evidence packet before an agent is asked to make an architectural decision. The packet part works. The ranking does not yet beat a stopword-stripped keyword scan. Indexing docstring bodies recovered part of the gap and none of the Hit@K gap, which places the remaining signal in **code** bodies — identifiers such as `rebuild_proxies` — that no scored field currently reads. See [Measured position](#measured-position).

### Isolated review agents

A reviewer should receive only the task and a small candidate packet. It can then pull exact code units, tests, history, and graph relationships only when needed. Its final result should be compact and structured so that exploratory material does not accumulate in the main coding session.

### Structural graph integration (tested, not adopted)

An earlier plan was to enrich retrieval with an external structural graph such as [Graph Code Review](https://github.com/tirth8205/code-review-graph). That plan was tested and dropped.

Code Steward extracts its own conservative `CALLS` edges. Reranking candidates by one resolved `CALLS` hop moved no retrieval metric in any direction — not Hit@K, not MRR, not the trap rate. Importing a second, less carefully verified source of the same edge type cannot be justified on ranking grounds when the carefully verified one does nothing. The verdict and its caveat — only 27.72% of extracted edges resolve to indexed units, so this rejects the tested fusion at the current resolution rate rather than structural retrieval in general — are recorded in [`docs/retrieval.md`](docs/retrieval.md).

Structural relationships are still stored and still useful for impact analysis and test discovery. They are simply not a ranking input, and the case for an external graph has to rest on a capability other than ranking.

### DRY and clone analysis (not implemented)

[jscpd](https://github.com/kucherenko/jscpd) provides mature duplicate-code detection. Code Steward is intended to treat clone findings as evidence for a reuse or refactoring decision, not as an automatic instruction to abstract every duplicated block.

## Code-unit addressing

Ordinary Python functions and classes are addressed from native AST boundaries and require no source modification. A one-line Code Steward tag can optionally give the next declaration a stable semantic ID:

```python
# code-steward: unit taxonomy.normalize
@cached
def normalize_taxon(name: str) -> Taxon:
    """Resolve a supplied name to its accepted taxon."""
    ...
```

The tag must immediately precede the declaration or its first decorator. It replaces the generated module/symbol ID for that unit rather than creating a second search candidate.

Paired tags are reserved for conceptual regions that span multiple native declarations:

```python
# code-steward: begin taxonomy.validation


def validate_name(name: str) -> None: ...


def validate_rank(rank: str) -> None: ...


# code-steward: end taxonomy.validation
```

Human documentation remains in normal language-native documentation such as Python docstrings. Hashes, Git metadata, callers, dependencies, and other generated facts stay in the index, never in source tags.

For the full draft semantics being tested, see [`docs/tag-protocol.md`](docs/tag-protocol.md).

## Design principles

- **Search before implementation.**
- **Reuse before creating parallel behavior.**
- **Do not abstract merely because code looks similar.**
- **Use deterministic tools before spending model tokens.**
- **Keep repository exploration out of the parent context when possible.**
- **Return compact decisions, not investigation transcripts.**
- **Prefer integration with mature tools over unnecessary reimplementation.**
- **Measure context savings and decision quality, not just feature count.**
- **Measure against a control, not against yourself.** Every feature that claims to beat ordinary agent behavior is compared to ordinary agent behavior on the same cases. A number that only improves against a previous version of Code Steward proves nothing about whether Code Steward is worth running.
- **Publish results that go against the project.** The text-search control arm and the rejected graph fusion are both in this README because a tool that hides its negative results cannot be trusted about its positive ones.

## Initial scope

The first development target is:

- Python 3
- FastAPI
- Claude Code skills, plugins, and subagents
- local AST-based indexing
- fuzzy and typed candidate retrieval
- exact code-unit extraction
- optional jscpd duplicate evidence (not implemented)

The architecture is intentionally broader than FastAPI so that support for other Python frameworks and languages can be considered later without changing the core model.

## Roadmap

### Built

- repository and plugin scaffold
- Python AST index with stable unit identifiers and optional source tags
- FastAPI endpoint enrichment
- compact candidate search and reviewer packets (`search`, `packet`, `read`, `map`)
- read-only reuse reviewer agent and the search-before-implement skill
- conservative `CALLS` and `TESTED_BY` relationship extraction
- Frozen Benchmark v1, a validity matrix, real-repository validation on `psf/requests`, and a text-search control arm
- docstring-body indexing as a scoring input
- blind candidate labeling and packet precision/noise measurement
- documentation coverage enforcement in CI

### Next, in priority order

1. **Adopt lexical matching.** Score body text, then fuse lexical and field scoring with tuned weights. Equal-weight rank fusion already reaches Hit@K 100% but dilutes MRR below the control, so equal weights are the wrong answer to the right idea.
2. **Write a second query set from documentation rather than source**, to size the vocabulary-overlap bias in every number above.
3. **Fix `_module_key` for src-layout projects**, which currently caps `TESTED_BY` at 13 edges and degrades call resolution.
4. **Post-change DRY and blast-radius review.**

### Deliberately not doing

- **External structural graph integration for ranking.** Tested, no metric moved. See [Structural graph integration](#structural-graph-integration-tested-not-adopted).
- **Further tuning of the existing five-field fuzzy weights.** The control arm shows the ceiling of that approach is below plain keyword search.

## Claude Code plugin surface

Code Steward ships a small plugin surface so an agent can use the indexer without a human
driving the CLI by hand.

```text
.claude-plugin/plugin.json
skills/searching-before-implementing/SKILL.md   # the search-before-implement workflow
skills/searching-before-implementing/references/retrieval-limits.md
agents/reuse-reviewer.md                        # read-only reviewer subagent
```

- **`searching-before-implementing`** teaches the workflow: run `code-steward packet` before
  broad exploration, treat candidates as evidence rather than answers, read the minimum number
  of unit bodies, classify the change, and fall back to ordinary exploration when the packet is
  insufficient. It states plainly when Code Steward should *not* be used.
- **`reuse-reviewer`** is the "isolated review agent" box in the diagram above. It receives a
  task, runs `packet` and `read` in its own context, and returns a compact structured decision
  so candidate evaluation never lands in the main session.

Both are deliberately conservative about the retriever's current quality, for the reasons set
out in [Measured position](#measured-position): the top candidate is wrong most of the time,
roughly one query in four returns a packet that does not contain the correct unit at all, and
a plain keyword scan does better on both counts. The skill and the agent both require
verification before any reuse decision, and neither is permitted to treat "not in the packet"
as proof that code is absent. The reviewer's no-result verdict is `NO_CANDIDATE` ("I did not
find it"), not `CREATE`.

Known gaps in this surface:

- The plugin does not install the CLI. `code-steward` must already be on `PATH`
  (`pip install -e .`) for the skill or the agent to do anything.
- There are no commands and no hooks. Indexing is not automatic; the index goes stale until
  `code-steward update <path>` or `code-steward build` is run.
- The reviewer agent holds `Bash` because that is the only way to invoke the CLI. Its
  read-only contract is enforced by instruction, not by the tool allowlist.
- Neither the skill nor the agent runs a text search alongside the packet, even though the
  control arm shows that would find units the packet misses. Doing so is roadmap item 2.

## Why this project exists

Modern coding agents are capable of exploring large repositories, but exploration itself has a cost. Repeated searches, broad file reads, graph results, test discovery, and Git history can consume a substantial portion of a long-running context window. That material is often useful only long enough to make one decision.

Code Steward is an experiment in moving that work into deterministic indexes and short-lived review contexts, while preserving the information the main coding agent actually needs to make and implement a sound change.

## Contributing

The project is in an early architecture phase. Contributions and design discussion are welcome, particularly around context-efficient retrieval, code-unit identity, Python/FastAPI static analysis, and measurable evaluation of agent context use.

Contributor guidance lives in [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

Code Steward is released under the MIT License. See [`LICENSE`](LICENSE).

## Acknowledgments

Code Steward learns from existing open-source code intelligence and duplicate-analysis tools, in particular Graph Code Review and jscpd. Neither is currently a dependency: graph-based reranking was tested and rejected on measured evidence, and clone analysis is not implemented. Code Steward is an independent project and is not affiliated with those projects or Anthropic.
