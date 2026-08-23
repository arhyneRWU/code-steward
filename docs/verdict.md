# Does the reuse evidence actually reach the reviewer?

Everything measured so far is a component number. The similarity arm
has precision 1.000 on labelled pairs. The product claim is larger:
that an agent reaches a better REUSE / EXTEND / REFACTOR decision
*before* writing code. Nothing had tested that.

This is the first half of testing it, and it is worth being exact
about which half.

**What is measured here:** whether the evidence needed to reach the
right verdict arrives in front of the reviewer at all.

**What is not:** whether a reviewer uses it. No agent is run. Evidence
arriving is a *necessary* condition for the product claim and not the
claim itself — a perfect detector that changes no decisions would
score perfectly on this page. The agent-in-the-loop half is
[still open](#what-this-cannot-tell-you).

## The protocol

A case is built from the frozen
[similarity labels](../benchmarks/similarity/reuse_pair_labels.json).
Take a function whose duplicate is already labelled, **remove it from
the repository** — it has not been written yet — and use its docstring
summary as the task an agent would type. The right answer is known in
advance.

- **Positive case** (`reuse-available`): the target has a labelled
  `same-behaviour` duplicate. Both directions are used; either
  function could have been the one about to be written.
- **Negative case** (`no-reuse-available`): the target appears only in
  `unrelated` pairs. The correct outcome is that nothing is surfaced.

Three arms on identical cases:

| Arm | Input | What it is |
| --- | --- | --- |
| `packet` | task sentence | the production retrieval path; what a reviewer sees today. **The control.** |
| `packet-reuse` | task sentence | the same packet with near-duplicate evidence attached to each candidate |
| `draft-similar` | the function's body | the pre-implementation path — `similar --draft` |

`draft-similar` is **not** a like-for-like comparison with the other
two. It is handed the code; they are handed a sentence. It is scored
anyway, because it is the path the product recommends and the one the
skill and reviewer agent are told to try first.

## Result

496 cases built, **250 scored, 246 excluded** — see the exclusion note
below, it is the largest caveat on this page.

| Arm | Duplicate surfaced | False positives | Unlabelled evidence | Mean bytes |
| --- | --- | --- | --- | --- |
| `packet` (control) | 0.459 | 0.176 | 75 | 2,782 |
| `packet-reuse` | 0.654 | 0.264 | 67 | 4,405 |
| **`draft-similar`** | **0.994** | 0.264 | 65 | **2,636** |

Positives n=159, negatives n=91, identical across arms. Committed at
[`benchmarks/verdict/evidence.json`](../benchmarks/verdict/evidence.json);
reproduce with `make bench-verdict`.

These figures are a re-run after body term coverage entered the
ranker's score; the first run predated it. Both packet arms moved a
little in the same direction — a slightly higher surfaced rate, a
slightly lower false-positive rate, a few more bytes. `draft-similar`
is unchanged to three places, which is expected: that arm does not
use the ranker. The movement is small enough that no conclusion on
this page turns on it.

## What it says

**`--reuse` earns its place, and it is not free.** It lifts the
surfaced rate from 0.459 to 0.654 — twenty more cases in a hundred
where the duplicate reaches the reviewer — and costs **58% more bytes**
and 8.8 points of false-positive rate. That is a real trade, not a
free win, and it is why the flag is opt-in rather than default.

**Drafting and comparing dominates everything else.** 0.994 against
the control's 0.459, at *fewer* bytes than the plain packet (2,636 vs
2,782) and a false-positive rate no worse than `--reuse`. One case in
159 was missed. This is the strongest result the project has produced
and it is the one that most directly supports the design: if an agent
can sketch the function, sketching and comparing finds the existing
one almost every time, for free.

The skill and the reviewer agent were already told to draft-and-
compare first and fall back to the ranker. That ordering was reasoned
from a component number. It is now measured.

**The control is being flattered and still loses badly.** Half the
cases were excluded because the function has no docstring — and
undocumented code is precisely where the ranker is
[documented to do worst](retrieval.md). The 0.459 is the packet path's
score on its best available ground.

**Every arm surfaces something on a fifth to a quarter of negatives.**
Including the plain packet, which has no reuse evidence at all, so
this is not a property `--reuse` introduced. For the similarity arms
it has an obvious cause: `similar` has a result limit but no score
floor, so it returns weak matches rather than nothing. Whether it
should have a floor, and where, is **not decided here** — choosing one
against this set would be tuning against the gold set, which this
project has committed not to do. It needs its own held-out
measurement.

## What this cannot tell you

