# The companion contract

**Status: partly implemented, and amended by measurement.** One
piece is now built and measured -- external neighbourhood enumeration
through `trace --members-from`, see [`context-cost.md`](context-cost.md).
The rest is still specification. This document
says what an integration between Code Steward and
[Graph Code Review](https://github.com/tirth8205/code-review-graph)
would have to satisfy before it could be built. It deliberately stops
short of building it, and one section below records why part of it
cannot be designed yet.

## Why a contract rather than an integration

Two projects that answer different questions can compose or they can
quietly become dependencies of each other. The difference is whether
the boundary is written down first.

Graph Code Review answers *what breaks if I change this* — blast
radius from a diff, over a typed edge graph across roughly 55
languages. Code Steward answers *what is the smallest thing you can
read to decide* — a compact packet, in Python only. The overlap is
their retrieval layer and this project's, which are the same design
arrived at independently and neither of which should be presented as a
differentiator against the other. See
[the comparison in the README](../README.md#code-steward-and-graph-code-review).

An earlier plan was to use their graph to improve Code Steward's
ranking. That was tested and rejected on measured evidence: reranking
by one resolved `CALLS` hop moved no retrieval metric in any
direction. The contract below therefore touches ranking nowhere. Any
value it carries has to come from somewhere else.

## The three rules that cannot be relaxed

These extend the [external graph facts](relationships.md#external-graph-facts)
rules already specified for this project. Nothing here weakens them.

**1. No benchmark number may change based on whether their tool is
installed.** The frozen benchmark, the real-repository validation, and
the similarity gold set must all be reproducible from this repository
and a Python interpreter alone. An integration that could move a
published figure by being present is not an integration, it is a
hidden dependency. This is enforceable and must be enforced by a test,
not by convention.

**2. External facts live in the opt-in store and never in
`hard_relationships` or `soft_relationships`.** Provenance separates
extractors this project controls and can reproduce. Their `graph.db`
is a different category: its availability, version, schema, and
completeness are outside this project's control. Reading it is an
explicit pass, never a side effect of `build` or `update`.

**3. A consumer gates on completeness and staleness before reading.**
A partially built external graph answers queries about the fraction of
the repository it has seen, usually without signalling that it is
incomplete. An ungated consumer records confident facts about a
sample. Gating means: the graph's own coverage marker is read first,
its commit or content hash is compared against the indexed tree, and a
graph that cannot prove currency is treated as absent.

## What the integration would actually read

**Amended after measurement.** This section originally read "never
for candidate generation and never for scoring". The scoring half
stands and was never in doubt. The other half was written before any
evidence existed, and the evidence, when it arrived, contradicted it:
on 200 Django functions their node selection rendered through this
project's bundle reached **+0.207 caller recall** over this project's
own selection, at a median of **24 bytes fewer**. See
[`context-cost.md`](context-cost.md).

The rule is therefore narrowed to what was actually tested and
rejected:

- **Permitted: neighbourhood enumeration.** Their graph may decide
  *which units belong in a slice*, through `trace --members-from`,
  which accepts a member list from any producer and knows nothing
  about theirs.
- **Still forbidden: ranking and scoring.** Reranking retrieval by
  one resolved `CALLS` hop was measured and moved no metric in any
  direction. Nothing here revisits that.

The distinction is real rather than verbal: enumeration answers *what
is adjacent*, which their graph demonstrably knows better, while
ranking answers *what matters most*, where the measured answer is
that it adds nothing.

Their graph is also queried for facts about *one already-selected
unit*, never for scoring:

| Fact | Why it belongs in a decision, not a ranking |
| --- | --- |
| Who calls this unit | A reuse candidate with fifteen callers is a different decision from one with none, whichever ranked higher. |
| Whether it is tested | Reusing untested code and reusing covered code are different risks. |
| What its blast radius is | An EXTEND verdict on a hub is a bigger commitment than on a leaf. |

Each of these enriches a verdict a reviewer has already reached. None
of them reorders a candidate list. That separation is the whole point
of the contract: it is the one shape the measured evidence does not
already argue against.

## Absent, stale, or wrong

The contract has to say what happens in each case, because in practice
one of them is always true.

**Absent.** The default. Every Code Steward output must be complete
and correct without the external graph. A packet is not degraded by
its absence and carries no placeholder for it. No warning, no nag —
absence is the supported configuration.

**Stale.** Detected by comparing the graph's recorded commit or
content hashes against the indexed tree. A stale graph is treated
exactly as an absent one. It is not partially trusted, and facts from
it are not shown with a caveat: a caveat in a packet is a cost the
reader pays to reach the same decision they would have reached without
the fact at all.

**Wrong.** The hard case, because it is silent. Their edges are
derived by a different extractor with different resolution rules, so a
`CALLS` edge they report and this project does not is not evidence of
a bug in either. Three consequences:

- External facts are always attributed in the packet — labelled as
  theirs, never merged into Code Steward's own edges.
- Where both projects have an opinion and they disagree, Code
  Steward's own edge wins, because it is the one this project can
  reproduce and test.
- No verdict may rest on an external fact alone. A reviewer that
  cannot reach its conclusion without their graph must return
  `UNCERTAIN`, not a confident verdict backed by an unverifiable
  claim.

## The candidate this enriches

Reuse detection now exists — `code-steward similar` and
`packet --reuse`, described in [`docs/similarity.md`](similarity.md) —
so the enrichment above has something concrete to attach to.

A reuse candidate carries what this project can derive: an overlap
score, the units it duplicates, and its own conservative `CALLS` and
`TESTED_BY` edges. What it does not carry is coverage across languages
this project does not parse, or a blast radius. Those are the facts
worth asking their graph for, and only after a candidate has been
selected.

One consequence of the shipped arm is worth stating here, because it
bounds what the enrichment can be trusted to say. Shingle comparison
finds copies that were pasted and tidied; it does not find a function
independently reimplemented in different words. An enrichment layer
built on top inherits that blind spot exactly, and must not be
described as an answer to *does this exist anywhere* — only to *does
this text already exist here*.

## What this contract is not

- Not a dependency. Neither project may require the other to run.
- Not a ranking input. Tested, rejected, and not revisited here.
- Not a claim of measured value, **except for the one part that now
  is**. Neighbourhood enumeration has been measured on 200 Django
  functions and the result is in [`context-cost.md`](context-cost.md).
  Everything else in this document remains a design constraint set,
  and a design that has not been measured is a hypothesis.
