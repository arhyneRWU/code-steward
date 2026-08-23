# Context-aware docstrings: what was measured, and what survives

Status: the design this file originally carried was **measured and
abandoned** the same day it was written. What remains is a much
smaller build. Both halves are recorded here, because knowing why the
larger idea died is what stops it being proposed again.

## The idea

Use the `trace` follower to bundle a function with its callers,
callees and tests, and use that bundle two ways:

1. **`docs drift`** -- find documented functions whose docstring no
   longer matches the code, and have an agent adjudicate.
2. **`docs fill`** -- find undocumented functions and have an agent
   write docstrings that are aware of how the function is actually
   called.

The original design specified drift first, on the reasoning that it
was the measurable half and would serve as fill's only automated
check. **That ordering was backwards, and drift does not survive at
all.**

## What killed drift

Drift needed a cheap way to nominate suspects before spending an
agent on them. Three signals were specified. None survived contact
with measurement, and the measurement was cheap enough that it should
have happened before the design was written.

### Signal 1 -- docstring names an identifier absent from the body

Predicted in the original design to be "the highest-precision signal
available". Measured on this repository's own `src/`, 76 documented
functions:

| Body model | Nominated | True positives |
| --- | --- | --- |
| Generous (names, attributes, params, nested defs, string tokens) | 0 | 0 |
| Strict (identifiers only) | 5 | **0** |

On third-party corpora, with the strict model:

| Package | Documented fns | Nominated | Rate |
| --- | --- | --- | --- |
| `_pytest` | 794 | 162 | 20.4% |
| `packaging` | 246 | 79 | 32.1% |
| `requests` | 163 | 41 | 25.2% |
| `urllib3` | 163 | 39 | 23.9% |
| Django (backtick-only) | 3,046 | 122 | 4.0% |

Hand-read: 28 of 28 urllib3 nominations are false positives, 24 of 24
Django, 5 of 5 here.

**The signal has no operating point.** Loosen the body model and it
finds nothing; tighten it and it finds only false positives. There is
no threshold between those states to tune toward.

The failure families are structural, not tunable:

- **Sphinx cross-reference roles.** ``:meth:`start_connect` `` is
  *by definition* a reference to code elsewhere.
- **Type names in prose.** "Returns a `QuerySet`" -- named because it
  is the return type, absent because a factory built it.
- **`.. versionchanged::` and deprecation notes.** These name removed
  or renamed identifiers, so absence from the body is guaranteed by
  construction.
- **Deliberate "see also" pointers** to sibling functions.
- **Settings and attribute names** owned by another object.
- **Private-name convention**: docstring says `start_connect`, body
  says `self._start_connect`.

Note what that list is. The signal fires on docstrings that name the
types they return, the settings they read, and the siblings they
mirror. `"""Return the name."""` never trips it. **The signal is
inversely correlated with docstring quality.**

It is also published research -- Kabir et al., *Detecting outdated
code element references in software repository documentation*, EMSE
2023 -- so it was neither novel nor untested.

### Signal 2 -- stale by git blame

Already shipped. `docvet` (PyPI, v1.15.1, 28 releases) has a
`freshness` check whose `stale-drift` rule compares git blame
timestamps on code lines against docstring lines, with a configurable
threshold. `docvet freshness --mode drift` is signal 2.

`docvet` also defaults to git-diff scope, which the original design
presented as a deliberate choice of its own, and ships a
`trivial-docstring` rule, which was the design's "deliberately
skipped" section.

This is the `jscpd` precedent exactly: an off-the-shelf tool that
already does the thing. The original design has a section titled "Why
this and not an off-the-shelf tool" that checked pydoclint, darglint
and Ruff, and missed the one tool that *is* the feature.

One useful finding survives the deletion, recorded for whoever
revisits this: **per-line-range blame is the wrong primitive.** One
whole-file `git blame -w -M --porcelain`, sliced in Python, is
cheaper than three line-range blames of the same file, because
blame's cost is walking the file's history and `-L` does not shorten
that. Measured here: 19 whole-file blames took 0.57 s against 4.18 s
for 152 per-range blames. `-M` itself is free; `-C` costs ~30%.

### Signal 3 -- visibility claim contradicted by callers

No volume. Docstrings in this repository making a privacy claim
(`internal`, `private`, `do not call`, `not part of the public`):
**0 of 281**. Elsewhere: `requests` 1.2%, `packaging` 2.4%,
`_pytest` 3.9%, `urllib3` 0%.

That small share then has to survive edge resolution. Of 3,485
`CALLS` edges in this repository, 820 resolve to a unit (**23.5%**),
and only 252 of those are cross-file. Expected yield is 0-2
nominations per repository -- not a stratum, and not a subsystem.

### The kill criterion was itself broken

The original design pre-registered: *precision at least twice the
control base rate, Fisher's exact p < 0.05, per signal.* That
conjoins a point-estimate gate at exactly the true value with a test
whose null is RR = 1. Simulated probability that a signal which
genuinely doubles the base rate survives:

| True base rate | n=33/arm | n=100 | n=300 | n=800 |
| --- | --- | --- | --- | --- |
| 0.05 | 0.023 | 0.199 | 0.527 | 0.522 |
| 0.10 | 0.112 | 0.434 | 0.518 | 0.505 |
| 0.20 | 0.315 | 0.526 | 0.510 | 0.516 |
| 0.33 | 0.546 | 0.518 | 0.510 | 0.514 |

It asymptotes at ~0.51 at any n. This is not an underpowered design
that a larger labelling budget would rescue: 1,600 labels buy the
same coin flip as 66. Had the study run, a null would have been
indistinguishable from a real 2x signal, and nothing in the procedure
would have revealed that.