**No verdict was scored.** No reviewer agent was run. Every number
above is about evidence arriving, not about a decision changing. It is
entirely possible for `--reuse` to lift the surfaced rate by sixteen
points and change no verdicts, because the reviewer would have reached
the same conclusion from the packet alone. Measuring that needs agent
runs, and it is the open half.

**Half the cases are excluded, and not at random.** 246 of 496 targets
have no docstring, so their "task description" would have been the
function's own identifier, which is not a task description. Excluding
them is right; the consequence is that this page speaks only about
documented functions. Undocumented code is the larger population in
every corpus measured, and its behaviour here is unknown.

**Negatives are bounded by the same pooling hole as everything else.**
A unit surfaced on a negative case is only a false positive if the
labels call it unrelated to that target. Roughly 65–73 negatives per
arm surfaced something nobody labelled; those are reported separately
and are not counted either way.

**`draft-similar` is measured on the real body.** A real agent drafts
an approximation, not the function that was removed. The rename
tolerance in [`docs/similarity.md`](similarity.md) bounds how fast
that degrades — a renamed signature still scores 0.535, a wholly
renamed body 0.015 — but the 0.994 here is an upper bound on what a
draft achieves, not the figure a real draft would get.

## The reviewer half: does the evidence change the verdict?

Everything above measures evidence *arriving*. The product claim is
that a reviewer reaches a better REUSE / EXTEND / REFACTOR decision,
and evidence arriving does not prove that. This section measures the
decision.

Sixty held-out cases -- ten per corpus per polarity -- were put to a
reviewer agent twice, once per packet arm, for 120 judgements. Every
judgement came back; none were unparsable.

Three things keep it honest. Candidates are **blinded**: unit IDs,
file paths, and dotted qualnames are replaced with labels `C1..C8`,
so a reviewer cannot open the file and answer from the source instead
of from the packet. The **arms are unnamed**, and the two arms of one
case are placed half a batch apart so no reviewer sees both. The
**sample is drawn in hash order** of the case ID, before anything was
run.

| Arm | Positive | Negative | Overall |
| --- | --- | --- | --- |
| `packet` | 0.700 | 0.667 | 0.683 |
| `packet-reuse` | 0.733 | 0.733 | 0.733 |

A positive case is correct only when the reviewer answers REUSE or
EXTEND *and names the labelled duplicate*. A negative case is correct
only when it answers NEW. Committed at
[`reviewer.json`](../benchmarks/verdict/reviewer.json), key at
[`reviewer_key.json`](../benchmarks/verdict/reviewer_key.json).

### What it says

**The reuse evidence does not measurably change the verdict.** The
arms are paired on the same sixty cases, so the right test is
McNemar's. Eleven cases disagreed: four where the plain packet was
right and the reuse packet wrong, seven the other way. Exact
two-sided **p = 0.549**. The five-point overall gap is noise at this
sample size, and nothing here supports the claim that attaching
near-duplicate evidence produces better decisions.

This is the measurement the project most needed and it came back
null. `--reuse` costs 58% more bytes. On the evidence so far those
bytes buy a better-populated packet and no better answer.

**The expensive failure is the one nobody was measuring.** On a third
of negative cases -- 10 of 30 for `packet`, 8 of 30 for
`packet-reuse` -- the reviewer was talked into REUSE or EXTEND when
the correct answer was to write the function. Retrieval always
returns its eight best candidates, and a reviewer handed eight
plausible-looking functions tends to pick one. This is worse than
missing a duplicate: a missed duplicate costs a little redundancy, a
wrong reuse wires the caller to code that does not do the job.

**Verdict accuracy on positives is capped by retrieval.** For 8 of 30
positive cases the labelled duplicate never entered the packet at
all, so no reviewer could have named it. Those are counted as wrong,
because they are the arm's failure and not the reviewer's -- and they
are most of the gap between 0.700 and a perfect score.

### Caveats

**This sample is easier than the full case set.** Sampling ten cases
per corpus per polarity gives Django a third of the weight, and
Django is where retrieval is strongest: the duplicate reached the
packet on 10 of 10 Django positives, against 5 of 10 for Home
Assistant. The sub-sample's surfaced rate is 0.733 where the pooled
figure over all 250 scored cases is 0.459. Read the accuracy figures
as *the reviewer's skill given good retrieval*, not as an end-to-end
product number, which would be lower.

**n = 30 per polarity per arm.** The sample size was a budget, not a
power calculation. It can detect a large effect and cannot rule out a
small one; p = 0.549 says the data are consistent with no difference,
not that no difference exists.

