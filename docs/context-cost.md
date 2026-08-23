# Pre-registration: what a unit of context costs, and what it buys

**Status: written and committed before the measurement.** Nothing in
the results section exists yet.

## Why this measurement exists

This project publishes **10.3x** compression on Django. Graph Code
Review publishes **65x**. Neither number converts into the other,
because they use different denominators -- ours is the files an agent
would open, theirs is the whole corpus. On Django, the same Code
Steward bundle scores 10.3x against one denominator and 1,416x
against the other. The ratio is a statement about the baseline at
least as much as about the tool.

So ratios are abandoned here. This measures the **numerator only**:
how many bytes and tokens each tool puts into a context window to
answer the same question about the same function in the same
repository, and how complete what it delivers actually is.

There is a second question behind the first, and it is the one worth
the effort: **their graph is broader than ours. Would using their
selection with our packaging beat either tool alone?** That is arm D.

## The probe that came first, and what it changed

Before fixing this design I ran their CLI once against *this*
repository -- not Django -- to see the shape of a response. It
returned `line_start` and `line_end` for every node.

That changed the design. An agent holding their output does not have
to read whole files; it can read exact spans. Costing their arm at
whole-file reads would have been a strawman and would have flattered
this project by a large factor. Arm C reads spans.

Recorded because the probe preceded the criterion, which is the thing
this project keeps getting wrong.

## Corpus and targets

Django at the pinned public commit
`fe0a859f537d4238cf49fca39073513206f83122`, indexed by both tools.
Code Steward: 11,612 units. Graph Code Review: 931 files, 12,611
nodes, 59,513 edges.

**200 target functions**, drawn in blake2b hash order from the Code
Steward index, restricted to functions that satisfy two conditions:
**both** tools resolve them to the same declaration, matched on
relative path and name; and the function's **name is unique across
the corpus** -- 3,513 of Django's 4,580 distinct function names are.

Hash order so the sample cannot follow the answers.

The uniqueness restriction exists because the answer key below is
name-based and is only exact when the name is. It also removes the
cases where name-based resolution is hardest, which is the mechanism
their graph appears to use, **so this restriction favours their
arm.** Stated here rather than discovered in the discussion.

The corpus checkout contains `django/` and no test suite, so
`tests_for` would return an empty result for every target in both
arms. It is dropped from the cost accounting rather than charged to
either side, and the test dimension is simply not measured here.

The match rate is **published, not silently applied**. Targets only
one tool knows about are excluded from the paired comparison and
counted in a line of their own, because an exclusion that favours one
arm is a result about coverage wearing the costume of a sample.

## Two accounting rules fixed after the probe, before the run

Both were discovered while wiring the harness, and both are written
down here rather than in the results.

**Targets are addressed unambiguously in every arm.** Their CLI
resolves a bare name to 20 candidates for a name like `get_template`
and returns a disambiguation list instead of an answer. Every arm is
therefore given the fully qualified form of the target -- our unit ID
for ours, `path::Class.method` for theirs. Both tools support exact
addressing, so this is symmetric, and it keeps the measurement about
delivered context rather than about name collisions.

**No disambiguation round trips are counted**, for the same reason.
This suppresses a real cost that falls on their arm in ordinary use
and does not fall on ours; the suppression favours them, and it is
recorded here so the result is not read as if the question never
arose.

**Arm D inherits no call sites.** Their nodes carry line spans but
not the line inside a caller where the call happens, so the hybrid
bundle cannot include the call-site pointers arm A has. That is a
property of their selection, not a handicap imposed by this harness,
and the results will say which side of the comparison it lands on.

## The task, identical for every arm

> You are about to change function `F`. Deliver what is needed to
> understand its immediate neighbourhood: its callers, its callees,
> and the tests that cover it, with enough source to judge.

## The four arms

