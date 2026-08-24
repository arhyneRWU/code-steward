# Pre-registration: resolving `obj.method()` by unique name

**Status: written and committed before the measurement.** No such
resolution rule exists in the indexer yet.

## The change being proposed

Our indexer records `response.has_header(...)` as an unresolved
symbol row and never promotes it to a `CALLS` edge, because it cannot
prove what `response` is. The proposal: **if exactly one indexed unit
is named `has_header`, resolve the call to that unit.**

On Django that would convert 2,738 of 13,957 attribute-style
unresolved rows and move edge resolution from **22.5% to 31.7%**.

The motivation is [`context-cost.md`](context-cost.md), where an
external graph found 21 points more of the real caller set than we
did, and a spot check showed the missing callers were already sitting
in our own index under exactly this shape.

## The circularity this design exists to avoid

The obvious instrument is the answer key from the context-cost run:
every function whose body calls the target's name. **It cannot be
used here.** That key is name-based, and the rule under test is
name-based, and they are the *same rule*. Measuring one against the
other returns recall 1.0 by construction.

That would have been the fourth criterion in this project that cannot
fail. It is written down here because the previous three were found
by simulation, by a smoke test, and by publication respectively --
this one was caught before the design was written, which is the first
time that has happened.

**The instrument is therefore an oracle that does not work by name.**
Jedi performs static type inference and resolves an attribute access
to a definition. It agrees or disagrees with the proposed rule on
evidence the rule does not have access to.

## Population and sample

Every call site in Django that is **currently an unresolved
attribute-style row** and whose method name is **unique among indexed
unit names**: 2,738 of them.

**200 sampled in blake2b hash order**, excluding any whose resolved
target is one of the 200 targets spent by the context-cost run. Those
targets motivated this change, and a repair evaluated on the set that
motivated it is tuned rather than tested.

## Outcome classes, fixed now

For each sampled call site, Jedi is asked to resolve the attribute.

| Jedi resolves to | Class |
| --- | --- |
| The same unit the rule would pick | **confirmed** |
| A different location inside the corpus | **contradicted** |
| A definition outside the corpus -- stdlib, third party | **contradicted** |
| Nothing at all | **unverified** |

A definition outside the corpus counts against the rule, not as an
abstention. That is precisely the failure mode worth fearing: a call
to `x.close()` on a file handle, where `close` happens to be unique
among our own units, would have the rule confidently invent an edge
into our own code.

## A second instrument, added before the run

A five-site smoke test of the harness came back **four unverified**,
which would trip the inconclusive rule below on its own. Two jedi
configurations and both `goto` and `infer` were tried on three of
those sites; all six combinations resolved nothing. This is not a
misconfiguration. Type inference genuinely fails on the receivers
Django uses -- managers, descriptors, objects assembled at runtime --
and those are exactly the receivers this rule is aimed at.

An instrument that abstains on the population of interest cannot
decide the question. So a second one is fixed here, before the run:

**Hand adjudication of 25 sites drawn in hash order from the
jedi-unverified stratum.** For each, the enclosing function is read
and the receiver identified from the source: a parameter annotation,
an assignment, an obvious construction, a documented contract.

| What the source shows | Class |
| --- | --- |
| The receiver is one of our indexed types, and the unique unit is its method | **confirmed** |
| The receiver is a stdlib, third-party, or otherwise non-indexed type | **contradicted** |
| The source does not determine the receiver | **undetermined** |

Because the method name is unique across our index, the failure mode
is narrow and legible: the receiver being something we do not index.
That is a question the source usually answers.

**The bias here is real and unmitigated.** I proposed the rule and I
am judging it. The protocol is written before the sites are read, the
per-site judgements and reasons are committed so anyone can check
them, and the hand pass is **secondary** -- it cannot rescue a
primary that fails, only decide a primary that abstains. If the two
instruments disagree in direction, that disagreement is the result.

## Primary outcome and the decision rule

**Precision** = confirmed / (confirmed + contradicted).

| Condition | Decision |
| --- | --- |
| Precision >= 0.95 **and** one-sided 95% Wilson lower bound >= 0.90 | **Adopt the rule.** |
| Precision >= 0.95 but the bound falls short | Sample is too small to support it. Do not adopt on the point estimate. |
| Precision < 0.95 | **Reject**, or restrict to a narrower population and pre-register that separately. Do not tune the threshold to make the result pass. |
| Unverified > 25% of the sample | The primary abstains. The hand pass above decides, under the same 0.95 / 0.90 thresholds, or the result is **inconclusive** if it too returns more than 25% undetermined. |

The 0.95 floor is chosen to match how this project already treats
false positives elsewhere: the reuse floor of 0.27 was set at the
smallest value holding the false-positive rate at or under 1%. An
edge is a stronger claim than a suggestion, so the bar should not be
lower.

Recall is **not** a primary outcome, because the circularity above
means it cannot be measured honestly with this instrument. What is
reported instead is the count of edges added and the resolution
delta, as description rather than as evidence of benefit.

