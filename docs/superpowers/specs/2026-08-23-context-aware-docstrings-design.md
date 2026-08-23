# Context-aware docstrings: drift detection and assisted fill

Status: design, not implemented. Written 2026-08-23.

## Summary

Two commands under `code-steward docs`, sharing one bundle format and
built in this order:

1. `docs drift` -- read-only. Nominate documented functions whose
   docstring may no longer describe the code, emit a `trace` slice for
   each, and let an agent adjudicate.
2. `docs fill` -- read-only. Find undocumented functions, emit a
   `trace` slice for each in dependency order, and propose docstrings.
   Prints proposals; never edits source.

Drift is built first because it is measurable and because it becomes
the only automated check `fill` has.

## Why this and not an off-the-shelf tool

`pydoclint`, `darglint`, and Ruff's preview `DOC` rules already compare
a docstring's params, returns, and raises against the function's own
signature and body. That work is done and this project should not
redo it. `docs drift` defers local checking to those tools explicitly,
and the documentation must say so.

What none of them do is adjudicate a docstring against the function's
callers, callees, and tests. That requires a call graph, which this
project already builds, and a judgement step, which no linter has.

The precedent is `jscpd` placing second on this project's own
similarity benchmark. An off-the-shelf tool that already solves the
problem is a reason not to build, and checking for one first is now
part of the process.

## What is already available

`CodeUnit` stores `doc_text`, `signature`, `parameters`, `returns`,
and `body_hash`, so "which functions are undocumented" is a query
against the existing index rather than new parsing.

`trace.build_slice` already assembles target, callers with call sites,
callees, and tests, and `trace.render_markdown` already renders it.
Both commands consume that directly.

`check.changed_python_files` already resolves a changed-file set from
a git ref. Both commands reuse it.

`pyproject.toml` enables pydocstyle formatting rules and deliberately
defers the D1xx missing-docstring rules; see `docs/code-quality.md`.
`docs fill` is therefore opt-in tooling, not enforcement of a policy
this repository has adopted.

## Scope and write policy

Both subcommands default to **changed files**, resolved from `--base`,
exactly as `check` does. `--all` widens to the repository.

Changed-file scope is a deliberate default, not a workaround:

- `git blame` over a line range is affordable per changed file and
  expensive across a whole repository.
- Drift is introduced by edits, so a changed-file set is where it
  lives.
- It makes `docs` composable with `check` in one pre-commit pass,
  which is issue #55 item 1, the path-level pass that does not exist
  yet.

**Neither subcommand writes to source.** `fill` prints proposed
docstrings and a unified diff to stdout; applying them is the agent's
or the developer's action.

The reasoning: a generated docstring is the one output of this project
that cannot be scored, because ground truth for the correct docstring
is exactly what a function without one lacks. Writing unverifiable
generated prose into source is how a tool with a measurement culture
loses it.

The counter-argument is recorded rather than dismissed: a `--write`
flag is what makes fill usable across hundreds of functions, and
requiring a manual apply step is friction that may mean nobody runs
it. The decision is to ship read-only, use it on a real repository,
and revisit `--write` once the proposals have been read in anger.

## Nomination

Nomination is **local and cheap**. The slice is used at adjudication,
not at nomination. This is a smaller claim than "slice-level
detection" and is stated here so it is not overstated later: two of
the three surviving signals need no graph at all. What no linter does
is the adjudication step that follows.

### Signal 1 -- identifier named in the docstring is absent from the body

The docstring names `_resolve_target` and nothing in the normalised
body mentions it. Pure text against the unparsed body: no graph, no
git, no dependency on call resolution.

Expected to be the highest-precision signal available, and it is also
reused as `fill`'s hallucination metric.

### Signal 2 -- stale by blame

The newest commit touching the function's body lines is later than the
newest commit touching its docstring lines, via `git blame -w -M`
(ignore whitespace, follow moves).

This is the volume driver and the noisiest signal. Reformatting,
renames, and mass refactors all move body lines without changing
meaning, and a body edited more recently than its docstring describes
a great deal of perfectly accurate documentation.

