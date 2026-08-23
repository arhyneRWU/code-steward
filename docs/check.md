# `check` — the post-write duplication pass

`code-steward check` compares the functions you changed against the
functions already in the repository, and says which ones you have
written twice.

## Why this command and not the other one

Every measurement in this project points at the same thing: the
comparison is excellent, and how much it is worth depends entirely on
how much of the function exists when you run it.

| What is compared | Duplicate found |
| --- | --- |
| A task sentence, through the packet ranker | 0.459 |
| A body an agent drafted from a name and docstring | 0.460 |
| **The real body** | **1.000** |

Those are from [`verdict.md`](verdict.md), on the same held-out cases.
The first two are the pre-write workflows this project spent most of
its life on. The third is what you have the moment you finish typing.

So the useful point in the cycle is not before the code is written. It
is after it is written and before it is kept -- late enough that a
real body exists, early enough that deleting it is still cheap.

## Using it

```bash
code-steward check                      # everything this branch changes
code-steward check path/to/file.py      # specific files
code-steward check --base develop       # diff against another branch
code-steward check --fail-on-overlap    # exit 1, for a hook or CI
code-steward check --json               # structured output
```

It reports the changed function, what it overlaps, and where:

```text
src/billing/refunds.py:42  build_refund_payload
    0.81  src.billing.charges::build_charge_payload  (src/billing/charges.py:88)

1 of 12 changed function(s) overlap existing code
```

When nothing overlaps it says so, with the denominator:

```text
12 changed function(s) checked, none overlap existing code
```

The denominator is not decoration. A silent result means nothing
unless you know whether it looked at twelve functions or none.

## What it will and will not catch

**It catches copy-and-tidy. It misses reimplementation.** This is the
same blind spot the comparison has always had, and `check` inherits it
whole. Measured against one fixture function: 0.941 with the function
renamed, 0.535 with the whole signature renamed, **0.015 once every
local variable was renamed too**.

Concretely, on this repository's own source: a copy of an internal
helper with only the function name changed scored **0.98** and was
reported. A genuine reimplementation of the same helper -- same
algorithm, every identifier different -- scored below the floor and
was not reported at all.

That is a real limit, and it points the command at a real population.
Copy-paste is the duplication people actually commit; reimplementation
is rarer and needs a different technique to find.

## The floor

Overlaps below **0.27** are discarded and not shown. The floor was
chosen on a held-out null distribution against a pre-registered 1%
false-positive budget; see [`floor.md`](floor.md).

This is what lets an empty result be an assertion rather than a shrug.
It is also not free: measured on realistic agent drafts, the floor
drops 12 of the 35 duplicates that were found at all. On real bodies
the cost is far lower, because a real body scores much higher than a
sketch of one -- which is the other reason this command runs where it
does.

`--floor 0.0` shows everything, for when you want to see what was
suppressed. That is a debugging move, not a normal one.

## How often it fires, and why that is about your repository

This is the number that decides whether `check` is worth leaving
switched on, and it is **a property of the codebase, not of the
tool.** Measured by treating every function as though it had just
been written and comparing it against the rest of its own repository,
at the shipped 0.27 floor:

| Codebase | Functions | Overlap something |
| --- | --- | --- |
| Airflow providers | 5,638 | **63.3%** |
| Home Assistant integrations | 1,176 | **45.5%** |
| Django | 5,541 | **29.7%** |
| Code Steward, `src/` only | 147 | **14.3%** |

Raising the floor moves it but does not remove it — Airflow is still
40% at 0.50.

**These are alarm rates, not error rates.** Nothing in that table is
labelled, so an alarm cannot be sorted into right and wrong. Airflow's
providers contain enormous genuine duplication by design: near
identical operators and hooks, one set per vendor. The tool is
probably correct most of those 63% of times, and it is *still*
unusable as a blocking gate there. Being right and being useful are
different properties.

Django is the corpus deliberately chosen as the low-duplication hard
negative, and it is still 29.7%. So this is not only a
template-repository problem.

### What follows from it

**Do not switch on `--fail-on-overlap` without measuring first.**

```bash
code-steward check --rate
```

reports the same figure for your repository. If it comes back near
15%, `check` will be quiet enough to gate on. Near 50%, it will not
be, and the honest use is as a report you read rather than a build
you block.

The default is deliberately report-and-exit-0 for this reason.
`--fail-on-overlap` exists, and it is opt-in, and this section is why.

### What would improve it

Reporting only the overlaps a change *introduces*, rather than every
overlap a changed function has. A function that already duplicated
something before you touched it is not your finding, and on
duplication-heavy repositories that distinction would remove most of
the noise. Not built, and the obvious next thing.

## Honest limits

- **Python only.** Nothing else is indexed.
- **The index must be current.** `check` compares against what
  `build` last saw. A stale index misses recent code, and a stale
  index is silent about being stale.
- **A function is excluded from its own comparison by unit ID**, so
  editing an already-indexed function does not match its previous
  revision. Rename the function *and* the file and that protection
  stops applying; you will see your own old code as a duplicate.
- **Functions under five lines are skipped** entirely, along with
  anything under twenty normalised tokens. Two identical three-line
  properties are not a finding worth making.
- **An overlap is not a verdict.** It says two functions share text.
  Whether the right answer is REUSE, EXTEND, REFACTOR, or leaving
  both alone needs someone to read them.
