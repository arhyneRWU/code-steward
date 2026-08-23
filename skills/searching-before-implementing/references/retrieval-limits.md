# Retrieval limits in practice

Load this when a packet looks wrong and you need to decide whether to rephrase the query or
abandon Code Steward for ordinary exploration.

## The measured numbers

Benchmark repository: `psf/requests`. Production retriever (`retrieve_units`, the path used by
`code-steward packet`).

| Metric | Ranker | Plain text search |
| --- | --- | --- |
| Hit@1 | 46.67% | **53.33%** |
| Hit@3 | 60.00% | **80.00%** |
| Hit@K | 73.33% | **86.67%** |
| MRR | 0.550 | **0.667** |

Restated without the jargon:

- The top candidate is correct **slightly under half the time**.
- The correct unit is somewhere in the packet **about 3 times in 4**.
- **About 1 query in 4 produces a packet with no correct answer in it anywhere.**
- A stopword-stripped keyword scan beats the ranker on **every one of those**.

There is no signal in the packet that tells you which case you are in. Score magnitude does
not separate the good packets from the bad ones.

What the packet does buy is size: 4,039 bytes against 21,107 to inspect the same candidates.
Use it for compression, not for confidence.

## The other tool is much better, and works earlier

`code-steward similar` compares code to code rather than an intent to code. Measured across
three pinned public repositories and 308 blind-labelled pairs: **precision 1.000**.

If you can sketch the function the task calls for, compare it before you reach for a packet:

```bash
code-steward similar --draft sketch.py --json
```

Docstrings, comments, and formatting are ignored, so a rough sketch is enough.

Its failure mode is different from the ranker's and worth knowing exactly. Overlap of one
fixture function against modified copies of itself:

| Change to the copy | Overlap |
| --- | --- |
| docstring rewritten | 1.000 |
| function renamed | 0.941 |
| whole signature renamed | 0.535 |
| every local variable also renamed | 0.015 |

So it finds a function that was copied and tidied, and misses one that was reimplemented from
scratch in different words. A silent `similar` narrows the possibilities; it does not close
them.

## Why it fails the way it does

Ranking is lexical and fuzzy similarity over metadata already in the index: unit name,
qualified name, signature, docstring-derived `purpose`, and derived `concepts`. There are:

- **no embeddings** — no semantic similarity, no synonym understanding beyond a tiny curated
  abbreviation/relation list (`repo`→`repository`, `save`→`persist`/`write`);
- **no call-graph consumption** — callers, callees, and tests do not influence rank;
- **no cross-language indexing** — Python only;
- **no summarization** — a unit without a docstring gets its own identifier as its `purpose`,
  so it contributes almost no matchable text.

The consequence: retrieval is essentially a smart search over the words the code already uses.
If your query does not share vocabulary with the target, the ranker has nothing to work with.

## Query phrasing: the largest lever you control

**Good** — reuses probable identifier tokens:

- `"resolve redirects for a prepared request"`
- `"rank code units for an intent"`
- `"extract git file commit for a path"`

**Bad** — describes behavior in vocabulary the code does not use:

- `"make sure we don't loop forever when the server keeps bouncing us"`
- `"figure out which thing is the best match"`

In one measured case a purely behavioral phrasing ranked the correct unit **119th out of 182**
indexed units. That is worse than random for a top-8 packet.

Practical procedure: try the identifier-flavored phrasing first. If the packet is unconvincing,
try **one** rephrasing with different nouns. If that also fails, stop — a third attempt is
almost never the difference between success and failure, and you have now spent more context
than a grep would have.

## Worked example of a Hit@1 miss

Run against Code Steward's own source, asking for the ranking function:

```bash
code-steward packet "rank code units for an intent" --limit 3
```

Top three candidates, abbreviated:

| Rank | Unit | Score | Purpose |
| --- | --- | --- | --- |
| 1 | `src.code_steward.db::all_units` | 57.4 | `all units` |
| 2 | `src.code_steward.retrieval::rank_units` | 55.3 | `Rank code units with baseline evidence plus query expansion.` |
| 3 | `src.code_steward.search::search_units` | 48.5 | `search units` |

The correct answer is rank 2. Rank 1 is a trivial database accessor that won on token overlap
(`units`) despite having no docstring — its `purpose` is just its identifier, split. This is
Hit@1 failing on the project's own codebase, with a well-phrased query, at a score gap of 2.1
points. It is the normal case, not a pathological one.

It also shows the correct reading habit: `all_units` is eliminated by its **signature**
(`(conn: sqlite3.Connection) -> list[CodeUnit]` takes no query), without reading its body.
Signatures rule candidates out cheaply; bodies confirm the one that survives.

## Operational failure modes

- **`index not found: .code-steward/index.sqlite3`** — nothing is indexed. Run
  `code-steward build`, or skip Code Steward for this task.
- **`build failed: ... unit ID '<id>' ... conflicts with existing unit in ...`** — two files
  carry the same `# code-steward: unit <id>` tag. Common when fixture or benchmark trees are
  indexed alongside real source. Re-run with `--exclude tests --exclude benchmarks`.
- **Stale index** — the index does not follow edits automatically. `lines`, `hash`, and bodies
  can be out of date. Run `code-steward update <path>` after editing a file; prefer the
  `path:lines` from a fresh `code-steward read` over remembered line numbers.
- **Near-duplicate suppression** — `packet` compresses metadata-similar candidates out of the
  top window, so a genuine second implementation of the same behavior may be hidden. If the
  task is specifically about finding duplication, use `code-steward search`, which does not
  apply that filter.

## When to give up and explore normally

Give up on the packet and switch to Grep/Glob/Read when:

- two phrasings have produced nothing plausible;
- you have read three candidate bodies without a match;
- the top candidates all have identifier-only `purpose` fields (the codebase is undocumented
  in this area, so retrieval has no signal);
- the target is cross-language, cross-service, or defined by data/config rather than code.

Falling back is a normal outcome, not a failure to report. Say which queries you tried so the
next agent does not repeat them.