**If a criterion of this shape is ever pre-registered again**, state
it as a one-sided 95% CI lower bound on the risk ratio exceeding the
threshold, and simulate its power before committing to it.

Two further defects, recorded so they are not rediscovered:

- **Signals 1 and 3 cannot be blinded.** Their nomination condition
  is visible in the case the labeller reads, so "precision" would
  measure the rate at which a labeller applies the signal's own rule.
- **The synthetic control exercises no signal.** A body mutation adds
  and removes no docstring identifiers, and either never moves blame
  (uncommitted) or always moves it (committed). It is a positive
  control for *adjudication*, not nomination.

## What survives

**`fill` is the buildable half**, which is the reverse of the
original ordering. Drift needed a cheap nomination signal and has
none. Fill needs one too -- and has a perfectly reliable one:
`doc_text == ""`. A function either has a docstring or it does not.

And it needs no new subsystem.

### The build

A selector on the command that already exists:

    code-steward trace --undocumented [--base REF]

Emit one `trace` bundle per undocumented function in scope. The agent
already in the loop writes the docstring. Code Steward assembles and
does not judge, which is the only architecture this project has
measured -- a cheap model handed an assembled bundle scored 0.917
with 30/30 on negatives, against a larger reviewer handed a ranked
packet false-positiving on a third (`benchmarks/verdict/bundle_score.py`).

No `docdrift.py`, no `docfill.py`, no `gitmeta.line_range_commits()`,
no model client in the dependency tree, no API key, and nothing
leaves the machine that was not already going to the agent.

### Why not adopt an existing generator

`wright` (PyPI `wright`, `surajs1999/WrightAI`) does caller- and
callee-aware LLM docstring generation with a call-graph ordering. It
is real prior art on the *idea* and is not adoptable here:

- **AGPL-3.0.** Code Steward is MIT. Depending on it or customising
  it is a derivative work and would force relicensing.
- **It is the client half of a hosted service.** Its dependencies
  include `workos`, `supabase`, `brevo-python`, `sentry-sdk`,
  `python-jose`, `slowapi`, `fastapi` and `uvicorn`. Run against a
  private repository, source leaves the machine through several
  channels, one of which fires on crashes the user never sees.
- **One release, 0.1.0, 0 stars, no published numbers.** Evidence
  that someone tried the idea; not evidence that it works.

It is prior art on novelty, not on quality. Those are separate claims
and should not be conflated.

### What the bundle must fix first

Three defects found while reviewing the design against the code.
These block `--undocumented` and are the actual work:

1. **`render_markdown` emits `purpose`, not `doc_text`.**
   `indexer._purpose` falls back to the function name with
   underscores stripped, so an undocumented callee renders with a
   pseudo-docstring like "resolve target". An agent cannot tell that
   from a real one-line summary. Either `--undocumented` needs its
   own renderer or `render_markdown` needs a flag.
2. **The index is stale on changed files.** `check_files` already
   re-parses changed paths rather than trusting the DB, because
   indexed line numbers are from a prior revision. `build_slice`
   looks the target up in `all_units` and returns `None` if absent --
   so a function *added* in the change, the certain case for fill,
   cannot be sliced at all. The spec must say whether `--undocumented`
   requires a fresh `update` or re-indexes in memory.
3. **"What callers do with the result" is not stored.**
   `evidence["lines"]` records `node.lineno` with no `col_offset` and
   no parent reference, so whether a caller subscripts, awaits or
   discards the result is not derivable. Either re-parse caller files
   or drop the claim.

### What is dropped from the original fill design

**Topological ordering by callee.** Measured: 82 undocumented
functions in `src/code_steward` form **43 connected components with
34 singletons** over 60 resolved edges. 41% of the work has no
ordering constraint at all, and most components cover two or three
functions. The claim that "by the time a caller's docstring is
written, everything it invokes is already documented" is false at
this resolution. A stable file-and-line order costs nothing and
produces the same result for 41% of nodes.

This was the most elaborate mechanism in the original design and the
one it admitted could not be scored.

**Trivial-function skipping** stays, but reusing what exists rather
than inventing a notion: skip a unit if `indexer._accessor_role` is
non-empty, the name is a dunder, or the normalised body tokenises
below `similarity.MIN_TOKENS`.

## Numbers, and which corpus each belongs to

Recorded because the original design quoted one of these without its
corpus and the review then conflated two different metrics.

| Quantity | Value | Scope |
| --- | --- | --- |
| Functions with >= 1 resolved neighbour | 54.7% | Django |
| Functions with >= 1 resolved neighbour | 90.4% | Code Steward |
| `CALLS` edges resolving to a unit | 23.5% | Code Steward |
| Signal 1 precision | 0 / 57 hand-read | Code Steward, Django, urllib3 |
| Privacy-claiming docstrings | 0 / 281 | Code Steward |

**These are different measurements.** "Half of Django's functions get
a non-empty slice" and "a quarter of individual call edges resolve"
are both true. Claims about a *path* being complete want the edge
number; claims about a slice being non-empty want the function
number.

## What would have to be true to revisit drift

- An off-the-shelf pass supplies the findings, so nomination is not
  ours to solve. `docvet freshness --format json` is the obvious
  source.
- The contribution is then **adjudication only**: hand an agent the
  slice and get `DRIFT` / `CLEAR` / `UNSURE`. That is the one slot no
  existing tool occupies.
- It is measured as a paired test on one variable -- adjudicate the
  same findings with and without the slice -- which is this project's
  standard and something the original design could not do, because it
  measured nomination and adjudication together against a base rate.

That is a small, honest experiment. It is not this document.
