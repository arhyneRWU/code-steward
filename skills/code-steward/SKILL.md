---
name: code-steward
description: This skill should be used when working in a Python repository that has a Code Steward index (`.code-steward/index.sqlite3`) — to understand a function together with everything that calls it and everything it calls before changing it, to see every FastAPI route with the path underneath it, to find duplication across a whole call path rather than only in the diff, to write docstrings for undocumented functions using the callers as context, and to check what a change duplicated before committing it. Covers `trace`, `check`, `similar`, and `search`, what each is measured to be worth, and when to use ordinary Grep/Read instead.
---

# Code Steward

Code Steward assembles a **small, complete-enough slice of a repository** so it
can be acted on without reading the repository. It is deterministic: AST
parsing, a call graph, and token-overlap comparison. Nothing here ranks by
relevance or guesses at meaning.

The measured reason it works this way: a cheap model handed an assembled
bundle scored **0.917** against blind labels with 30/30 on negatives, while a
larger model handed a *ranked shortlist* was talked into a duplicate that was
not there on **a third of clean cases**. Assemble a complete slice; never pick
from a shortlist.

## How much to trust each answer

Read this table before anything else. The difference between the rows is not
small, and acting on a weak row as though it were a strong one is the main way
to misuse this tool.

| Moment | Command | Trust |
| --- | --- | --- |
| Understand a function before changing it | `trace <target>` | **Strong.** Deterministic graph walk. Incomplete, never wrong. |
| See what a route actually does | `trace --endpoints` | **Strong.** Same walk, rooted at the routes. |
| Check what you just wrote | `check` | **Strong** on copy-and-tidy. Blind to reimplementation. |
| Compare code to code | `similar "<unit>"` | **Strong.** Precision 1.000 on 308 blind-labelled pairs. |
| Duplication across a whole path | `trace --dry` | **A report.** Fires on ~53% of paths; the rate compounds with slice size. |
| Docstrings for undocumented code | `trace --undocumented` | Selector is exact. **The docstring itself is unverifiable — propose, do not apply.** |
| Understand a function, with a broader graph installed | `trace ... --members-from` | **Strong, and better.** +0.207 caller recall over our own selection on 200 Django functions. |
| Guess where something lives | `search "<intent>"` | **Weak.** Hit@1 33%; plain grep scores 53%. Use grep first. |
| Predict a duplicate before writing | `similar --draft` | **Weak.** 0.460. One cheap attempt, then move on. |

Two consequences worth stating plainly:

- **Grep is better than `search` at finding things.** Use Grep, get a
  `path:line`, and hand that to `trace`. `search` is for when you cannot even
  guess the vocabulary.
- **The tool is reliable on code that exists.** Everything predictive is weak.
  Checking after you write is where it earns its keep.

## The pipeline

Everything below is one shape: **select a target, assemble the slice, run
passes over it, read one bundle.**

### Make sure the index exists

```bash
code-steward build --quiet             # first time, or after large changes
code-steward update path/to/file.py    # after editing one file
```

**A stale index is quietly wrong, not quietly incomplete.** Found in the
field, not in review: it handed back one function labelled with a
*neighbouring* function's line range, and reported one caller where two
existed — on a function the agent had just edited. Both are the judgement
this tool exists to support, inverted, and neither is visible unless you
already know the answer.

`trace` now warns on stderr when a file in the slice is newer than the
index, and `check` re-indexes the files it is about to compare. `update`
takes many paths and costs one relationship refresh however many you pass.

### Understand a function: `trace`

Name the target however you have it. All three forms work:

```bash
code-steward trace app.py:42           # what Grep gave you — any line inside the unit
code-steward trace normalise           # what a traceback or review comment gave you
code-steward trace "pkg.mod::fn"       # a unit ID
```

You get the function, its callers **with the exact line where each calls**,
its callees, and its tests — as one bundle, at 4–10x compression against
reading the files involved.

An ambiguous name lists candidates and exits 2. It does not pick one, because
picking from plausible candidates is the failure mode above.

Depth is `--callers 1 --callees 1` by default. Raise it when the path matters
more than the size; a hub function at depth 2 gets large fast.

### Understand a route: `trace --endpoints`

