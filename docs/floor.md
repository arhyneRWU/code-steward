# The relevance floor

`similar` used to return its best candidates however weak they were.
This page is how the floor that stops it was chosen, and what it
costs.

## Why there is one

The reviewer measurement in [`verdict.md`](verdict.md) found that on a
third of cases where the correct answer was to write the function, a
reviewer handed the packet was talked into REUSE or EXTEND instead.
The cause was structural rather than a bug: retrieval always returned
its eight best candidates, so an empty result was not a thing the
tool could produce, so "nothing here fits" was not a conclusion it
could support.

The thresholds were not unknown. The skill told the agent, in prose,
that a match above roughly 0.4 was worth opening and below 0.2 was
usually coincidence. Neither number appeared anywhere in the code.
The knowledge was in the wrong place: advice to a reader, where it
should have been behaviour of the tool.

## How the value was chosen

**The criterion was fixed before the curve was read.** The floor is
the smallest value at which the false-positive rate over a null
distribution falls to or below **1%**. It is not chosen to maximise
any score, and it is not chosen on the frozen gold set -- that would
convert a benchmark into a target.

**The sample is held out by construction.** Both corpora are sliced
in hash order immediately *after* the gold sample: Home Assistant
integrations 200-260, Airflow providers 30-45. No directory in this
sample was ever labelled, and the disjointness is asserted by a test
rather than claimed in prose.

**The null distribution is cross-corpus.** Every held-out Home
Assistant function is ranked against the whole held-out Airflow
corpus and vice versa, keeping the single best match per query. The
two solve unrelated problems, so a match between them is almost
always coincidence. "Almost" matters: retry loops and dictionary
merging look the same everywhere, so some pairs are genuine overlap.
Those inflate the measured false-positive rate, which pushes the
chosen floor *up*. The bias is toward declining too often, which is
the safer direction for this particular failure.

## Result

6,814 null queries, 5,128 of which returned something before any
floor was applied.

| Floor | False-positive rate |
| --- | --- |
| 0.00 | 1.0000 |
| 0.10 | 0.1236 |
| 0.15 | 0.0515 |
| 0.20 | 0.0277 |
| 0.25 | 0.0132 |
| **0.27** | **0.0057** |
| 0.30 | 0.0051 |
| 0.40 | 0.0003 |

**The floor is 0.27.** It sits between the two numbers the skill had
been quoting from prose, which is a mild independent check on advice
that had never been measured.

## What it costs

Rescoring the frozen gold set's 170 labelled `same-behaviour` pairs
at 0.27 keeps **167**, a recall of **0.982**.

This figure is an observation, not an input. The floor was already
fixed when it was computed, and no value was compared against it.
Reported because the trade is the thing a reader needs: the floor
removes roughly 99.4% of spurious matches and 1.8% of true ones.

## Caveats

**A cross-corpus null is not the same as a within-repository null.**
Two functions in the same codebase share idioms, helpers, and house
style, so spurious overlap within one repository is probably higher
than between two. The floor may therefore be permissive in the case
that matters most. Measuring a within-repository null needs labels to
separate coincidence from real reuse, which is what made the
cross-corpus construction attractive in the first place.

**Django is absent.** Its sampling rule takes the whole subtree, so
no disjoint slice exists under the current rule and the hard-negative
corpus contributes nothing here.

**The gold recall figure inherits the gold set's pooling bias.** Those
170 positives were found by three generators, two of them lexical, so
they are the population a shingle comparison is most likely to keep.
Recall against reimplementations written in different words is not
measured by this number and is probably worse.

**Only the `similar` path is floored.** The packet ranker scores on a
different scale and no null distribution has been measured for it, so
`packet` still returns its best candidates regardless of score.
Inventing a threshold for an uncharacterised scale would be the
mistake this page exists to correct.

Reproduce with `make bench-floor CHECKOUTS=<dir>`. Committed at
[`benchmarks/similarity/floor.json`](../benchmarks/similarity/floor.json).
