---
name: searching-before-implementing
description: This skill should be used before writing new Python functions, classes, helpers, or FastAPI endpoints in a repository that has a Code Steward index, to check whether equivalent behavior already exists. It covers running `code-steward similar --draft` on code you are about to write, `code-steward packet` when you cannot draft it yet, reading the minimum number of candidate units, and classifying the work as REUSE, EXTEND, REFACTOR, CREATE, or UNCERTAIN. It also states when Code Steward is the wrong tool and normal exploration should be used instead.
---

# Searching before implementing

Code Steward turns "does this already exist?" into a cheap deterministic lookup instead of
an open-ended repository crawl. It emits a small JSON packet of candidate code units so you
can make a reuse decision without pulling whole files into context.

**Read this first: the two tools here have very different accuracy, and you should trust
them differently.**

## Two tools, measured separately

### `similar` — comparing code to code. Reliable.

Measured across three pinned public repositories and 298 blind-labelled pairs: **precision
0.978**. When it reports an overlap, there is almost always a real one.

Use it whenever you can write down the code you are about to add, even roughly. It is the
stronger of the two signals by a wide margin, and it is the only one that works before the
code exists.

Its blind spot is specific and worth memorising: it compares text, so it finds a function
that was **copied and tidied** but not one **reimplemented in different words**. Overlap
against a copy of one fixture function measured 0.941 with the function renamed, 0.535 with
the whole signature renamed, and 0.015 once every local variable was renamed too. A silent
`similar` is weak evidence of absence for the same reason a silent packet is.

### `packet` / `search` — matching an intent to code. Weak.

Measured on `psf/requests`:

| Metric | Value | What it means for you |
| --- | --- | --- |
| Hit@1 | **46.67%** | The top-ranked candidate is the wrong unit more often than not. |
| Hit@K | **73.33%** | Roughly **one query in four returns a packet that does not contain the correct unit at all**. |
| MRR | **0.550** | On average the right answer, when present, sits around rank 2. |

A plain keyword scan beats this on every one of those metrics. What the packet buys is
compression — the same candidates in about a fifth of the bytes — not better recall.

Four hard limitations of the ranking, all of them real:

1. **No embeddings, no call graph.** Ranking is lexical and fuzzy matching over names,
   signatures, docstrings, and derived concepts. Nothing understands meaning.
2. **Identifier tokens win; behavioral phrasing loses.** A query that reuses the target's
   own naming succeeds. A query phrased purely as behavior can fail catastrophically — in one
   measured case the correct unit ranked **119th out of 182**.
3. **Python only.** Other languages are not indexed and never appear in a packet.
4. **Undocumented code retrieves badly.** A unit with no docstring falls back to its own
   identifier as its `purpose`, so there is almost nothing for the ranker to match against.

Two rules follow directly from those numbers, and they are not optional:

- **A packet is evidence, not truth. Verify before you act on it.** Never call something
  reusable because it ranked first. Open the unit, or the decision is unsupported.
- **An empty or unconvincing packet is not evidence that the code does not exist.** With
  Hit@K at 73%, "Code Steward found nothing" is only weak evidence of absence. If the packet
  does not answer the question, fall back to ordinary Grep/Glob/Read exploration and say so.

## When NOT to use Code Steward

Skip it — go straight to normal exploration — when any of these hold:

- The repository is **not Python**, or the relevant code is not Python.
- **No index exists** and building one is not worth it (`code-steward packet` will tell you:
  `index not found: .code-steward/index.sqlite3`). For a one-line change, just grep.
- You **already know where the code lives**. Read the file. A packet is strictly worse than
  a known path.
- The task is **not "does this exist?"** — debugging, editing a file you have open, renaming,
  formatting, dependency work, config, docs, tests for code you just wrote.
- The target is **defined by behavior with no shared vocabulary** with the codebase
  ("retry with jitter when the upstream is flaky"). This is the *ranker's* documented worst
  case — but if you can sketch the code, `similar --draft` does not depend on vocabulary at
  all and is worth trying before you grep.
- The codebase is **largely undocumented**. Retrieval quality degrades sharply.
- You are **inside a subagent that was already handed the relevant units**. Do not re-retrieve.

## Workflow

### 1. Make sure an index exists

```bash
code-steward build --quiet          # first time, or after large changes
code-steward update path/to/file.py # after editing one file
```

`build` fails loudly on duplicate `# code-steward: unit <id>` tags across files. Use
`--exclude <dir>` (repeatable) to keep fixture or vendored trees out of the index.

### 2. If you can draft the code, compare it first

This is the strongest signal available and it works before the function exists.

