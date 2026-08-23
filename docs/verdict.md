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
