# Reuse similarity

Code Steward has two goals. One is to send an agent a smaller, more
precise packet. The other is to answer *does this already exist*
before an agent writes it again.

The second never had a number attached to it, even though a
similarity function had shipped since the beginning:
`retrieval.metadata_similarity`, used to deduplicate a result set.
This is the measurement that gave it one, and that picked the
mechanism now used for reuse detection.

## What was measured

Given one function, find the functions already in the same repository
that a reviewer would call reusable — and stay quiet when there are
none. Three public corpora pinned to full commit SHAs, 308 pairs
labelled blind, four arms scored from one label file.

The protocol, the corpora, the sampling rule, and the known
limitations are in
[`benchmarks/similarity/README.md`](../benchmarks/similarity/README.md).
It was written before any pair was labelled.

## The arms

| Arm | What it sees |
| --- | --- |
| `token-shingle` | five-token shingles of normalised bodies; Jaccard overlap. **The control.** No model of code at all. |
| `jscpd` | copy-paste spans from an off-the-shelf clone detector |
| `metadata-similarity` | `retrieval.metadata_similarity` exactly as it ships — names, purposes, signatures, never a body |
| `body-rapidfuzz` | RapidFuzz `token_set_ratio` over whole normalised bodies; the arm Code Steward would most plausibly ship next |

## Result

### Macro, mean over the three corpora

| Arm | Precision | Recall (in pool) | F1 | Bytes | Unlabelled returned |
| --- | --- | --- | --- | --- | --- |
| **token-shingle** | **1.000** | **0.406** | **0.577** | **37,342** | 0 |
| jscpd | 0.878 | 0.356 | 0.506 | 135,934 | 0 |
| metadata-similarity | 0.667 | 0.271 | 0.385 | 85,145 | 0 |
| body-rapidfuzz | 1.000\* | 0.210 | 0.321 | 89,400 | **44** |

\* over labelled pairs only — see the bracket below.

### Per corpus

| Corpus | Arm | P | R | F1 | Bytes | Unlabelled |
| --- | --- | --- | --- | --- | --- | --- |
| home-assistant | token-shingle | 1.000 | 0.390 | 0.561 | 7,758 | 0 |
| home-assistant | jscpd | 0.967 | 0.377 | 0.542 | 35,415 | 0 |
| home-assistant | body-rapidfuzz | 1.000 | 0.247 | 0.396 | 15,616 | 11 |
| home-assistant | metadata-similarity | 0.600 | 0.234 | 0.336 | 20,720 | 0 |
| airflow | token-shingle | 1.000 | 0.429 | 0.600 | 15,612 | 0 |
| airflow | body-rapidfuzz | 1.000 | 0.371 | 0.542 | 16,218 | 4 |
| airflow | jscpd | 0.833 | 0.357 | 0.500 | 57,884 | 0 |
| airflow | metadata-similarity | 0.667 | 0.286 | 0.400 | 36,628 | 0 |
| django | token-shingle | 1.000 | 0.400 | 0.571 | 13,972 | 0 |
| django | jscpd | 0.833 | 0.333 | 0.476 | 42,635 | 0 |
| django | metadata-similarity | 0.733 | 0.293 | 0.419 | 27,797 | 0 |
| django | body-rapidfuzz | 1.000 | 0.013 | 0.026 | 57,566 | 29 |

Every figure comes from
[`benchmarks/similarity/scores.json`](../benchmarks/similarity/scores.json),
reproducible with `make bench-similarity`.

## What this says

**Token shingles came first on every axis, on every corpus.**
Precision 1.000 in all three, the best F1 in all three, and 2.3× to
3.6× fewer bytes than the next arm. No more sophisticated arm bought
anything measurable here.

**`metadata_similarity` came last of the three evaluable arms.** Macro
F1 0.385 against 0.577, at 2.3× the bytes. On Home Assistant its
precision is 0.600 — two of every five pairs it surfaces are noise.
Reading names, purposes, and signatures while never reading a body is
a handicap for this particular question.

**`body-rapidfuzz` is not measurable from this pool, and its 1.000 is
not a result.** It was not one of the three generators, so its ranking
reaches pairs nobody judged — 52 of 90, and 29 of 30 on Django. Its
precision is a bracket, not a number: **0.033 to 1.000 on Django**,
0.42 to 1.00 macro-pessimistic to macro-optimistic. Publishing the
1.000 alone would report a hole in the data as a result. The arm is
unevaluated.

