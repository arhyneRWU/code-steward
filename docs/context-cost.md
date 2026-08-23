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
Steward index, restricted to functions **both** tools resolve to the
same declaration -- matched on relative path, name, and overlapping
line span. Hash order so the sample cannot follow the answers.

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
| **B -- GCR, as delivered** | Bytes of `callers_of` + `callees_of` + `tests_for`. Names, paths and line spans. No bodies. |
| **C -- GCR to sufficiency** | Arm B plus the source of every span it names, deduplicated. This is the fair comparison to A, because A already contains its bodies. |
| **D -- Hybrid** | Their node set, rendered through our bundle renderer. Their selection, our packaging. |

Arm B is reported because it is the honest description of what lands
in context from one call, and arm C because a name without a body is
not yet an answer. Reporting only one of them would be a choice
dressed as a measurement.

Bytes are primary; tokens are reported beside them using
`benchmarks/tokens.py`, since the bytes-to-tokens ratio moves with
how much of the text is identifiers rather than prose.

## Coverage, and why it is scored against neither graph

Cheap and empty wins on bytes. Every cost figure is therefore paired
with what it bought.

The answer key is the **union of both tools' claimed neighbours,
AST-confirmed** -- each claimed caller is parsed and kept only if its
source really contains a call to the target's name. Confirmation is
conservative: it confirms a claim rather than refuting one, and it
can be fooled by a name collision, so unconfirmable claims are
reported as unverified rather than counted as wrong.

Scoring against either project's own graph would decide the result
before the run. The union is symmetric and neither tool authored it.

Coverage is **recall of the confirmed union**.

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

## Stopping rule

Run once, over all 200 targets. No dropping targets that behave
badly, no swapping the arms' definitions after seeing bytes, no
re-running one arm. If a bug is found afterwards, the fix, the re-run
and the original numbers are all published.
