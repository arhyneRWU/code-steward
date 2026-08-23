# Reuse-similarity gold set

This benchmark answers one question: given a function, can a tool
find the functions already in the repository that a reviewer would
call reusable — and does it stay quiet when there are none?

That is a different question from the one the retrieval benchmark
asks. Retrieval ranks units against a natural-language task. This
ranks units against *another unit*. Code Steward has never measured
the second one, and the capability it ships for it —
`retrieval.metadata_similarity` — exists only to deduplicate a result
set. It has never been evaluated against anything.

## The protocol

Written before any pair was labelled, and unchanged since.

### 1. Corpora

Three public repositories, pinned to full commit SHAs, scoped by rule
rather than by hand. See `corpus.py` for the pins and the sampling
rule; `tests/test_similarity_corpus.py` fails if either drifts.

| Corpus | Role | Why it is here |
| --- | --- | --- |
| `home-assistant/core` | template duplication | Integrations written to a shared scaffold. The highest expected positive rate. |
| `apache/airflow` | organic duplication | Provider hooks and operators copied between vendors over years. Duplication that accumulated for reasons. |
| `django/django` | **hard negative** | Old, small, reviewed to death. The right answer is usually "nothing". |

Django is not filler. Without a corpus where the correct output is an
empty result, an arm that returns whichever pair looks most alike
scores well everywhere, and the benchmark cannot tell it apart from
one that understands reuse.

Test trees are excluded from every corpus. Test modules repeat
themselves by design, and including them would raise the positive rate
without saying anything about production reuse.

### 2. Units

Functions and methods only, at least 5 lines and at least 20
normalised tokens. Bodies are normalised through `ast.unparse`, which
drops comments and formatting and re-emits canonical source.
Identifiers are kept: renaming locals would silently convert the
lexical control arm into a structural one.

### 3. Candidate pairs

Pooled from **three independent generators**, chosen because they fail
differently:

- **token-shingle Jaccard** over normalised bodies — lexical only
- **`metadata_similarity()`** — names, purposes, signatures; never
  reads a body
- **jscpd** — copy-paste spans; blind to two functions doing the same
  thing in different words

Top *N* from each, unioned per corpus. A fourth **probe** stratum is a
deterministic random sample of pairs with no generator involved.

### 4. Blinding

The labelling sheet carries a pair of normalised bodies, their paths,
and an opaque pair ID. It does not carry the corpus, the stratum, the
generators, the scores, or the ranks. The provenance key is written to
a separate file that the labeller does not open until every label is
committed.

This is the same protocol used for the packet-precision labels, and
for the same reason: a labeller who can see that a pair was ranked
first by the system under evaluation is no longer an independent
judge.

### 5. Labels

- `same-behaviour` — one could replace or call the other with only
  mechanical changes. REUSE.
- `overlapping` — a real shared core with genuine differences around
  it. EXTEND or REFACTOR.
- `unrelated` — shared idiom, shared framework, shared shape, no
  shared job. Reporting this pair wastes the reader's time.

## Known limitations, stated up front

**Recall is recall within the pool.** A pair that no generator
proposed is invisible to this benchmark, so every arm's recall is an
upper bound. The probe stratum bounds how bad that is; it does not
fix it.

**One labeller.** There is no second annotator and therefore no
inter-annotator agreement figure. The packet-precision labels were
validated by independent reproduction of a gold key at 15/15, which is
evidence about the protocol, not about this set.

**Probe pairs are excluded from precision.** Scoring a generator on
pairs it was never asked about measures nothing. They are reported
separately, as a base rate.

## Reproducing

```
make bench-similarity-pairs CHECKOUTS=<dir>   # generate + pool + sheet
make bench-similarity                          # score every arm
```

`CHECKOUTS` holds one directory per corpus, each a checkout at the
pinned SHA. `scripts/fetch_similarity_corpora.sh` creates them.

Committed data holds unit IDs, paths, line ranges, and labels. It
never holds source snippets — the sheet is generated locally and is
not committed.
