# Run 2 pre-registration: the skill on a repository too large to read

**Status: written and committed before the run. Nothing has been
run against this design.** That sentence is the point of the page.
Run 1 fixed its criterion after seeing data twice -- once by
comparing the arms in the wrong direction and once by choosing a
bound that could not fail -- and both times the mistake was invisible
until someone simulated the criterion. So this run states everything
first, including the ways it is allowed to come out.

Run 1 and its three corrections are in [`skill-ab.md`](skill-ab.md).

## The question

Does an agent following the `code-steward` skill answer call-graph
questions about a large repository more completely than an agent with
Grep, Glob and Read?

Run 1 could not answer it because the control scored 0.929 on a
4,400-line repository -- an agent can simply read that. The claim is
about repositories too large to read, so this run uses one.

## Fixed before the run

### Corpus

Django at commit `fe0a859f537d4238cf49fca39073513206f83122`, the
public pin already recorded in `benchmarks/similarity/corpus.py`.
11,612 indexed units, **22.5% `CALLS` edge resolution**, which is
reported beside every score as it was in run 1. The checkout and the
index stay local; only unit IDs are ever committed. No private
repository is involved at any point.

### Questions

Regenerated with `benchmarks/skill/questions.py`, changing two
parameters and nothing else:

| Parameter | Run 1 | Run 2 | Why |
| --- | --- | --- | --- |
| `MIN_ANSWER` | 2 | **4** | 19 of the 30 Django questions generated under the old floor had two-unit answers. A two-unit answer is a coin flip dressed as a question. |
| `limit` | 15 | **40** | See the power table. |

Everything else stays: targets in blake2b hash order so the set
cannot be picked by looking at the answers, `calls` at depth 2 and
`impact` at depth 1, `MAX_ANSWER` 12.

**n = 40.** One question per agent, 40 agents per arm, 80 runs. Run 1
put ten questions in one context, which makes them non-independent
and the paired test is not entitled to assume that away.

The generated set is committed **before** the arms run, as
`benchmarks/skill/questions_run2_django.json`: 40 questions, 30
`calls` and 10 `impact`, answer sizes 4 to 12 with a median of 6.

### Arms

- **skill** -- the `code-steward` skill and CLI, against a
  pre-built index.
- **control** -- Grep, Glob and Read; explicitly instructed not to
  touch the CLI, the index, or the skill file.

Same model, same phrasing, same question text. Answers are sets of
unit IDs. Scoring is mechanical: no rubric, no labeller, and the
scorer never sees which arm produced a file.

### Primary outcome

**Recall against the answer key**, arm `skill` minus arm `control`,
paired per question.

Recall, not F1, because the key is a **lower bound**: built from the
22.5% of edges the graph resolves, and validated on six `impact`
questions against an independent AST scan, where it was a strict
subset of the callers that genuinely exist every time. A correct
caller the graph missed would count *against* precision, so precision
is not interpretable here and F1 inherits that. Run 1 claimed to have
guarded against this and had not.

Claims outside the key are adjudicated by
`benchmarks/skill/verify.py` against the source -- confirmed,
or reported unverified. Never silently counted wrong.

### Primary test

One-sided paired sign-flip permutation test on the recall
differences, `permutation_p()` in `benchmarks/skill/score.py`, at
**alpha = 0.05**. Exact, distribution-free, and it keeps the
magnitude of a difference instead of discarding it -- which the sign
test does not.

The bootstrap lower bound run 1 used is **dropped outright.** On a
sample with no negative values it is positive by construction, which
makes it a formality rather than a test.

### Co-primary outcome: cost

Tool calls and tokens per question, taken from the harness rather
than self-reported, reported per arm with a paired permutation test
on the same terms. Run 1 found 22% fewer tool calls and 24% fewer
tokens in the skill arm and treated it as an afterthought. Half the
product's claim is that it is cheaper; a run that measures only
accuracy measures half the product.

## Power, simulated before the criterion was fixed

`benchmarks/skill/power.py`, 400 trials per cell, seed 7.
Discordant differences drawn uniform on
[0.10, 0.50]; `p_up` is the probability that a discordant pair
favours the skill, so `p_up = 0.50` is the null.

| n | tie rate | p_up | power |
| --- | --- | --- | --- |
| 30 | 0.50 | 0.50 | 0.04 |
| 30 | 0.50 | 0.70 | 0.43 |
| 30 | 0.50 | 0.85 | 0.88 |
| 30 | 0.70 | 0.70 | 0.24 |
| **40** | **0.50** | **0.50** | **0.06** |
| **40** | **0.50** | **0.70** | **0.50** |
| **40** | **0.50** | **0.85** | **0.92** |
| **40** | **0.70** | **0.70** | **0.33** |
| 40 | 0.70 | 0.85 | 0.81 |
| 60 | 0.70 | 0.70 | 0.47 |

Two things this table says, both of which must survive into the
write-up:

1. **The criterion can fail.** At `p_up = 0.50` it fires about 5% of
   the time, which is what alpha means. Run 1's bound fired 100% of
   the time on its data.
2. **A modest effect is out of reach.** At a 0.70 tie rate and
   `p_up = 0.70`, n = 40 has 33% power and n = 60 has 47%. If the
   run comes back null with a high tie rate, that is **inconclusive,
   not a kill**, and it will be reported in those words.

n = 40 is chosen as the largest run worth its cost, not as the n that
reaches 80% power. It does not reach 80% power against a modest
effect at a high tie rate, and no feasible n does.

## How this run is allowed to come out

Stated now, so no reading gets invented later.

| Outcome | Conclusion |
| --- | --- |
| p < 0.05, mean difference positive | The skill helps on a repository too large to read. Reported as the result. |
| p >= 0.05, **tie rate < 0.50** | Powered and null. Evidence against an effect of the simulated size, reported as such. |
| p >= 0.05, **tie rate >= 0.50** | **Inconclusive.** The questions did not discriminate. A design failure, reported as a design failure. |
| p < 0.05, mean difference negative | Cannot occur: the test is one-sided. A negative mean difference is reported as the skill not helping. |
| Control mean recall > 0.90 | The ceiling problem is not fixed. The accuracy comparison is void regardless of p, and only the cost comparison stands. |

## Stopping rule

The run happens **once**. No re-running an arm, no regenerating
questions after seeing a score, no adding questions to reach
significance, no swapping the test.

If a bug is found in the harness after the run, the fix and the
re-run are both disclosed, and the original numbers stay on the page
next to the corrected ones -- the way run 1's wrong direction is
still printed in `skill-ab.md`.

Anything computed after seeing the data is labelled a post-hoc
observation and is not the result. Run 1's five-for-five sign test
is the template: recorded, and explicitly not the finding.

## What is not being claimed

- Ground truth is still the graph the skill exposes, so the skill arm
  is scored partly against its own source. 22.5% resolution.
- One repository, one model, one prompt phrasing.
- Django is Python-only and library-shaped. Nothing here generalises
  to a service, a monorepo, or another language.