## What adoption would and would not license

- It would **not** be evidence that slices get better. That is a
  separate claim needing a separate measurement, on a fresh sample,
  and it must not reuse the context-cost targets either.
- It would **not** retire `trace --members-from`. A broader graph
  still resolves calls this rule cannot -- an ambiguous method name
  is exactly where type inference wins and name matching cannot.

## Interaction with the skill A/B, stated before either runs

[`skill-ab-run2.md`](skill-ab-run2.md) pre-registers a run whose
question file was generated against an index at **22.5% resolution**,
with its answer sets frozen inside that file.

If this rule lands first, the skill arm would answer against a better
index than the one the key was drawn from, which inflates that arm
for a reason unrelated to the skill. So, fixed now:

**Run 2 is pinned to an index built without this rule**, or its
questions are regenerated and the run re-pre-registered. It may not
simply be run against an improved index and reported against the old
key.

## Stopping rule

Run once, all 200. No re-sampling, no threshold adjustment after
seeing precision, no reclassifying a contradiction as unverified
because the disagreement looks defensible on inspection.

---

# Result: rejected

Run once, 200 call sites, Django. Everything above this line was
written before the run.

| Class | n |
| --- | --- |
| confirmed | 109 |
| contradicted | 28 |
| unverified | 63 |

**Precision 0.796** on the 137 sites the oracle could adjudicate, with
a one-sided 95% Wilson lower bound of **0.734**. The floor was 0.95
with a bound of 0.90. **The rule is rejected.**

## It fails in exactly the way the design predicted

The pre-registration named the failure mode before the run: *"a call
to `x.close()` on a file handle, where `close` happens to be unique
among our own units, would have the rule confidently invent an edge
into our own code."*

Twenty-six of the 28 contradictions are that, verbatim:

```text
django/db/models/sql/compiler.py:631   extend   -> builtins.pyi
django/utils/text.py:482               lower    -> builtins.pyi
django/core/handlers/wsgi.py:67        replace  -> builtins.pyi
django/forms/widgets.py:1238           insert   -> builtins.pyi
django/contrib/sessions/middleware.py:54  time  -> time.pyi
```

Django contains exactly one indexed unit named `extend`, so
`some_list.extend(...)` would have become an edge into it. The rule
does not know that `some_list` is a list, and that is the entire
problem: **uniqueness in our index says nothing about what the
receiver is.**

## Why the pre-registered hand pass was not run

The unverified rate is 0.315, which by the amended rule sends the
decision to the hand pass. It was not run, and the reason is
arithmetic rather than judgement.

The verifiable stratum is 68.5% of the sample at precision 0.796.
**Even if every one of the 63 unverified sites were correct**, whole
population precision could not exceed

```text
0.685 x 0.796  +  0.315 x 1.000  =  0.860
```

which is below the 0.95 floor. No outcome of the hand pass could
change the decision, so running 25 hand judgements whose result
cannot matter would have been ceremony, not rigour.

**This is a deviation from the pre-registration and is recorded as
one.** It also exposes a flaw in that document: the decision table
has two rows that both fire on this data -- "precision < 0.95" and
"unverified > 25%" -- and they point to different next steps. A
future table needs to say which condition is evaluated first.

## The restriction that suggests itself, and why it is not adopted here

Excluding builtin method names from the population gives 109/118 =
**0.924** on 169 sites.

**That is a post-hoc number and is not a result.** It was computed by
looking at which cases failed and removing them, which is how a
false positive is manufactured. It is recorded only because it points
at a v2 worth pre-registering separately: resolve only where the
unique name is not an attribute of any builtin type.

Even that would not clear the bar as measured. The nine
contradictions surviving the exclusion are stdlib and third-party
methods -- `inspect.getfullargspec`, `sqlite3.register_converter`,
`os.makedirs`, `time`, `email.message.attach` -- and 0.924 is still
short of 0.95 before any correction for its post-hoc selection. A v2
would need a real exclusion mechanism and a fresh sample, and these
200 sites are now spent.

## The corollary that matters more than the rejected rule

The [context-cost](context-cost.md) answer key is **name-based**: a
caller is any function whose body calls the target's name. This run
measured a name-based resolution rule at **0.796 precision** against
a type-inference oracle.

Those two facts together mean the context-cost key **cannot penalise
name-based false positives**, because it shares their mechanism. If
the broader graph in that comparison also resolves by name -- and its
edge counts are consistent with that -- then part of its +0.207
recall advantage is edges that would not survive the oracle used
here.

That does not overturn the context-cost result, and
`trace --members-from` remains the right seam: a caller list from a
better selector is still better, and the bundle is assembled from
whatever list it is given. But the size of that advantage is now in
question, it was not in question when it was published, and the next
measurement should be adjudicating **their** caller claims with the
oracle used here rather than with a key built the same way they work.