```bash
code-steward trace --endpoints
```

One bundle per FastAPI route: the handler, everything it calls, labelled with
its method and path. Defaults change here to `--callers 0 --callees 2`,
because nothing in the repository calls a route handler and a handler that
delegates twice needs two hops before the bundle holds any implementation.

This is usually the right entry point for "what does this service do".

### Find duplication on the path: `--dry`

```bash
code-steward trace app.py:42 --dry
code-steward trace --endpoints --dry
```

Compares **every unit in the slice** against the index, not just the one you
named. This finds duplication that belongs to the path rather than to your
diff — a near-copy sitting two hops away that nobody touched this week.

**Read it, do not gate on it.** It fires on roughly 53% of paths in a
low-duplication repository, and that is arithmetic rather than a verdict on
the code: a five-member slice gets five chances to fire. Raising `--callers`
or `--callees` raises the rate by construction.

A true overlap is also not automatically a defect. The first one this found in
its own repository was a pair of functions that deliberately differ only by a
floor.

### Write missing docstrings: `--undocumented`

```bash
code-steward trace --undocumented --base HEAD
```

One bundle per function with no docstring, so the docstring can be written
against the callers that show how the function is actually used — which is
what makes it describe the contract rather than restate the body.

Use `--base`, or you get every undocumented function in the repository.
Dunders, property accessors and one-line bodies are skipped: undocumented and
trivial is a legitimate state.

**Propose the docstring; do not silently apply it.** This is the one output
here that cannot be scored — if there were ground truth for the right
docstring, the function would not need one.

### Before you commit: `check`

```bash
code-steward check                     # everything this branch changes
code-steward check path/to/file.py
```

Reports only overlaps **your change introduced**. A function that already
duplicated something before you touched it is not your finding — on Django
that removes 16x the noise.

An empty result is an answer, and it names its denominator so you can tell it
from a no-op:

```text
12 changed function(s) checked, none introduce new overlap
```

Two caveats before trusting a silent run. It catches **copy-and-tidy and
misses reimplementation**: a copied helper with a new name scores ~0.98, the
same algorithm rewritten with every identifier changed scores ~0.015 and is
invisible. And it compares against the last `build`.

**Run `check --rate` on a repository once before trusting it.** Baseline
duplication measured at the shipped floor: Airflow 63.8%, Home Assistant
50.8%, Django 31.3%, this repository 14.3%. On a template-heavy codebase
`check` fires constantly and `--fail-on-overlap` is not worth switching on.

### Comparing code to code: `similar`

```bash
code-steward similar "<unit-id>"       # what else looks like this
code-steward similar --draft new.py    # weak: before the code exists
```

A **0.27 floor** applies, chosen on a held-out cross-corpus sample as the
smallest value holding false positives at or under 1%. If a match comes back,
it cleared the bar — do not second-guess the score, open it.

Its blind spot is worth memorising: it compares text. A function copied and
tidied scores 0.941; the same function with every local variable renamed
scores 0.015.

## When a broader graph is installed: select there, assemble here

**Measured, on 200 Django functions.** Our own call resolution is
conservative: it records `obj.method()` as unresolved and never turns it into
an edge, so slices miss real callers. A broader graph -- Graph Code Review, or
anything else -- finds them. Rendering *its* selection through *our* bundle
scored **+0.207 caller recall** over our own selection, at a **median of 24
bytes fewer** than our own bundle, and matched that graph's own coverage
exactly while costing **48% of the bytes** its own output needs.
[`docs/context-cost.md`](../../docs/context-cost.md) has the run and the
caveats.

So when such a graph is present and current, use it. The order is: **select
there, assemble here.**

### The pattern

