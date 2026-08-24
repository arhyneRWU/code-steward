# Roadmap: what Code Steward should become

Written 2026-08-23. This is a direction document, not a record of
what exists. For what exists, read the README; for what was tried and
abandoned, read [`direction.md`](direction.md).

## The product is the skill

Code Steward is a **skill an agent invokes**. The CLI is the substrate
that skill drives, not the deliverable. That distinction has been
implicit and it has cost us: every number in this repository measures
a command, and none measures whether an agent following the skill
does better work.

One line, and everything below serves it:

> **Hand a model a small, complete-enough slice of a repository so it
> can act without reading the repository.**

Measured support: a cheap model given an assembled bundle scored
0.917 against blind labels with 30/30 on negatives, while a larger
model given a *ranked shortlist* was talked into a duplicate that was
not there on 33% of clean cases. Assembly beats ranking, and the
cheap model with a good bundle beat the expensive one with a bad one.

## The architecture we already have, named

Nobody designed this. It emerged, and naming it is most of the work
of planning what comes next:

    select targets  ->  assemble a slice  ->  run passes  ->  emit one bundle

| Layer | What exists today |
| --- | --- |
| **Selector** | a named unit; `--undocumented`; `--base` (changed files) |
| **Assembler** | `trace.build_slice` -- callers, callees, tests, call sites |
| **Pass** | source rendering; call-site annotation; `--dry` duplication |
| **Emit** | Markdown bundle, or JSON |

`--undocumented` and `--dry` look like two flags bolted onto `trace`.
They are not. One is a **selector**, the other is a **pass**, and
seeing that turns ad-hoc growth into something predictive:

- The drift detector died because it was **a selector that did not
  work** -- see the 2026-08-23 design record.
- Docstring fill lived because `doc_text == ""` is **a selector that
  cannot fail**.