| Arm | What is counted |
| --- | --- |
| **A -- Code Steward** | Bytes of one `code-steward trace F` bundle. Bodies included; nothing further to read. |
| **B -- GCR, as delivered** | Bytes of `callers_of` + `callees_of`. Names, paths and line spans. No bodies. |
| **C -- GCR to sufficiency** | Arm B plus the source of every span it names, deduplicated. This is the fair comparison to A, because A already contains its bodies. |
| **D -- Hybrid** | Their node set, rendered through our bundle renderer. Their selection, our packaging. |

Arm B is reported because it is the honest description of what lands
in context from one call, and arm C because a name without a body is
not yet an answer. Reporting only one of them would be a choice
dressed as a measurement.

Bytes are primary; tokens are reported beside them using
`benchmarks/tokens.py`, since the bytes-to-tokens ratio moves with
how much of the text is identifiers rather than prose.

## Coverage, and the key that had to be thrown away

Cheap and empty wins on bytes. Every cost figure is therefore paired
with what it bought.

**The first version of this section specified a union key** -- every
claim either tool made, kept where the source confirmed it -- and a
three-target smoke test of the harness killed it. Where our slice
comes back empty, the union collapses to their claims alone and
their recall is **1.0 by construction**. That is the third criterion
in this project that could not fail, and the first one caught before
the run rather than after.

The key is therefore **independent of both tools**: a single AST pass
over the corpus that records, for every function, the names it calls.
The callers of a target are then every function whose body calls that
target's name. Neither graph contributes to it and both are scored
against it.

That key is only exact if the name is unambiguous, which is why the
sample is restricted to unique names -- see above.

Coverage is **recall of that independent caller set**. Claims a tool
makes that are absent from it are reported separately as apparent
over-claiming, not folded into a single score.

**The caller direction only.** A name-based key cannot be built for
callees without collapsing on common method names, so callees are
paid for in the cost arms and not scored. Both arms are treated
identically.

## The decision rule, fixed now

Paired per-target comparisons. Primary statistic on both outcomes is
the one-sided paired sign-flip permutation test at alpha 0.05, the
same test pre-registered for the skill A/B, on:

1. **Bytes per target** (lower is better)
2. **Recall of the confirmed union** (higher is better)

**A win requires not losing on the other.** Fewer bytes at lower
coverage is not a better tool, it is a smaller answer, and it will be
reported as one.

| Outcome | What this project does |
| --- | --- |
| C uses significantly more bytes than A at equal recall | Assembly is worth what it claims. Publish, and stop quoting ratios. |
| C matches A on bytes at equal recall | The compression claim is a baseline artefact. Say so in the README, in those words. |
| **D beats A on recall at comparable bytes** | **Their selection is better than ours. Adopt it behind the companion contract, and say where the improvement came from.** |
| D is no better than A | Their broader graph does not help on Python. The contract stays a specification. |
| A beats C on both | Report it, and note that a Python-only tool beating a 55-language one on Python is the expected direction, not a triumph. |

## What this cannot show

- **One language.** Their graph covers roughly 55 and this measures
  the one where the comparison is least favourable to them. Nothing
  here says anything about the other 54.
- **One repository**, and a library-shaped one.
- **No agent is involved.** This measures what each tool delivers,
  not whether a model does better work with it. That is the skill
  A/B, and it is a separate and harder question.
- **Their tool is being driven by this project.** If a better way to
  use their surface exists, this design will miss it, and the miss
  will look like their result.

## What was seen before the run

Two smoke tests during harness development, three targets and then
five, both taken from the front of the hash order -- so **five of the
200 targets were visible before the run began**. The first smoke test
is what killed the union key.

No arm was changed in response to a number. The definitions of the
four arms have not moved since they were first written. But five
paired observations were seen, and a page that hides that while
claiming pre-registration is worth nothing.

## Stopping rule

Run once, over all 200 targets. No dropping targets that behave
badly, no swapping the arms' definitions after seeing bytes, no
re-running one arm. If a bug is found afterwards, the fix, the re-run
and the original numbers are all published.

---

# Results

Run once, 200 targets, Django. Everything above this line was written
before the run; nothing above it has been edited since.