**This is the signal most likely to fail the kill criterion below.**
If it does, `docs drift` becomes a smaller and sharper tool, and that
is an acceptable outcome.

### Signal 3 -- visibility claim contradicted by callers

The docstring says internal, private, or do not call directly, and
there are resolved callers outside the module. Genuinely graph-based,
high precision, low volume. Expected to fire a handful of times per
repository.

### Deliberately not built: documented raise absent from the callee tree

Call resolution is at 54.7%. At that rate, "nothing in the callee tree
raises `ValueError`" is not evidence that nothing raises `ValueError`.
Shipping this signal now would manufacture false positives and
attribute them to the docstring rather than to the resolver.

Revisit after issue #55 item 3 raises call resolution.

## Adjudication

Each nominated function is emitted as a `trace` bundle -- target
source, callers with call sites, callees, tests -- and an agent
returns `DRIFT`, `CLEAR`, or `UNSURE`.

`CLEAR` and `UNSURE` are ordinary outcomes and must be worded that
way. `NO_CANDIDATE` in the reviewer agent was written as "a report
that you did not find something, not a finding that nothing exists",
and that hedge is part of why the reviewer was talked into a positive
verdict on a third of negative cases. The declining verdicts here get
plain wording.

Code Steward does not call a model. It assembles the bundle; the agent
judges. This follows the measured result in
`benchmarks/verdict/bundle_score.py`: a cheap model handed an
assembled bundle scored 0.917 with 30/30 on negatives, while a larger
reviewer handed a ranked packet false-positived on a third.

## Measurement

Two numbers, and the second is the one that matters.

### Nomination rate -- unlabelled, cheap

`docs drift --rate` reports nomination rate per signal across the
pinned public corpora, before adjudication. Follows `check --rate`. If
a signal nominates most of a mature repository, that is reported
plainly and the tool is a report rather than a gate, in those words.

### Precision against a control -- labelled, expensive

A nominated function labelled `DRIFT` proves nothing alone, because
the base rate is unknown. If a third of all documented functions are
drifted, a signal with 33% precision is worth zero.

Procedure:

- Sample 100 nominated functions, stratified across the three
  signals, capped per repository so one corpus cannot dominate.
- Sample 100 un-nominated documented functions at random from the
  same repositories.
- Shuffle both sets together, strip every trace of which set a case
  came from, and label blind: `DRIFT` / `CLEAR` / `UNSURE`. Same
  format, same labeller, no way to distinguish a nomination from a
  control.

### Pre-registered kill criterion

Fixed before the measurement runs:

> A signal survives only if its precision is at least **twice** the
> base rate measured in the control, with the difference significant
> by Fisher's exact test at p < 0.05.

Per signal, not pooled. Pooling would let signal 1 carry signal 2.

Any signal that fails is dropped, and the negative result is written
into `docs/doc-drift.md`, as the p = 0.549 reuse-evidence result was.

### Synthetic positive control -- separate, and not the headline

Mutate documented functions semantically -- invert a condition, change
a return value, drop a raise -- and check whether the pipeline catches
it. This manufactures labelled positives at no cost.

Synthetic drift is not distributed like real drift, so this is a
sanity floor: failing it is damning, passing it proves little. It does
not appear in headline numbers.

### Adjudication scored separately from nomination

Reuses the shape of `benchmarks/verdict/bundle_score.py`: cheap model,
blind labels, invented findings counted. Nomination recall and agent
precision are different failures with different fixes. Conflating
retrieval with judgement is how this project misdiagnosed itself
twice.

### Held out by construction

Sampling uses the existing hash-order slicing in
`benchmarks/similarity/corpus.py`, so the labelled set never overlaps
whatever is tuned against. Once labelled, it is frozen and is never
tuned against.

## Fill

### Dependency order

`fill` runs in dependency order, not file order: callees first, then
the target, then callers. Topological sort over the resolved callee
graph, cycles broken arbitrarily.