**Blinding costs the reviewer information.** A real reviewer sees
paths and module names, which carry genuine signal about whether two
functions belong to the same concern. These figures are a floor.

**One reviewer model, one prompt.** No claim is made that a different
reviewer, or a prompt that argued harder for NEW, would score the
same. The negative-case failure in particular looks like something a
prompt change might move, and that is untested.

## What a realistic draft is actually worth

The 0.994 above compares the **real removed body**. `docs/direction.md`
reframed the whole project around drafting, and that reframe rested on
a number no agent could actually produce. This measures what one can.

Fifty held-out positive cases. An agent was given each function's
name, signature, and docstring -- what a developer has before writing
it -- and asked for a plausible body, with no access to the source.
That body was then compared against the repository in place of the
real one.

| Arm | Usable drafts | All 50 cases |
| --- | --- | --- |
| `real-body` (the published upper bound) | **1.000** | 1.000 |
| `agent-draft`, no floor | 0.814 | **0.700** |
| `agent-draft`, shipped 0.27 floor | 0.535 | **0.460** |

Seven of fifty drafts came out below the minimum token count and
could not be compared at all. They are excluded from the first column
and counted as failures in the second. **The second column is what a
user experiences**, and it is the honest headline.

Committed at
[`realistic_draft.json`](../benchmarks/verdict/realistic_draft.json).

### The reframe's headline number does not survive

The case for drafting was 0.994 against 0.459 for the sentence packet.
The comparable figure is **0.460**. That is not a wide margin over the
packet path -- it is the same number.

This is the risk `docs/direction.md` flagged when it put this
measurement third in the order of work, and it landed. Anyone reading
that page should read this section with it.

Two things stop it being a straight refutation, and neither is a
rescue:

**The samples are not directly comparable.** The packet's 0.459 is
over 250 cases pooled across three corpora; this is 50 cases sampled
20/20/10. The two numbers being equal to three decimal places is
coincidence, not a matched comparison. A matched one has not been run.

**Recall is not the only axis, and it is the one where they tie.** The
draft path reaches 0.460 while returning nothing at all on most
non-matches -- the floor holds spurious results to roughly 0.6%. The
packet path reaches 0.459 by returning eight candidates every single
time, whether or not any of them fit. Equal recall, very different
precision, and the reviewer measurement showed precision is what was
actually costing verdicts.

So the defensible claim shrinks from *"drafting finds twice as much"*
to *"drafting finds about as much and knows when it hasn't."* That is
a smaller claim and it is the one the evidence supports. It has not
itself been put to a reviewer, so it is a hypothesis about verdicts,
not a measurement of them.

### The floor is expensive here

Of 43 usable drafts, the labelled duplicate scored:

| Band | Cases |
| --- | --- |
| not found at all | 8 |
| below 0.20 | 5 |
| 0.20 to 0.27 (lost to the floor) | 7 |
| 0.27 to 0.50 | 14 |
| above 0.50 | 9 |

The floor costs 12 of the 35 duplicates that were found, and 7 of
those sit in the narrow band just underneath it. Median score when the
duplicate was found at all: 0.415.

**The floor is not being changed in response to this.** It was chosen
against a pre-registered false-positive budget on a held-out null
distribution, before any of this existed. Moving it now, having seen
which value would score best here, is tuning against a measurement --
the precise thing [`floor.md`](floor.md) was constructed to avoid.

What this does justify is *revisiting the criterion*, once, in the
open. The 1% budget was chosen when only one side of the trade could
be measured. Both sides can be measured now, so a criterion that
weighs them against each other is defensible where it was not before.
That decision has to be written down before the number is picked.

### Caveats

**One drafting model, one prompt.** A different model, or a prompt
that pushed for closer-to-idiomatic code, would move this. The
instruction asked for a realistic first draft rather than a polished
one, which is the intent, but it is still one point in a space.

**The instruction not to search is load-bearing.** The reviewer runs
could blind the candidates; a drafting prompt cannot hide the function
name, and a name is searchable. The corpora sit well outside the
working directory and the agents were told not to look, but this rests
on compliance in a way the reviewer measurement did not.

**Home Assistant does much worse than Airflow** -- 9 of 20 against 19
of 20 unfloored. Its integrations are template-duplicated, so its
functions are short and its duplicates are near-identical
boilerplate; a from-scratch draft of a short accessor has little
surface to overlap on. That is a real population, not an artefact.

**Positive cases only.** This measures whether a draft still finds a
duplicate that exists. What a draft does on functions with no
duplicate is the floor's job and is measured in [`floor.md`](floor.md).
