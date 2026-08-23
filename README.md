# Code Steward

**Context-efficient code intelligence and stewardship for Claude Code.**

Code Steward is an early-stage project for helping coding agents work more carefully with existing code while using less long-lived context. The central idea is simple: the main coding session should receive **decisions and selected code units, not the full history of repository exploration**.

Instead of repeatedly searching large files, rediscovering callers and tests, or creating functionality that already exists, Code Steward is designed to build a compact map of a codebase, retrieve the most relevant existing units, and delegate deeper investigation to isolated review agents.

> **Project status:** early development. The architecture is being implemented and tested first against Python and FastAPI codebases. The public API, plugin behavior, and storage format may change.

## Goals

Code Steward is being designed around two forms of stewardship:

1. **Steward the context window.** Keep broad repository exploration, graph traversal, history inspection, and duplicate analysis out of the main coding context whenever they can be handled deterministically or inside a disposable subagent context.
2. **Steward the codebase.** Search before implementation, reuse existing behavior where appropriate, understand the impact of changes, and avoid unnecessary duplication or parallel abstractions.

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

## Planned architecture

Code Steward is intended to combine several complementary sources of code intelligence rather than rebuild all of them.

### Local Python and FastAPI index

The first implementation targets Python and FastAPI and will extract information that is cheap and deterministic to obtain:

- functions, classes, and exact source boundaries
- function signatures and parameter names
- type annotations and return types
- docstrings and compact purpose summaries
- FastAPI routes, response models, and dependencies
- source hashes and Git metadata
- optional stable aliases and conceptual code-unit regions

### Low-context retrieval

Candidate generation should happen before model reasoning whenever possible. The initial approach uses structured metadata plus lexical and fuzzy matching, including RapidFuzz-style similarity over names, summaries, signatures, and concepts.

The goal is to reduce a large repository to a small evidence packet before an agent is asked to make an architectural decision.

### Isolated review agents

A reviewer should receive only the task and a small candidate packet. It can then pull exact code units, tests, history, and graph relationships only when needed. Its final result should be compact and structured so that exploratory material does not accumulate in the main coding session.

### Graph Code Review integration

[Graph Code Review](https://github.com/tirth8205/code-review-graph) already provides structural graph capabilities such as callers, callees, tests, flows, change analysis, and minimal-context retrieval. Code Steward is intended to integrate with that capability rather than fork or duplicate the underlying graph engine.

### DRY and clone analysis

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

## Initial scope

The first development target is:

- Python 3
- FastAPI
- Claude Code skills, plugins, and subagents
- local AST-based indexing
- fuzzy and typed candidate retrieval
- exact code-unit extraction
- optional Graph Code Review enrichment
- optional jscpd duplicate evidence

The architecture is intentionally broader than FastAPI so that support for other Python frameworks and languages can be considered later without changing the core model.

## Roadmap

The first public milestones are expected to focus on:

1. repository and plugin scaffold
2. Python AST index and stable unit identifiers
3. FastAPI endpoint enrichment
4. compact candidate search and reviewer packets
5. read-only reuse reviewer agent
6. Graph Code Review integration
7. post-change DRY and blast-radius review
8. benchmarks for context use, retrieval quality, and incorrect reuse decisions

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

Both are deliberately conservative about the retriever's current quality. On `psf/requests` the
production retriever measures **Hit@1 40%, Hit@K 73.33%, MRR 0.500** — the top candidate is
wrong most of the time, and roughly one query in four returns a packet that does not contain
the correct unit at all. The skill and the agent both require verification before any reuse
decision, and neither is permitted to treat "not in the packet" as proof that code is absent.
The reviewer's no-result verdict is `NO_CANDIDATE` ("I did not find it"), not `CREATE`.

Known gaps in this surface:

- The plugin does not install the CLI. `code-steward` must already be on `PATH`
  (`pip install -e .`) for the skill or the agent to do anything.
- There are no commands and no hooks. Indexing is not automatic; the index goes stale until
  `code-steward update <path>` or `code-steward build` is run.
- The reviewer agent holds `Bash` because that is the only way to invoke the CLI. Its
  read-only contract is enforced by instruction, not by the tool allowlist.

## Why this project exists

Modern coding agents are capable of exploring large repositories, but exploration itself has a cost. Repeated searches, broad file reads, graph results, test discovery, and Git history can consume a substantial portion of a long-running context window. That material is often useful only long enough to make one decision.

Code Steward is an experiment in moving that work into deterministic indexes and short-lived review contexts, while preserving the information the main coding agent actually needs to make and implement a sound change.

## Contributing

The project is in an early architecture phase. Contributions and design discussion are welcome, particularly around context-efficient retrieval, code-unit identity, Python/FastAPI static analysis, and measurable evaluation of agent context use.

Contributor guidance lives in [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

Code Steward is released under the MIT License. See [`LICENSE`](LICENSE).

## Acknowledgments

Code Steward is designed to integrate with, learn from, and complement existing open-source code intelligence and duplicate-analysis tools. In particular, the project draws on ideas and capabilities from Graph Code Review and jscpd. Code Steward is an independent project and is not affiliated with those projects or Anthropic.
