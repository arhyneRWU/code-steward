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
none. Three public corpora pinned to full commit SHAs, 298 pairs
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

Precision, recall, and F1 at depth 30 per corpus. Bytes are the
normalised source of everything the arm returned — what a reviewer
would have to read.

### Macro, mean over the three corpora

| Arm | Precision | Recall (in pool) | F1 | Bytes | Unlabelled returned |
| --- | --- | --- | --- | --- | --- |
| **token-shingle** | **0.978** | **0.404** | **0.571** | **55,642** | 0 |
| jscpd | 0.899 | 0.367 | 0.521 | 127,401 | 0 |
| metadata-similarity | 0.744 | 0.304 | 0.431 | 102,457 | 0 |
| body-rapidfuzz | 1.000\* | 0.180 | 0.276 | 193,159 | **52** |

\* over labelled pairs only — see the bracket below.

### Per corpus

| Corpus | Arm | P | R | F1 | Bytes | Unlabelled |
| --- | --- | --- | --- | --- | --- | --- |
| home-assistant | token-shingle | 1.000 | 0.375 | 0.545 | 18,964 | 0 |
| home-assistant | metadata-similarity | 0.933 | 0.350 | 0.509 | 28,207 | 0 |
| home-assistant | jscpd | 0.897 | 0.325 | 0.477 | 29,450 | 0 |
| home-assistant | body-rapidfuzz | 1.000 | 0.138 | 0.242 | 63,750 | 19 |
| airflow | token-shingle | 1.000 | 0.448 | 0.619 | 15,802 | 0 |
| airflow | body-rapidfuzz | 1.000 | 0.388 | 0.559 | 16,218 | 4 |
| airflow | jscpd | 0.867 | 0.388 | 0.536 | 58,699 | 0 |
| airflow | metadata-similarity | 0.633 | 0.284 | 0.392 | 41,846 | 0 |
| django | jscpd | 0.933 | 0.389 | 0.549 | 39,252 | 0 |
| django | token-shingle | 0.933 | 0.389 | 0.549 | 20,876 | 0 |
| django | metadata-similarity | 0.667 | 0.278 | 0.392 | 32,404 | 0 |
| django | body-rapidfuzz | 1.000 | 0.014 | 0.027 | 113,191 | 29 |

Every figure comes from
[`benchmarks/similarity/scores.json`](../benchmarks/similarity/scores.json),
reproducible with `make bench-similarity`.

## What this says

**Token shingles came first on every axis.** They lead on F1 in two
corpora and tie for first in the third, in 1.8× to 3.5× fewer bytes.
No more sophisticated arm bought anything measurable here.

**`metadata_similarity` came third.** Macro F1 0.431 against 0.571,
at 1.8× the bytes. On Airflow its precision is 0.633. Reading names,
purposes, and signatures while never reading a body is a handicap for
this particular question.

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
`code-steward packet --reuse`, which attaches near-duplicate evidence
to each candidate. The draft path is the point: the reuse question is
worth most before the code exists.

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
report a person reads. The edge over jscpd is modest on F1 (0.571 to
0.521) and larger on bytes (2.3× fewer), and bytes are what decide
whether the evidence fits in an agent's context.

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

**Pool depth is 30 per generator per corpus.** Deeper pooling would
change recall and might change the ranking. The depth was chosen
before scoring so one labeller could read every pair properly, and it
was not revisited afterwards.
