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

| Arm | mean F1 | perfect answers | named outside the key |
| --- | --- | --- | --- |
| skill | **0.984** | 17 / 20 | 1 |
| control | **0.929** | 12 / 20 | 7 |

Mean paired difference **+0.055** in the skill's favour. One-sided
95% bootstrap lower bound **-0.099**, which does not exclude zero.

**By the pre-registered criterion the skill is not shown to help.**
The observed gap is roughly a quarter of the smallest detectable one.

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
4. **Pre-register the sign test as the primary measure**, not the
   mean difference. Most questions tie, and a test built for
   discordant pairs has far more power here than a mean. Deciding
   that now, before the next run, is the only way it counts.

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