By the time a caller's docstring is written, everything it invokes is
already documented, so the docstring describes composed behaviour
rather than guessing at it. This is what makes the pass "beginning to
end" rather than a loop over undocumented functions.

### Return contracts without annotations

Undocumented functions are usually also unannotated, so
`CodeUnit.returns` is empty exactly when it is needed. The bundle
therefore carries two things the AST supplies without inference:

- the shape of every `return` statement in the body;
- what each caller does with the result -- subscripts it, awaits it,
  truth-tests it, discards it.

A caller that writes `if result is None` says more about the return
contract than an annotation would.

### The closed loop

After `fill` proposes a docstring, `docs drift` runs against it.
Signal 1 catches a hallucinated delegation directly.

Acceptance criteria for `fill`:

- proposals pass `docs drift` clean;
- a blind spot-check of 30 proposals;
- **hallucination metric**: the proportion of generated docstrings
  naming an identifier absent from the slice. This should be zero, and
  if it is not, the number is published.

### Deliberately skipped

Trivial functions -- one-line returns, properties, dunders. This
repository defers D1xx on purpose. Blanket coverage that emits
"Return the name." is noise that makes real docstrings harder to
find. Undocumented and trivial is a legitimate state.

## Components

| Module | Responsibility |
| --- | --- |
| `src/code_steward/docdrift.py` | The three signals, a `DocFinding` type, nomination and rate. Consumes `trace.build_slice`. |
| `src/code_steward/docfill.py` | Undocumented selection, topological ordering, bundle emission. |
| `src/code_steward/gitmeta.py` | Gains `line_range_commits()` -- `git blame -w -M` over a line range. Its only new dependency. |
| `src/code_steward/cli.py` | `cmd_docs`, with `drift` and `fill` subcommands. Reuses `check.changed_python_files`. |
| `benchmarks/docs/` | `nominate_rate.py`, `label_sample.py`, `drift_score.py`, `fill_score.py`. |
| `docs/doc-drift.md` | The public page, including whichever signals die. |

## Data flow

    changed files (--base)  ->  index lookup  ->  documented units
      -> signal 1 / 2 / 3    ->  nominated units
      -> trace.build_slice   ->  bundle per unit
      -> agent               ->  DRIFT / CLEAR / UNSURE

    changed files (--base)  ->  index lookup  ->  undocumented units
      -> skip trivial        ->  topological sort by callee edges
      -> trace.build_slice   ->  bundle per unit, in order
      -> agent               ->  proposed docstring
      -> docs drift          ->  hallucination check

## Error handling

- No git repository, or `--base` unresolvable: signal 2 is skipped
  with a stated reason, and signals 1 and 3 still run. Absence of git
  degrades the tool; it must not fail it.
- Unparseable docstring section: the docstring is treated as prose.
  Signals must not require a Google or NumPy section layout.
- Empty slice: `trace` already renders the message that unresolved
  dynamic dispatch may mean incomplete rather than isolated. That
  message must reach the adjudicating agent, not be stripped.
- A unit whose file no longer exists on disk: skipped, counted, and
  reported in the summary rather than silently dropped.

## Testing

- Per-signal unit tests over fixture trees, following the existing
  pattern.
- Blame tests need a real temporary git repository each, which is
  slower than the rest of the suite; they are marked and kept few.
- **Assert the finding, never that the command ran.** Both the
  introduced-only filter and the shingle cache passed their tests
  while doing nothing, because those tests checked that output
  appeared rather than what was in it.

## Risks

- `docs drift` may reduce to one good signal. The kill criterion is
  the answer, and a one-signal tool that is right is preferable to a
  three-signal tool that is not.
- `docs fill` may produce docstrings that read plausibly and are
  subtly wrong in ways no automated check catches. Staying read-only
  and emitting proposals limits the damage; it does not eliminate it.
- Neither answer is airtight, and neither should be described as one.

## Relationship to issue #55

This lands inside item 1, the path-level pass, rather than beside it:
`check` and `docs` share a changed-file scope and a bundle format, and
composing them is the point.

It is blocked in part by item 3, call resolution, which is why the
documented-raise signal is deferred.
