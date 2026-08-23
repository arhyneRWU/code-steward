---
name: searching-before-implementing
description: This skill should be used before writing new Python functions, classes, helpers, or FastAPI endpoints in a repository that has a Code Steward index, to check whether equivalent behavior already exists. It covers running `code-steward packet`, reading the minimum number of candidate units, and classifying the work as REUSE, EXTEND, REFACTOR, CREATE, or UNCERTAIN. It also states when Code Steward is the wrong tool and normal exploration should be used instead.
---

# Searching before implementing

Code Steward turns "does this already exist?" into a cheap deterministic lookup instead of
an open-ended repository crawl. It emits a small JSON packet of candidate code units so you
can make a reuse decision without pulling whole files into context.

**Read this first: the retriever is weak, and this skill only works if you treat it that way.**

## Maturity and measured accuracy — read before trusting a packet

Measured on a real repository (`psf/requests`), the production retriever scores:

| Metric | Value | What it means for you |
| --- | --- | --- |
| Hit@1 | **40%** | The top-ranked candidate is the wrong unit **most of the time**. |
| Hit@K | **73.33%** | Roughly **one query in four returns a packet that does not contain the correct unit at all**. |
| MRR | **0.500** | On average the right answer, when present, sits around rank 2. |

Four hard limitations, all of them real:

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
  ("retry with jitter when the upstream is flaky"). This is the retriever's documented worst
  case. Grep for the mechanism instead.
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

### 2. Ask for a packet before exploring broadly

```bash
code-steward packet "<intent>" --limit 8 --input <Type> --returns <Type>
```

Phrase the intent using **the vocabulary the code would use** — likely function names, class
names, parameter names, domain nouns — not a description of user-visible behavior. This is the
single largest lever on retrieval quality. If the first phrasing returns nothing plausible,
try one rephrasing with different identifier tokens, then stop and fall back.

`--input` / `--returns` add a typed signal and are worth passing whenever you know the shape.

### 3. Read the minimum number of units

The packet gives you `unit`, `score`, `path`, `lines`, `signature`, `purpose`, `concepts`,
`hash`, and `git` per candidate. Usually the signature and purpose are enough to eliminate
most candidates on sight.

Pull a body only for candidates you cannot rule out from metadata:

```bash
code-steward read "<unit-id>" --header
```

**Read at least one body before any REUSE or EXTEND decision.** Metadata alone is not enough
to justify depending on code, given a 40% Hit@1. Two or three bodies is a normal ceiling; if
you find yourself reading six, the packet has failed — fall back.

Scores are not calibrated probabilities. A 57 does not mean 57% confident, and the gap
between rank 1 and rank 2 carries little information.

### 4. Classify

| Decision | Use when |
| --- | --- |
| **REUSE** | An existing unit already does this. You verified by reading it. Call it. |
| **EXTEND** | An existing unit is the right home; add a parameter or branch there. |
| **REFACTOR** | Two or more units already do overlapping work and the change should consolidate them. Requires reading all of them. Do not abstract merely because code looks similar. |
| **CREATE** | Nothing existing fits **and** you confirmed that beyond the packet. |
| **UNCERTAIN** | The packet did not settle it. Say what you checked and what you would need. |

**CREATE deserves specific suspicion.** "Not in the packet" and "not in the repository" look
identical from here, and about a quarter of the time they are different things. Before
committing to CREATE, spend one grep on the most likely identifier or two. If you skip that
step, report the decision as UNCERTAIN, not CREATE.

### 5. Report the decision, not the search

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

- `code-steward search "<intent>"` — exploratory ranking, wider and noisier than `packet`.
- `code-steward endpoints` — FastAPI routes found by AST.
- `code-steward map` — compact Markdown code map, written to `.code-steward/CODEMAP.md`.

## Further reading

`references/retrieval-limits.md` — the measured failure modes in detail, worked examples of
query phrasing that succeeds and fails, and a live example of the retriever ranking the wrong
unit first. Load it when a packet looks wrong and you want to know whether to rephrase or bail.