- The test work in [#60](https://github.com/arhyneRWU/code-steward/issues/60)
  is **another pass**, not another subsystem.

Every future capability should be expressible as a selector, a pass,
or an emit. Anything that is not is probably a second product.

## What the skill should tell an agent

The current skill is organised around commands and around a workflow
whose first five steps are the weakest path we have. It should be
organised around **moments in the work**, each carrying its own
measured reliability.

| Moment | Command | How much to trust it |
| --- | --- | --- |
| **Before you write** | `similar --draft` | Weak. 0.460. One cheap attempt, then move on. |
| **Before you modify** | `trace <unit>` | Strong. The path, with call sites, at 4-10x compression. |
| **Across a path** | `trace --dry` | A report. Fires on ~53% of paths here, and the rate compounds with slice size. |
| **Before you commit** | `check` | Strong on copy-and-tidy, blind to reimplementation. |
| **When documenting** | `trace --undocumented` | Exact selector; the docstring itself is unverifiable. |

Three structural changes follow:

1. **Rename it.** `searching-before-implementing` names the thesis
   that measurement killed. Searching before implementing is worth
   one cheap attempt and no more; the tool is reliable on code that
   exists.
2. **Demote the ranking path to a footnote.** `packet` and `search`
   currently take three of seven workflow steps. Their Hit@1 loses to
   a plain keyword scan, and reuse evidence in the packet changed no
   verdicts (p = 0.549).
3. **Promote `trace`.** It is one line under "Other commands" at the
   bottom of a 303-line skill, and it is the thing every capability
   since has been built on.

## The gap that matters

Sort every number this project publishes by what it actually
describes:

| Number | Describes |
| --- | --- |
| alarm rate 63.8 / 50.8 / 31.3 / 14.3% | how often the tool **speaks** |
| compression 10.3x / 4.2x | how **small** the bundle is |
| call resolution 32.1% | how much the graph **sees** |
| nomination rates | how often a signal **fires** |
| **0.917 on blind DRY labels** | whether **anyone is better off** |

One row in five describes usefulness, and it rests on a single
experiment over 30 cases.

So when `check` fires on 63.8% of Airflow, **we do not know whether
those findings are right.** The same holds for `--dry` at 53%. The
documentation says so plainly, which is to this project's credit, and
it means the central claim is still unevidenced.

Reframing the product as a skill makes the right experiment obvious,
and it is a better experiment than labelling findings one at a time:

> **Give two agents the same tasks. One has the skill, one does not.
> Score the work blind.**

That is a paired test on one variable, which is this project's
standard, and it measures the thing the product actually is.

## Stages, each with an exit criterion

### Stage 0 -- make the skill describe the tool that exists **(done)**

Renamed `searching-before-implementing` to `code-steward`, because
the old name encoded a thesis that measurement killed twice and a
tool name cannot go stale the same way. Rewritten around moments in
the work rather than commands, opening with a reliability table.
`packet` retired as a command -- `packet.py` stays, since six
benchmark modules import it and those benchmarks are the record of
why the ranking flow was abandoned.

The open decision on `search` resolved as **keep, but stop it being
load-bearing**. Its job was never wrong -- grep returns a line, an
index returns a unit -- but its guarantee was "best eight, ranked, no
floor". `trace` now accepts a bare name or `path:line`, so the common
case is deterministic and `search` is only for when you cannot guess
the vocabulary at all.

`tests/test_cli_surface.py` pins the command list, so adding or
removing one is a deliberate act with a diff.

*Exit met: nine commands, one thesis, and the skill's own table now
tells a reader which answers to trust.*

### Stage 1 -- measure the skill, not the commands

The paired A/B above. Keep the existing discipline: blind scoring,
provenance stripped, negative result published either way.

*Exit met, and the number is null.* See
[`skill-ab.md`](skill-ab.md). Skill arm 0.984 mean F1, control 0.929,
paired difference +0.055 with a one-sided 95% lower bound of -0.099.
The pre-registered detectable effect was 0.20, so this does not show
the skill helping.

**The design could not answer the question, and that is the finding.**
At 0.929 the control nearly saturates: this repository is 4,400 lines
and an agent can just read it. The skill's claim is about
repositories too large to read, and a repository small enough to read
cannot test it. The next run needs Django or Home Assistant, harder
questions, one question per agent, and the sign test pre-registered
as primary -- most questions tie, and a mean difference is the wrong
instrument for that.

Recorded, and explicitly not the result: the arms differed on 5 of 20
questions and **all five favoured the skill**, one-sided sign-test p
= 0.031. Choosing that test after seeing 5/5 is how false positives
are made, so it is a direction to power the next run against, not a
finding.

### Stage 2 -- use it in anger for a week

On a real repository, locally. Nothing from a private repository is
ever committed or published here.

Instrumented, so the account is a record rather than a recollection:
`CODE_STEWARD_FIELD_LOG` appends one line per invocation to a local
file -- command, exit, duration, slice size, whether it came back
empty, which selector produced it. Off unless the variable is set,
and it never leaves the machine. The template and the publishing
rules are in [`stage-2-field-notes.md`](stage-2-field-notes.md).

*Exit: a written account of what it caught and what it wasted time
on. Both halves.* An account whose second half is empty has not met
this criterion.

### Stage 3 -- new passes, and only then

The test pass ([#60](https://github.com/arhyneRWU/code-steward/issues/60)),
budget-aware assembly ("the best 8 KB for this task" rather than a
hop count).

*Exit: each new pass ships with its own reliability number in the
skill's table.*

### Cross-cutting -- call resolution

32.1% of `CALLS` edges resolve to a unit. Every pass above the graph
is capped by that. Fixing the `src/` layout defect took `TESTED_BY`
on this repository's own source from 0 functions to 45 in one commit,
so there is likely more of that kind of win available.

## What it will never do

Kept explicit, because today demonstrated how much this saves.

- **Rank a shortlist.** Measured: a ranked shortlist is itself a
  suggestion, and an agent picking from one picks wrongly a third of
  the time. Assemble a complete slice instead.
- **Predict before the code exists.** Two reframes died here. A task
  sentence scores 0.459, an agent's sketch 0.460, the real body
  1.000.
- **Write to source.** Proposals only. The one output that cannot be
  scored must not be applied automatically.
- **Embed a model client.** The agent in the loop is the model. No
  API key, and nothing leaves the machine.
- **Rebuild an off-the-shelf tool without searching PyPI first.**
  This has cost us twice: `jscpd` on similarity, `docvet` on
  docstring staleness.

## Open decisions

These need a call and do not have one yet.

1. ~~Do `packet` and `search` stay?~~ **Resolved in Stage 0.**
   `packet` is retired; `search` stays as the "I cannot guess the
   vocabulary" path, no longer load-bearing.
2. ~~What is the skill called?~~ **Resolved:** `code-steward`.
3. **Is the CLI a public interface or a private substrate?** Still
   open. There are no external users -- 0 stars, 0 forks, every issue
   and PR self-authored -- so if the skill is the product, command
   stability matters much less and consolidation gets cheaper.
