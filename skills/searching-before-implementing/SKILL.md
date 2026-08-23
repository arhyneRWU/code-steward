---
name: searching-before-implementing
description: This skill should be used before writing new Python functions, classes, helpers, or FastAPI endpoints in a repository that has a Code Steward index, to check whether equivalent behavior already exists. It covers running `code-steward similar --draft` on code you are about to write, `code-steward packet` when you cannot draft it yet, reading the minimum number of candidate units, and classifying the work as REUSE, EXTEND, REFACTOR, CREATE, or UNCERTAIN. It also states when Code Steward is the wrong tool and normal exploration should be used instead.
---

# Searching before implementing

Code Steward turns "does this already exist?" into a cheap deterministic lookup instead of
an open-ended repository crawl. It emits a small JSON packet of candidate code units so you
can make a reuse decision without pulling whole files into context.

**Read this first: there is one primary path and one fallback, and they are not close in
accuracy. Draft the code and compare it. Only describe the task in words when you cannot.**

On 250 held-out functions, comparing a drafted body found the existing duplicate **99.4%**
of the time. Describing the task in a sentence found it **45.9%** of the time. That is the
whole reason for the ordering below.

## Two tools, measured separately

### `similar` — comparing code to code. Reliable. Use this first.

Measured across three pinned public repositories and 308 blind-labelled pairs: **precision
1.000**. When it reports an overlap, there is almost always a real one.

Use it whenever you can write down the code you are about to add, even roughly. It is the
stronger of the two signals by a wide margin, and it is the only one that works before the
code exists.

It applies a **relevance floor of 0.27** and returns nothing below it. That floor was chosen
on a held-out cross-corpus sample as the smallest value holding the false-positive rate at or
under 1%; it keeps 167 of the 170 labelled duplicates. You do not need to judge whether a
score is meaningful — if a match comes back, it cleared the bar. Pass `--floor 0.0` to see
what was suppressed, which is a debugging move rather than a normal one.

Its blind spot is specific and worth memorising: it compares text, so it finds a function
that was **copied and tidied** but not one **reimplemented in different words**. Overlap
against a copy of one fixture function measured 0.941 with the function renamed, 0.535 with
the whole signature renamed, and 0.015 once every local variable was renamed too. A silent
`similar` is real evidence, but it is not proof: the floor rules out coincidence, not a
reimplementation written in other words.

### `packet` / `search` — matching an intent to code. Weak. The fallback.

Use this only when there is nothing to draft: exploring an unfamiliar repository, or
answering "where does this already happen?". When you take this path, say that you took it,
because the answer deserves less confidence.

Measured on `psf/requests`:

| Metric | Value | What it means for you |
| --- | --- | --- |
| Hit@1 | **33.33%** | The top-ranked candidate is usually the wrong unit. |
| Hit@K | **93.33%** | The correct unit is usually somewhere in the packet — but rarely first. |
| MRR | **0.534** | On average the right answer, when present, sits around rank 2. |

A plain keyword scan still beats this on Hit@1 (53.33%) and MRR. What the packet buys is
recall and compression — the same candidates in about a fifth of the bytes — not precision.
Read down the list rather than trusting the top row.

**The packet has no floor.** Its score is on a different scale from `similar` and no null
distribution has been measured for it, so it returns its best eight candidates regardless of
how weak they are. Judging whether they are good enough is still your job on this path.

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
- **An empty or unconvincing packet is not evidence that the code does not exist.** This
  applies to the packet, which has no floor and no way to assert absence. It applies far less
  to `similar`, which does. If the packet does not answer the question, fall back to ordinary
  Grep/Glob/Read exploration and say so.

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

### 2. Draft the code and compare it

This is the primary path. Do it whenever you can write down roughly what you are about to
add, which is nearly always — you were going to write the code anyway.

```bash
code-steward similar --draft new_function.py     # or '-' to read stdin
```

A rough draft is enough. The comparison ignores docstrings, comments, and formatting, so
sketch the body and spend no effort on prose. Every match that comes back has already
cleared the 0.27 floor, so do not second-guess the score — open it.

If it returns nothing, **that is an answer, not a failed search.** Report it as one. The
output tells you which case you are in:

```text
no existing unit overlaps this one          # nothing even reached the comparison
nothing above the 0.27 floor (6 suppressed) # six candidates checked, none close enough
```

Those are different facts and the second is stronger. Neither is proof of absence — a
reimplementation in different words is invisible to this — but both are real evidence, and
writing the function is the correct next step.

Already have a unit in hand and want to know what else looks like it?

```bash
code-steward similar "<unit-id>"
```

### 3. Only if you cannot draft, ask for a packet

The fallback. Reach for it when there is nothing to sketch — an unfamiliar repository, or a
question about where existing behaviour lives. Its hit rate is roughly half the draft path's,
so say out loud that you took it:

```bash
code-steward packet "<intent>" --limit 8 --input <Type> --returns <Type> --reuse
```

`--reuse` attaches near-duplicate evidence to each candidate, which is what tells REUSE apart
from REFACTOR: a candidate that already exists three times over should not be reused a fourth
time. **Use it for that, and not because more evidence helps generally — it does not.** Put
to a blinded reviewer over sixty held-out cases, it changed no verdicts at a detectable rate
(0.683 against 0.733, paired, p = 0.549) while costing 58% more bytes.

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
to justify depending on code, given a 33.33% Hit@1. Two or three bodies is a normal ceiling; if
you find yourself reading six, the packet has failed — fall back.

Scores are not calibrated probabilities. A 57 does not mean 57% confident, and the gap
between rank 1 and rank 2 carries little information.

### 5. Classify

| Decision | Use when |
| --- | --- |
| **REUSE** | An existing unit already does this. You verified by reading it. Call it. |
| **EXTEND** | An existing unit is the right home; add a parameter or branch there. |
| **REFACTOR** | Two or more units already do overlapping work and the change should consolidate them. Requires reading all of them. A candidate carrying a `duplicates` list is the usual signal. Do not abstract merely because code looks similar. |
| **CREATE** | Nothing existing fits. On the draft path a floored empty result is sufficient support for this; on the packet path, confirm beyond the packet first. |
| **UNCERTAIN** | The packet did not settle it. Say what you checked and what you would need. |

**CREATE deserves suspicion on the packet path, and much less on the draft path.** The packet
has no floor, so "not in the packet" and "not in the repository" look identical from there;
spend one grep on the most likely identifier or two before committing, or report UNCERTAIN
instead. A floored empty result from `similar --draft` is a different kind of answer — the
tool checked, scored what it found, and asserts that nothing cleared the bar.

**Do not treat "write it new" as a failure to find something.** On a third of measured cases
where writing the function was correct, a reviewer shown a packet of eight candidates picked
one of them instead. Being handed plausible candidates is not evidence that one of them fits.

### 6. Report the decision, not the search

Carry forward the decision, the units it rests on (`unit-id` + `path:lines`), and one line of
reasoning. Do not carry forward the packet JSON or the exploration transcript — keeping that
out of the parent context is the entire point of the tool.

## Delegating to the reviewer subagent

For a larger decision, or when you want the candidate evaluation kept out of this context
entirely, delegate to the **`reuse-reviewer`** agent shipped with this plugin. Hand it the task
description and let it run `packet` and `read` itself; it returns only a structured decision
plus the units it relied on.

It is advisory and cannot edit files. Treat a `NO_CANDIDATE` it reached from a packet as a
prompt to check; one it reached from a floored `similar --draft` result is stronger, because
the tool made an assertion rather than failing to find something.

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