```bash
code-steward similar --draft new_function.py     # or '-' to read stdin
```

A rough draft is enough — the comparison ignores docstrings, comments, and formatting, so
sketch the body and do not spend effort on prose. A match above roughly 0.4 is worth opening;
below 0.2 is usually coincidence.

If it returns nothing, that is the common and correct answer: on the benchmark's random
sample of 45 pairs, "nothing" was right 45 times out of 45. It is not proof of absence —
see the blind spot above — but it is a real signal, unlike an empty packet.

Already have a unit in hand and want to know what else looks like it?

```bash
code-steward similar "<unit-id>"
```

### 3. Otherwise, ask for a packet

When the task is described by intent and you cannot yet draft the code:

```bash
code-steward packet "<intent>" --limit 8 --input <Type> --returns <Type> --reuse
```

`--reuse` attaches near-duplicate evidence to each candidate. It is what tells REUSE apart
from REFACTOR: a candidate that already exists three times over should not be reused a fourth
time. It costs an extra pass over the index, so leave it off for a quick look.

Phrase the intent using **the vocabulary the code would use** — likely function names, class
names, parameter names, domain nouns — not a description of user-visible behavior. This is the
single largest lever on retrieval quality. If the first phrasing returns nothing plausible,
try one rephrasing with different identifier tokens, then stop and fall back.

`--input` / `--returns` add a typed signal and are worth passing whenever you know the shape.

### 4. Read the minimum number of units

The packet gives you `unit`, `score`, `path`, `lines`, `signature`, `purpose`, `concepts`,
`hash`, and `git` per candidate. Usually the signature and purpose are enough to eliminate
most candidates on sight.

With `--reuse`, a candidate may also carry `duplicates`: other indexed units its body already
overlaps. A candidate with duplicates is a REFACTOR signal, not a REUSE one.

Pull a body only for candidates you cannot rule out from metadata:

```bash
code-steward read "<unit-id>" --header
```

**Read at least one body before any REUSE or EXTEND decision.** Metadata alone is not enough
to justify depending on code, given a 46.67% Hit@1. Two or three bodies is a normal ceiling; if
you find yourself reading six, the packet has failed — fall back.

Scores are not calibrated probabilities. A 57 does not mean 57% confident, and the gap
between rank 1 and rank 2 carries little information.

### 5. Classify

| Decision | Use when |
| --- | --- |
| **REUSE** | An existing unit already does this. You verified by reading it. Call it. |
| **EXTEND** | An existing unit is the right home; add a parameter or branch there. |
| **REFACTOR** | Two or more units already do overlapping work and the change should consolidate them. Requires reading all of them. A candidate carrying a `duplicates` list is the usual signal. Do not abstract merely because code looks similar. |
| **CREATE** | Nothing existing fits **and** you confirmed that beyond the packet. |
| **UNCERTAIN** | The packet did not settle it. Say what you checked and what you would need. |

**CREATE deserves specific suspicion.** "Not in the packet" and "not in the repository" look
identical from here, and about a quarter of the time they are different things. Before
committing to CREATE, spend one grep on the most likely identifier or two. If you skip that
step, report the decision as UNCERTAIN, not CREATE.

### 6. Report the decision, not the search

Carry forward the decision, the units it rests on (`unit-id` + `path:lines`), and one line of
reasoning. Do not carry forward the packet JSON or the exploration transcript — keeping that
out of the parent context is the entire point of the tool.

## Delegating to the reviewer subagent

For a larger decision, or when you want the candidate evaluation kept out of this context
entirely, delegate to the **`reuse-reviewer`** agent shipped with this plugin. Hand it the task
description and let it run `packet` and `read` itself; it returns only a structured decision
plus the units it relied on.

It is advisory. It cannot edit files, and its verdict is subject to the same retrieval limits
described above — including its inability to distinguish "absent" from "not retrieved". Treat
`NO_CANDIDATE` from the reviewer as a prompt to check, not as a licence to write new code.

## Other commands

- `code-steward similar --draft -` — compare a function you have not written yet; the most
  reliable signal here.
- `code-steward search "<intent>"` — exploratory ranking, wider and noisier than `packet`.
- `code-steward endpoints` — FastAPI routes found by AST.
- `code-steward map` — compact Markdown code map, written to `.code-steward/CODEMAP.md`.

## Further reading

`references/retrieval-limits.md` — the measured failure modes in detail, worked examples of
query phrasing that succeeds and fails, and a live example of the retriever ranking the wrong
unit first. Load it when a packet looks wrong and you want to know whether to rephrase or bail.
