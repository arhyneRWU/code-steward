# `trace` — the function follower

`code-steward trace <unit-id>` emits one function together with what
calls it, what it calls, and the tests that pin it, as a single
self-contained bundle.

## What it is for

Handing a slice of a repository to a model that cannot hold the
repository. A smaller or cheaper model can reason about a function it
can see in full alongside the callers whose expectations it must not
break. It cannot do that from a file list, and it should not have to
read six files to reassemble what the index already knows.

This is the oldest idea in the project and the last one built. It is
also the one that most directly serves the original goal of
[stewarding the context window](../README.md#goals), as distinct from
stewarding the codebase.

```bash
code-steward trace "pkg.module::function"
code-steward trace "pkg.module::function" --callers 2 --callees 2
code-steward trace "pkg.module::function" --signatures   # no bodies
code-steward trace "pkg.module::function" --json         # for your own prompt
```

## What you get

Each neighbour carries **the line where the call actually happens** —
in the caller for a caller, in the target for a callee:

```text
### pkg.mod::caller_function
`pkg/mod.py:109-114` · depth 1 · calls the target at line 110
```

That is the difference between a follower and a pile of related
functions. Handed a forty-line caller, neither a person nor a model
should have to hunt for the one line that matters.

## What it saves

Measured by tracing every function in a repository at the default
depth and comparing the bundle against the whole content of every
file the slice touches.

| Repository | Functions | With resolved neighbours | Compression | Mean bundle |
| --- | --- | --- | --- | --- |
| Django | 9,345 | 54.7% | **10.3x** | 4,170 bytes |
| Code Steward | 158 | 90.5% | **4.2x** | 6,236 bytes |

**The comparison is deliberately generous to the baseline.** "Reading
the files" counts the whole content of every file involved, because
that is what an agent without an index actually does — it cannot know
which of a file's forty functions matter until it has read them. It
is *not* counted against the concatenated bodies of the sliced units,
which would be comparing the tool against itself.

**Compression is reported over slices that found something.** A
function with no resolved neighbour produces a bundle of one function
against a whole file, which compresses enormously and says nothing
about the follower. Averaging those in would inflate the headline
with cases where the feature did nothing. The unfiltered figures are
in the committed JSON if you want them.

A four-kilobyte bundle is the point of the number. That fits
comfortably in a small model's context alongside a task description,
where the twenty to forty kilobytes of source it replaces does not.

## The limit that matters most

**Call resolution is conservative, and on Django it resolves for
barely half of all functions.**

A call becomes an edge only when the target resolves to an indexed
unit by AST analysis. Dynamic dispatch, callables passed as
arguments, registry and plugin lookups, descriptors, and metaclass
machinery all produce nothing. Django uses a great deal of all of
those, which is why its resolved share is 54.7% against 90.4% here.

So **a slice is a lower bound on the real path.** The bundle header
prints how many edges were walked, and an empty slice says explicitly
that it may be unresolved rather than isolated:

```text
> No resolved neighbours. Calls made through dynamic dispatch,
> callables passed as arguments, or absolute imports into a `src/`
> layout do not resolve, so this may be incomplete rather than
> isolated.
```

That distinction is the whole reason the message exists. A model
handed a slice treats it as the truth, and a silently partial path is
worse than no path.

## Other limits

- **Resolution is conservative, but no longer blind to `src/`.**
  Until 2026-08-23 the index keyed `src/pkg/mod.py` as `src.pkg.mod`
  while every importer writes `pkg.mod`, so on a src-layout
  repository no absolute import resolved and the `TESTED_BY` relation
  was empty: 0 of 157 functions in this project's own `src/` had a
  test edge, against 323 tests that exercise them. The root is now
  stripped. What still does not resolve is genuine: dynamic dispatch,
  callables passed as arguments, registry lookups, metaclasses.
- **Breadth-first, then truncated.** With `--limit` reached, the slice
  says it was truncated rather than trimming quietly. Breadth-first
  in both directions means a widely-used function does not lose its
  direct callers to its own transitive callees.
- **Call sites come from the call graph, not from re-parsing.** If a
  caller invokes the target several times, every line is listed. If
  the edge resolved without line evidence, the site is simply absent
  rather than guessed.
- **Nothing here is ranked.** Every resolved neighbour at the
  requested depth is included. There is no relevance model deciding
  which caller matters, and at depth 2 or more on a hub function the
  slice gets large fast.
- **Python only.**

## Writing the docstrings that are missing

    code-steward trace --undocumented --base HEAD

Emits one bundle per function with no docstring, so the agent already
in the loop can write one against the callers that show how the
function is actually used. Code Steward assembles; it does not call a
model, and nothing leaves the machine.

This is the surviving half of a larger design that was measured and
abandoned the same day -- see
[`../docs/superpowers/specs/2026-08-23-context-aware-docstrings-design.md`](superpowers/specs/2026-08-23-context-aware-docstrings-design.md).
The other half looked for docstrings that had *drifted* from their
code. Every heuristic for that failed: the best of them nominated 0
true positives in 57 hand-read cases, and the next was already
shipped as `docvet freshness --mode drift`. This half survived
because it needs no heuristic at all. `doc_text` is empty exactly
when there is no docstring.

**Use `--base`.** Without it the command selects every undocumented
function in the repository -- 419 here, about 1.7 MB of bundles.

**What is skipped, and why.** Dunders, property accessors, and
one-line bodies. Undocumented-and-trivial is a legitimate state; this
repository defers the missing-docstring lint rules on purpose (see
[`code-quality.md`](code-quality.md)), because blanket coverage that
emits "Return the name." buries the docstrings that carry something.
The size cut is *not* `similarity.MIN_LINES`, which answers "too
small to compare for duplication" -- a different question that at
five lines would skip four-line functions with entirely non-obvious
contracts.

**Untracked files are invisible with `--base`.** The changed-file set
unions the committed diff with the staged and unstaged ones, and a
brand-new file is in none of the three. Stage it, or run without
`--base`. This is `check`'s behaviour, shared rather than forked.

**A defect this fixed, which affected every bundle.** The renderer
printed `unit.purpose`, and `purpose` falls back to the declaration
name with its underscores taken out. An undocumented `resolve_target`
therefore rendered the summary "resolve target" in the position a
docstring goes, telling the reader the function was documented when
it was not. Purpose is now printed only when a docstring exists.

## Starting from the entry points

    code-steward trace --endpoints --dry

An endpoint is a **selector**: it names the root of a path. This
emits one bundle per FastAPI route -- the handler, everything it
calls, and the duplication across all of it.

That is the shape a reader actually wants. You do not usually ask
"what does `normalize_taxon_name` do", you ask "what happens when
someone POSTs to `/organisms`", and the answer is a path with a route
at the top of it.

**Depth defaults change in this mode: `--callers 0`, `--callees 2`.**
Nothing in the repository calls a route handler -- the framework does
-- so walking up finds nothing. Walking down one hop is not enough
either: a handler that delegates twice would hand over a call with no
body behind it. Both remain overridable.

Each bundle is labelled with its route, because a reader handed
twenty of them needs to know which entry point each sits under before
reading any.

## DRY across the whole path

    code-steward trace "pkg.mod::fn" --dry

Runs the duplication comparison over **every unit in the slice**, not
just the one you asked about, and prints the result as a
`## duplication` section of the same bundle. Composes with
`--undocumented`.

This is the step neither command could take alone, and it is issue
#55 item 1. `check` only looks at functions the author changed, so a
duplicate sitting on the path but untouched by this edit is invisible
to it. `trace` lists the path without comparing it to anything. The
finding this produces belongs to the *path* rather than to the diff.

The first one it found on this repository: tracing
`check::check_files` reports that `similarity::rank_with_floor`
overlaps `similarity::rank_against` at 0.34. That is correct, and it
is also **deliberate** -- they are the floored and unfloored variants
of one ranking, and `similarity.md` says so. A true overlap is not
automatically a defect, which is the same caveat `check` carries.

**The alarm rate compounds with slice size, and that is arithmetic
rather than a property of your code.** Measured over 60 paths in this
repository's own `src/`, 32 carried at least one finding -- 53%,
against a per-function rate of 14.3% for `check`. A five-member slice
gives five independent chances to fire: `1 - (1 - 0.143)^5` is 0.53.

So **raising `--callers` or `--callees` raises the alarm rate by
construction**, and a deep slice will almost always report something.
This is a report to read, not a gate to enforce. Run `check --rate`
on your own repository first; the path-level rate will be
substantially higher than whatever that prints.

Reproduce with `make bench-trace ROOT=<indexed repo> LABEL=<name>`.
Committed at
[`trace_bundle_django.json`](../benchmarks/trace_bundle_django.json)
and
[`trace_bundle_code_steward.json`](../benchmarks/trace_bundle_code_steward.json).