**The probe stratum is 0 positives out of 45.** A generator-free
random sample of pairs from the same units contains no reuse
candidates at all, in any of the three corpora. That is the base rate
the pooled 86.6% sits above, and the main evidence that the pool is
finding something real rather than that the labeller was generous.

**Django was chosen as the hard-negative corpus and did not behave
like one.**
Its pooled positive rate is 83.7%, against Airflow's 81.7%. Django has
real intra-file duplication — parallel `get_fallback_sql`
implementations, mirrored operator dunders, repeated
`_get_condition_sql` — that a clone detector finds easily. The corpus
did not do the job it was chosen for. Its value here turned out to be
different and still real: it is the only corpus where the control does
*not* score a perfect 1.000, and the only one where jscpd ties it.

## What shipped

The measurement ran first and the mechanism was chosen from it. The
winning arm is now `code_steward.similarity`, promoted unchanged, and
`benchmarks/similarity/generators.py` imports that module rather than
keeping a second copy — so the code that produced this page and the
code that ships cannot report different numbers. A test asserts the
import, and another pins the five constants.

The surface is `code-steward similar`, either against an indexed unit
or against a draft that has not been written yet, and
`code-steward trace --dry`, which reports duplication across every
unit on a call path. The draft path was once the point; measurement
moved it. A sketch finds the duplicate 0.460 of the time and a real
body 1.000, so the reliable moment is after the code exists.

### What the arm catches, and what it does not

Overlap of a fixture function against modified copies of itself:

| Change to the copy | Overlap |
| --- | --- |
| docstring rewritten | 1.000 |
| function renamed | 0.941 |
| whole signature renamed | 0.535 |
| every local variable also renamed | 0.015 |

Normalisation makes docstrings, comments, and formatting free.
Renaming a signature leaves most five-token windows intact. Renaming
every local changes nearly all of them, and overlap collapses.

So a function that was copied, pasted, and tidied is found, and a
function independently reimplemented in different words is not. That
second population is invisible to this arm and its size is unmeasured.
Detecting it needs a structural comparator, which is a different tool.
The limitation is pinned by a test.

### On novelty

The comparison itself is not new. Near-duplicate detection by token
shingling is long-established, and jscpd — a mature implementation of
the same idea — placed second on this benchmark. What is different is
placement: indexed-unit granularity, stable IDs, asked before the code
is written, and returned as a packet an agent acts on rather than a
report a person reads. The edge over jscpd is modest on F1 (0.577 to
0.506) and large on bytes (3.6× fewer), and bytes are what decide
whether the evidence fits in an agent's context.

## How deep the gold set can see

The headline numbers are reported at depth 30. That was a labelling
choice — deep enough to clear 150 pairs, shallow enough that one
person could read every pair properly — and it is tempting to read a
deeper slice of the same ranking and report the better recall.

That does not work, and the reason is the same one that made
`body-rapidfuzz` unreportable. Past the pool depth the arm returns
pairs nobody judged, so its precision is computed over a shrinking
labelled fraction of its own output.

| Depth | Returned | Labelled | Unlabelled | Precision (labelled) | Precision (pessimistic) |
| --- | --- | --- | --- | --- | --- |
| 10 | 30 | 30 | 0% | 1.000 | 1.000 |
| **30** | **90** | **90** | **0%** | **1.000** | **1.000** |
| 60 | 180 | 92 | 49% | 1.000 | 0.511 |
| 120 | 360 | 102 | 72% | 1.000 | 0.283 |
| 240 | 720 | 120 | 83% | 0.992 | 0.165 |
| 480 | 1,440 | 146 | 90% | 0.993 | 0.101 |

The `precision (labelled)` column looks flat and encouraging all the
way down. It is not a result below depth 30. At depth 480 it describes
10.1% of what the arm returned, and the pessimistic bound on the other
89.9% is 0.101. The truth is somewhere between, and this gold set
cannot narrow it.

**So depth 30 is both the pool depth and the measurement ceiling.**
Recall beyond it is not unknown-but-probably-better; it is unknown.
Extending the benchmark deeper means labelling more pairs, not
re-reading the ones already labelled.

Committed at [`benchmarks/similarity/depth.json`](../benchmarks/similarity/depth.json).

### The detection floor, and why it is weaker evidence than it looks

Of the 222 labelled positives, **0 share too few windows for the arm
to see them at any depth.** Median overlap is 0.904, and the 10th
percentile is 0.302.

