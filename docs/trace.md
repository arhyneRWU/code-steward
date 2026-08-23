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

## What it saves

Measured by tracing every function in a repository at the default
depth and comparing the bundle against the whole content of every
file the slice touches.

| Repository | Functions | With resolved neighbours | Compression | Mean bundle |
| --- | --- | --- | --- | --- |
| Django | 9,345 | 54.7% | **10.3x** | 4,170 bytes |
| Code Steward | 157 | 90.4% | **4.7x** | 4,441 bytes |

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

- **Absolute imports into a `src/` layout do not resolve.** The index
  keys a module by its path, so `src/pkg/mod.py` becomes
  `src.pkg.mod` while the import says `pkg.mod`. Relative imports
  inside the package are fine; the cost falls mostly on test files,
  which import absolutely. This is a known defect, not a design
  choice.
- **Breadth-first, then truncated.** With `--limit` reached, the slice
  says it was truncated rather than trimming quietly. Breadth-first
  in both directions means a widely-used function does not lose its
  direct callers to its own transitive callees.
- **Nothing here is ranked.** Every resolved neighbour at the
  requested depth is included. There is no relevance model deciding
  which caller matters, and at depth 2 or more on a hub function the
  slice gets large fast.
- **Python only.**

Reproduce with `make bench-trace ROOT=<indexed repo> LABEL=<name>`.
Committed at
[`trace_bundle_django.json`](../benchmarks/trace_bundle_django.json)
and
[`trace_bundle_code_steward.json`](../benchmarks/trace_bundle_code_steward.json).
