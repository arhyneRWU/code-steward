# Can a small model do the work?

The project's premise is that a cheap model can do useful work on a
large codebase if something hands it the right small bundle. Every
other figure in these docs measures whether the right bytes *reach* a
reader. This is the only one that measures whether a cheaper model
then succeeds.

It needed measuring for a specific reason: the same gap already
produced one wrong conclusion here. Reuse evidence in the packet
looked valuable for weeks on arrival metrics, and when the verdict
was finally scored it was
[null](verdict.md#the-reviewer-half-does-the-evidence-change-the-verdict).

## Method

Sixty bundles of eight functions each, mean 5.9 KB. Thirty contain a
pair the blind labelling called `same-behaviour`; thirty contain no
labelled duplicate. The model is asked which two functions, if any,
do the same work.

**Ground truth is the blind pair labels, not this project's
similarity scores.** Scoring a model against our own Jaccard would
measure whether it can reproduce our arithmetic, which is a different
and much less interesting question.

**`overlapping` pairs are excluded entirely.** They are the ambiguous
middle of the label set, where a model calling one a duplicate is
neither right nor wrong. Including them would make the score depend
on where a human judgement call fell.

Distractors come from the same corpus, so the task cannot be won by
noticing that one function looks out of place, and only from units
the labels never implicate in any duplication.

## Result — Haiku 4.5

| | Correct | Rate |
| --- | --- | --- |
| Duplicate present | 25 / 30 | 0.833 |
| No duplicate present | 30 / 30 | **1.000** |
| **Overall** | 55 / 60 | **0.917** |

**Every one of the five misses was a decline, not a wrong pair.** The
model never named two functions that were not the labelled pair, and
never invented a duplicate in a clean bundle. Precision on the pairs
it did name was 25/25.

Committed at
[`small_model_dry.json`](../benchmarks/verdict/small_model_dry.json).

## What it says

**The premise holds.** A cheap model given a compact bundle makes
this judgement correctly nine times in ten, and its errors are
conservative rather than confident. That is the first direct evidence
in this project that the pipeline it was built for can work.

**The contrast with the packet is the interesting part.** The two
measurements ask nearly the same question and get opposite answers:

| | Talked into a duplicate that was not there |
| --- | --- |
| Larger reviewer, given a **packet** | 33% of negatives |
| Haiku 4.5, given a **bundle** | 0 of 30 |

The cheap model did better. The difference is not capability, it is
what it was handed. A packet is eight ranked summaries, and ranking
is itself a suggestion — the reader is being told these are the best
candidates, and picking one feels like completing the task. A bundle
is eight complete functions in arbitrary order with no claim attached,
and the reader can simply look.

That is worth stating plainly because it inverts the obvious
optimisation. Months of this project went into ranking better. On
this evidence, **assembling a complete-enough slice matters more than
ranking a shortlist**, and it is also the cheaper thing to build.

## Caveats

**n = 60, one model, one prompt.** A budget, not a power calculation.
Thirty per polarity can establish that a large effect exists and
cannot bound a small one.

**Eight functions is a small bundle.** Real slices from `trace` reach
similar sizes at depth 1, but a hub function at depth 2 produces
something much larger, and nothing here says the judgement survives
that.

**The distractor pool is reused across bundles.** Once exhausted it
wraps. If an unlabelled distractor pair is a real duplicate, the
model calling it out counts against it, so the bias runs toward
understating the score rather than inflating it.

**A labelled pair is a duplicate someone found.** The gold set was
pooled by three generators, two of them lexical, so these are
duplicates a text comparison was likely to surface in the first
place. Whether a small model spots reimplementations written in
different words is not measured here and is probably worse.

**This is not an end-to-end result.** It measures the last step of
the pipeline given a good bundle. Whether the earlier steps produce
good bundles on a real task is a separate question, and `trace`
resolves only 54.7% of Django's functions.

Reproduce with `make bench-bundle-prompts` then `make
bench-bundle-score`.