Read literally that says the arm has no blind spot on this set, and
that its recall of 0.406 at depth 30 is a ranking-depth artifact
rather than a detection failure. The first half of that is not
trustworthy, for a specific reason:

**The pool was partly generated by the arm being measured.** A pair
invisible to shingles could only have entered the gold set through
jscpd or `metadata_similarity`. jscpd is also lexical, so it would
miss the same pairs. That leaves `metadata_similarity` as the only
generator that could have surfaced a reimplementation written in
different words — one generator, at depth 30, out of three.

So the honest statement is not "there is no blind spot." It is that
**this gold set is structurally close to blind to reimplementations**,
and 0 out of 222 is what that looks like from the inside. The
rename-tolerance table above shows the blind spot exists on a
constructed example; how common it is in real code remains unmeasured,
and measuring it needs a pool built by a generator that is not
lexical.

## Threats to validity, on the record

**Recall is recall within the pool.** A pair no generator proposed is
invisible, so every recall figure above is an upper bound. The probe
stratum bounds how bad the miss can be; it does not eliminate it.

**One labeller, no agreement statistic.** There is no second annotator
and therefore no inter-annotator agreement figure for this set. The
labelling conventions were fixed during the first batches and applied
uniformly, including retroactively.

**The labelling conventions are opinionated and they moved the
result.** Two decisions in particular: sibling constructors sharing
only a `super().__init__` call were labelled `unrelated`, and backend
implementations of the same interface that must differ (MySQL vs
SQLite `get_constraints`) were labelled `unrelated` rather than
`same-behaviour`. Both push the positive rate down. A labeller who
called those positive would report higher precision for every arm.

**The unit extractor emits nested functions and their enclosing
function.** Their bodies overlap by construction, so such pairs are
free positives for any lexical arm. They were kept and labelled
`unrelated` rather than filtered, because removing them after seeing
the labels would be tuning the corpus against the result. The fix
belongs in a v2 gold set.

**Pool depth is 30 per generator per corpus, and that is also the
measurement ceiling.** Deeper pooling would change recall. Reading the
existing ranking deeper does not, because past depth 30 most returned
pairs are unlabelled; see [How deep the gold set can
see](#how-deep-the-gold-set-can-see). The depth was chosen before
scoring so one labeller could read every pair properly, and it was not
revisited afterwards.

**This is the second gold set.** The first excluded every decorated
function — 53.3% of comparable units in Home Assistant — because unit
lookup keyed on a function's `def` line while the indexer records a
decorated function's start as its first decorator. Fixing that grew
the corpora by 27% to 133% and invalidated the first set, which could
not be re-scored: 28 of 30 returned pairs fell outside its labels. The
set was rebuilt rather than patched. Direction of the result did not
change; the shipped arm scored higher and `metadata_similarity`
scored lower.

**The reimplementation blind spot is demonstrated but unsized.** The
arm provably misses a function whose every local has been renamed. How
often that happens in real code is not measured here, and this gold
set cannot measure it: two of its three generators are lexical, so the
population is largely absent from the pool by construction.

## The cache was returning noise

Worth recording, because it invalidates an earlier conclusion on this
page's sibling docs rather than adding to them.

Shingle values came from Python's built-in `hash`, which is seeded
per process. In memory that is fine and every benchmark on this page
is unaffected -- each run computed and compared its shingles inside
one process. On disk it is not: the shingle cache persisted those
values, so on the *second* and every later invocation of
`code-steward similar`, the cache returned integers from a dead
process's hash seed. Nothing matched them. The tool reported no
overlap and gave no indication anything was wrong.

A verbatim copy of an indexed function scored 0.00. That is how it
was found -- as a smoke test of the new relevance floor, not by any
test in the suite, because the tests either disable the cache or
populate and read it inside a single process.

The fix is a keyed digest (`similarity._window_hash`, BLAKE2b
truncated to signed 64 bits) and a versioned cache table so rows
written under the old scheme are dropped rather than read.

**No measured figure changes.** Jaccard over hashed windows equals
Jaccard over the windows themselves unless the hash collides;
compared across 40,000 Airflow pairs, the largest difference between
the two was 0.0. The first build of a large tree costs a few seconds
more, which is the trade for a cache that works at all.

It also explains an earlier failed optimisation: cache decoding was
profiled and tuned for a latency win that never arrived. The decode
path was never the problem, because the decoded values were never
usable.