## What each arm cost, and what it found

| Arm | mean bytes | median bytes | mean recall |
| --- | --- | --- | --- |
| **A -- Code Steward** | **4,266** | **2,064** | 0.708 |
| B -- GCR as delivered | 6,303 | 4,961 | no bodies |
| C -- GCR to sufficiency | 10,825 | 6,701 | **0.915** |
| **D -- Hybrid** | 5,165 | 2,296 | **0.915** |

Recall is over the 134 targets of 200 that have a non-empty caller
key. The other 66 have no callers anywhere in the corpus.

## The pre-registered result: not a win

| Comparison | Difference | p |
| --- | --- | --- |
| Bytes, A vs C | **-6,559** in our favour | < 0.001 |
| Recall, A vs C | **-0.207**, against us | 1.0 |

Code Steward delivers a slice in **39% of the bytes** their arm needs
to reach the same question -- and finds **21 points less** of the
real caller set while doing it.

The rule fixed before the run says a win on bytes at lower coverage
is not a win. **It is not a win.** Fewer bytes for a less complete
answer is a smaller answer, and this page will not call it
compression.

Direction, across the 134 scored targets: they beat us on **38**, we
beat them on **1**.

## The hybrid is the finding

Their node selection, rendered through our bundle:

| Comparison | Difference | p |
| --- | --- | --- |
| Recall, D vs A | **+0.207** | < 0.001 |
| Recall, D vs C | 0.000, tied on all 134 | -- |
| Bytes, D vs A | +899 mean, **-24 median** | 1.0 |

**Their selection is better than ours, and our packaging is better
than theirs.** The hybrid carries their complete caller set at 48% of
the bytes their own surface needs, for a median byte cost against our
bundle of *negative twenty-four*. Every node they named mapped onto
one of our units; nothing was lost in translation, and the hybrid
never named a unit outside the key.

By the decision table, this fires the row that says adopt their
selection. Before doing that, the next section explains why it may
not be necessary.

## Why they find callers we miss

The mechanism is not that they see calls we cannot. **We see them and
decline to resolve them.**

Their gap over us is `obj.method()`. Our indexer records such a call
as an unresolved symbol row -- `response.has_header` -- and never
promotes it to an edge, so it never enters a slice. On
`HttpResponseBase.has_header`, an 11-caller key where we scored 0.0,
every missing caller is sitting in our own index under exactly that
shape.

Across Django:

| | count |
| --- | --- |
| `CALLS` edges recorded | 29,895 |
| of those, unresolved | 23,161 |
| of those, attribute-style `obj.method()` | 13,957 |
| **of those, whose method name is unique in the index** | **2,738** |

Resolving only the unambiguous ones would move edge resolution from
**22.5% to 31.7%** without a single guess: if exactly one unit in the
index is named `has_header`, then `response.has_header` is that unit
or it is nothing.

That is a change to this project, not an integration with theirs.

## What this does not license

- **Do not measure that fix on this sample.** These 200 targets are
  spent. A repair evaluated on the set that motivated it is tuned,
  not tested; a fresh hash-order draw is required, and the sample
  must exclude these.
- **The key rewards name matching.** It is built by name, on targets
  chosen for having unique names, and name matching appears to be
  their mechanism. On a unique name that is close to exact -- a call
  to a name only one function has is that function -- but the
  restriction removed the cases where their approach is weakest, and
  their 0.915 should be read with that in mind.
- **Their 20 claims outside the key against our 8** is not
  necessarily over-claiming by either side. The key misses dynamic
  dispatch, and both numbers are small.
- **Python only.** This is the language where a 55-language tool has
  least to show, and it still won the coverage comparison.

## Deviations from the pre-registration

1. **The run was executed twice.** The first pass omitted arm D's
   recall, which the decision table requires and which I failed to
   collect. The re-run added it and changed nothing else: arms A, B
   and C are **byte-identical** across both passes, which was checked
   rather than assumed. Both files are in the repository.
2. Everything else ran as written.
