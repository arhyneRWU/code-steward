# Does the skill help? First measurement

Stage 1 of [`roadmap.md`](roadmap.md). Every other number in this
project measures a command; this one measures the product, which is
the skill an agent follows.

**Result: null by the pre-registered criterion.** The skill arm
scored higher, and the difference is a quarter of the smallest one
this design can distinguish from noise.

## Design

Two arms answered the same 20 questions about this repository. Arm
**skill** had the `code-steward` skill and CLI. Arm **control** had
Grep, Glob and Read, and was instructed not to touch the CLI, the
index, or the skill file.

Questions are graph-answerable, so scoring needs no rubric and no
labeller:

- *"Which functions run as a result of calling X?"* -- callee closure
  at depth 2.
- *"Which functions would be affected if X changed?"* -- direct
  callers.

Answers are sets of unit IDs, scored by F1 against the `CALLS` edges.
Targets were selected in hash order, so the set could not be chosen
by looking at the answers. Ten questions per agent, two agents per
arm.

**The criterion was simulated before it was fixed**, which the
previous pre-registered criterion in this project was not:

| n | true F1 gap | power |
| --- | --- | --- |
| 12 | 0.20 | 0.77 |
| **20** | **0.20** | **0.91** |
| 20 | 0.10 | 0.45 |
| 30 | 0.20 | 0.98 |

So n = 20 detects a 0.20 gap and cannot reliably detect 0.10.

## Result

| Arm | mean F1 | mean recall | perfect | outside the key | tool calls | tokens |
| --- | --- | --- | --- | --- | --- | --- |
| skill | **0.984** | 0.984 | 17 / 20 | 1 | **28** | **93,599** |
| control | **0.929** | 0.929 | 12 / 20 | 7 | 36 | 122,897 |

Mean paired difference **+0.055** in the skill's favour. The skill
arm also used **22% fewer tool calls and 24% fewer tokens**, measured
by the harness rather than self-reported. Cost was not part of the
original analysis and should have been: it is half the product's
claim.

**The conclusion is inconclusive, and the first version of this page
reached it by the wrong route.** Three corrections, all found after
the fact:

1. **The arms were compared in the wrong direction.** The scorer
   ordered them alphabetically and computed `control - skill`, so the
   published bound of `-0.099` was the negative of the intended
   statistic. In the correct direction the F1 difference is
   **+0.0552** with a one-sided 95% lower bound of **+0.0169** --
   which by the criterion as literally written means the skill
   *helps*.

2. **That criterion cannot fail on this data, so it is not
   evidence.** The 20 paired differences are 15 zeros and 5
   positives, with **no negative values at all**. Every bootstrap
   resample therefore has a mean at or above zero and the one-sided
   lower bound is positive by construction. A paired sign-flip
   permutation test, which models the actual null, gives **p =
   0.126**. Not significant.

3. **The tie rate was 0.85**, not the continuous spread the power
   simulation assumed. Seventeen of twenty questions were answered
   identically, so the effective sample was three, and the quoted
   "91% power at a 0.20 gap" never applied to this data.

So the honest reading is unchanged -- the skill is not shown to help
-- but the earlier reasoning for it was wrong in both sign and
instrument.

## Why the design could not answer the question

**The control was too good.** At 0.929, grep-and-read nearly
saturates the task. This repository is 4,400 lines of source; an
agent can simply read the files. The skill's claim is about
repositories too large to read, and a repository small enough to read
cannot test it.

The arms agreed exactly on the first batch -- 0.968 against 0.968,
zero differences across ten questions. Every difference came from the
second batch, whose answers were slightly larger on average (5.0
units against 4.0).

A ceiling this high leaves almost no room for an effect to appear in,
which is a flaw in the task, not a finding about the tool.

## A post-hoc observation, labelled as one

The arms differed on 5 of 20 questions. **All five favoured the
skill; none favoured the control.** A sign test on those discordant
pairs gives a one-sided p of 0.031.

**This is not the result.** It was not pre-registered, and reaching
for a sign test *after* seeing five out of five in one direction is
precisely how a false positive gets manufactured. It is recorded
because suppressing it would be equally dishonest, and because it
suggests the direction worth powering a future run to detect.

The other suggestive detail: the control named **7 units absent from
the answer key against the skill's 1.** That has two readings and
this design cannot separate them -- the control may be finding real
callers the 32.6%-resolved graph missed, or it may be guessing.

## What the next run must change

1. **A repository too large to read.** Django or Home Assistant, not
   this one. The control's 0.929 is the whole problem.
2. **Harder questions.** Deeper closures, or paths that cross module
   boundaries, where reading files is genuinely expensive.
3. **More questions, and one per agent.** Ten questions in one
   context makes them non-independent, which the bootstrap assumes
   away.
4. **A paired permutation test as primary, on recall.** Simulation
   put the sign test and the permutation test within a point or two
   of each other at every tie rate tried, so the choice was made on
   the fact that the permutation test keeps magnitude. The bootstrap
   lower bound is dropped outright: it cannot fail on a sample with
   no negative values.
5. **Recall, not F1.** The key was validated against an independent
   AST scan on six `impact` questions and was a **strict subset** of
   the callers that genuinely exist, every time. It is a lower bound,
   so recall against it is interpretable and precision is not -- a
   correct caller the graph missed counts *against* precision, which
   is the bias this page claimed to have guarded against and had not.
   `benchmarks/skill/verify.py` now adjudicates claims outside the
   key against the source rather than assuming they are wrong.
6. **Cost as a co-primary outcome**, measured by the harness.

## Caveats that travel with these numbers

- Ground truth is the same graph the skill exposes, so the skill arm
  is scored against its own source. Edge resolution is **32.6%**.
- Units named outside the key are counted, not punished, for that
  reason.
- Questions within a batch share one agent context and are not
  independent.
- One repository, one model, one prompt phrasing. Two arms answered
  identically on half the questions, which is as much a statement
  about the questions as about the arms.