```bash
# 1. Gate on currency FIRST, on BOTH axes. A stale graph is an absent one.
built=$(code-review-graph status --repo . | sed -n 's/^Built at commit: //p')
case "$(git rev-parse HEAD)" in "$built"*) ;; *) echo "stale graph"; exit 0;; esac
# A commit match is not enough. A git-shaped graph cannot see uncommitted
# work, and uncommitted work is what you are usually changing.
[ -z "$(git status --porcelain -- '*.py')" ] || { echo "uncommitted Python: use plain trace"; exit 0; }

# 2. Select: ask the broader graph who the neighbours are.
code-review-graph query --repo . callers_of "$PWD/django/http/response.py::HttpResponseBase.has_header" \
  | jq -r '.results[] | "caller:" + (.file_path | ltrimstr(env.PWD + "/")) + "::" + (.qualified_name | split("::")[-1])' \
  > members.txt

# 3. Assemble: one bundle, full bodies, call sites recomputed from our AST.
code-steward trace "django.http.response::HttpResponseBase.has_header" --members-from members.txt
```

That example is the real one: plain `trace` on `has_header` finds **no
callers**, and the two-step finds **nine**, each with the line inside it where
the call happens.

`--members-from` reads one ref per line -- a unit ID, `path:line`, or
`path::name` -- each optionally prefixed `caller:`, `callee:` or `test:`. It
does not know or care which tool produced the list. A ref that resolves to
nothing indexed is **printed to stderr, never dropped**.

### The rules that come with it

- **Gate before you trust, on both axes.** A commit match is necessary and
  not sufficient. A graph built from git reports itself current the moment
  its commit matches `HEAD`, and is still blind to every uncommitted file
  -- which, during development, is exactly the file you are changing.
  **Found in the field, not in review:** a graph reporting
  `head_matches_build: true` held no node at all for a new untracked
  module, and answered a blast-radius question that named the *old* copy
  of the function without saying the new one was missing.
- **Code Steward indexes the working tree**, so it sees that file. This is
  the one axis where the narrower tool wins outright, and it is invisible
  to any benchmark run at a pinned commit -- including this project's own,
  where every file is committed by construction.
- If the graph cannot prove currency, treat it as absent and run plain
  `trace`. Do not use it "with a caveat" -- a caveat is a cost the reader
  pays to reach the same decision.
- **Absence is the supported configuration.** No such graph installed means
  plain `trace`, no warning, no degradation. Every number this project
  publishes is reproducible without it.
- **Selection only.** Use the external graph to decide *which units belong in
  the slice*. Do not use it to rank candidates or score reuse: that was tested
  here and moved no retrieval metric in any direction.
- **Our edges win a disagreement**, because they are the ones this project can
  reproduce and test.
- **Check what came back.** The bundle header prints the member count. If
  `--members-from` yields fewer members than plain `trace` did, something is
  wrong with the list, not with the repository.

## Empty results are answers

Distinguish these, and report which one you got:

```text
no existing unit overlaps this one            # nothing reached the comparison
nothing above the 0.27 floor (6 suppressed)   # six checked, none close enough
No resolved neighbours.                       # may be unresolved, not isolated
```

The second is stronger than the first. The third is **not** an assertion of
isolation: call resolution reaches 32.1% of edges, so dynamic dispatch,
callables passed as arguments, and registry lookups produce no edge. A slice
is a **lower bound on the real path** and the header prints how many edges it
walked so you can tell a small slice from a broken one.

## When to use ordinary Grep and Read instead

- The repository is **not Python**, or the relevant code is not.
- **No index exists** and building one is not worth it. For a one-line change,
  grep.
- You are **looking for a string**, not a function. Grep wins outright.
- The task is not about code structure — debugging, renaming, formatting,
  config, dependency work. *Editing a file still ends with `check`; only the
  understanding half is skippable.*
- You are **inside a subagent that was already handed the relevant units.** Do
  not re-retrieve.

## Reporting

Say what you checked and what the answer was, not that you searched.

- Name the command and its scope: "`check` on 12 changed functions, none
  introduced overlap."
- If you took a weak path — `search`, or `similar --draft` — **say so**, and
  attach less confidence to the conclusion.
- Writing new code is a normal outcome, not a failed search. On a third of
  measured cases where writing the function was correct, a model shown eight
  plausible candidates picked one instead.

## Further reading

- [`docs/trace.md`](../../docs/trace.md) — the follower, its passes, and what
  it costs
- [`docs/check.md`](../../docs/check.md) — alarm rates per corpus
- [`docs/roadmap.md`](../../docs/roadmap.md) — where this is going
- [`references/retrieval-limits.md`](references/retrieval-limits.md) — why
  `search` is the weak path
