# Direction

This page records what the project set out to do, what measurement
changed, and what it is doing now. It exists so that old framing does
not keep steering the work by default. Nothing here is deleted
history -- the earlier goal is stated plainly, because knowing why it
was abandoned is what stops it coming back.

## Where this started

The original claim was:

> Decide REUSE / EXTEND / REFACTOR **before the code is written**.

Operationally that meant: a developer or agent types a sentence
describing what they are about to build, the ranker finds the
existing units it would overlap, and a packet of stable code-unit IDs
goes to a reviewer, which decides.

Three assumptions came with it, none of them stated as assumptions at
the time:

1. A task sentence is enough to find the existing code.
2. More evidence in the packet produces better decisions.
3. Recall is the binding constraint -- the failure to fix is the
   duplicate that never arrives.

## What the measurements did to that

**A task sentence is not enough — but the margin was overstated.** On
250 held-out functions the packet ranker surfaced the labelled
duplicate 0.459 of the time, against 0.994 for comparing a drafted
body. That 0.994 compared the *real removed body*, and has since been
remeasured with bodies an agent actually wrote from a name, signature
and docstring: **0.460** end to end, floor applied, counting drafts
too small to compare as the failures they are.

So the 2:1 margin this page was originally built on is not there. What
remains is a precision difference rather than a recall one: the draft
path reaches 0.460 while returning nothing on most non-matches, and
the packet path reaches 0.459 by returning eight candidates every
time. The reviewer measurement says precision is what costs verdicts,
so this is still a real difference — it is just a much smaller and
less certain claim than the one that motivated the reframe. See
[`verdict.md`](verdict.md).

**More evidence did not produce better decisions.** Attaching
near-duplicate evidence to every candidate raised the surfaced rate
from 0.459 to 0.654 -- and when sixty of those cases were put to an
actual reviewer agent, paired, the verdict accuracy went 0.683 to
0.733 with eleven discordant pairs, 4 against 7, exact two-sided
**p = 0.549**. Null. The extra evidence cost 58% more bytes and
bought nothing measurable. Assumption 2 is falsified as far as this
can measure it.

**Recall was not the binding constraint.** In the same run, on a
third of the negative cases -- where the correct answer was to write
the function -- the reviewer was talked into REUSE or EXTEND anyway.
Retrieval always returns its eight best candidates; a reviewer handed
eight plausible functions picks one. The system has no way to say
*none of these*. That failure is more expensive than the one the
project was built to prevent: a missed duplicate costs some
redundancy, a wrong reuse wires a caller to code that does not do the
job.

## Where it is going

**The entry point is a draft, not a sentence** — held with less
confidence than when this page was written, and for a different
reason. See the remeasurement above.

> Decide REUSE / EXTEND / REFACTOR / NEW **on a drafted change,
> before it is kept.**

An agent sketches the function it intends to write, that sketch is
compared against the index, and the verdict comes back with the
existing units it overlaps. "Before it is written" was the
aspiration; "before it is kept" is what the numbers support and what
is honestly deliverable. The draft is cheap -- the agent was going to
write the code anyway -- and it can support an answer the sentence
path cannot: that nothing in the repository fits.

**Declining is a first-class answer.** The reviewer agent already has
a declining verdict, `NO_CANDIDATE`, so the gap is not a missing
option. It is two other things.

First, **the packet itself cannot decline.** `similar` has a result
limit and no score floor, so retrieval always returns its eight best
candidates however weak they are. The reviewer is never shown an
empty result, because an empty result cannot be produced.

Second, **the declining verdict is written as a non-answer.**
`NO_CANDIDATE` is defined as "a report that *you did not find*
something, not a finding that nothing exists". That hedge is
epistemically honest and it makes declining feel like a failure to
complete the task, which is the wrong pressure when declining is
correct. Between the two, a reviewer handed eight plausible functions
picks one, which is what the measurement shows it doing on a third of
negative cases.

So the work is a score floor, a packet that can legitimately return
zero candidates, and a decision contract where writing new code is a
normal outcome rather than an admission. The measurement that matters
is verdict accuracy *including correct abstention*, not surfaced
rate. Surfaced rate can be driven to 1.0 by returning everything,
which is roughly what the current packet does.

**What carries over unchanged.** Stable code-unit IDs, the packet as
the interface an agent acts on, and the byte compression -- those are
infrastructure and none of the above touches them. The similarity
engine is the part that won, and it is the part the new frame leans
on hardest. The measurement discipline carries over too: every claim
on these pages is against a control, blind where blinding is
possible, with negative results kept.

**What is demoted rather than deleted.** The sentence-only packet
still exists and is still measured. It is the fallback for when there
is no draft to compare -- exploring an unfamiliar repository, or
answering "where does this already happen". It is no longer the
headline path, and its numbers should not be quoted as the product's
numbers.

## What this changes about the work

- Stop adding signal to the packet. Two of the last three changes did
  that and the verdict did not move.
- The score floor is promoted from a tuning question to the main line
  of work, because it is the thing standing between the tool and its
  most expensive failure.
- New features are judged against verdict accuracy with abstention,
  not against surfaced rate or Hit@K.
- The undocumented half of every corpus is still excluded from the
  verdict benchmark and is still the population the ranker is worst
  at. Draft-and-compare does not read docstrings, so the new frame
  may simply not have this problem -- that is a testable claim and it
  has not been tested.

## What was never true

Worth keeping visible, because it was believed for a while: the
method here is not novel. Five-token shingle comparison is textbook,
and jscpd -- an off-the-shelf tool -- placed second on this project's
own benchmark. What is unusual is the *placement*: running the
comparison against stable code-unit IDs, before the change is kept,
and handing the result to an agent as a packet rather than to a human
as a report.
