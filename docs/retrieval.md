# Retrieval architecture

Code Steward uses a two-stage deterministic retrieval pipeline before any model reviews implementation bodies.

```text
coding intent
  |
  v
baseline metadata scoring
  |
  v
narrow weighted query expansion
  |
  v
ranked candidate pool
  |
  v
metadata similarity cap
  |
  v
compact reviewer packet
```

## Stable interfaces

`code_steward.search.search_units` remains the low-level lexical and typed scoring primitive. It is intentionally separate from the production policy so the original benchmark baseline remains measurable.

`code_steward.retrieval.rank_units` adds deterministic query expansion while preserving the baseline score as the primary signal. Expanded queries can add only a weighted fraction of a positive score improvement.

`code_steward.retrieval.select_review_candidates` removes near-duplicate candidates from the requested top review window using only metadata already present in the index.

`code_steward.retrieval.retrieve_units` composes ranking and selection for context-facing reviewer packets.

The CLI `search` command uses `rank_units` because it is an exploratory ranking surface. The CLI `packet` command uses `retrieve_units` because its purpose is to minimize reviewer context.

## Query expansion policy

The first production policy includes only two deterministic sources supported by the frozen retrieval benchmark:

- abbreviations such as `repo` to `repository`
- curated programming relations such as `save` to `persist` or `write`

The original query always remains the primary evidence. An expanded query can only contribute a conservative bonus based on how much it improves a candidate over the original score.

Broader concept aliases are not included in the first production policy. In the controlled experiment they improved ranking slightly but increased the absolute number of known false-similarity traps.

This is not intended to become a general English thesaurus.

## Candidate compression

The reviewer selector compares:

- name
- qualified name
- purpose or first docstring line
- concepts
- signature

The current similarity score is 85% semantic metadata overlap and 15% signature overlap. Candidates at or above the tested similarity threshold are treated as redundant within the requested top review window.

The selector does not refill skipped slots. A request for eight candidates means at most eight candidates. Returning fewer candidates is intentional when the omitted slots would contain metadata-near-duplicates.

## Evidence for the first policy

The frozen Benchmark v1 comparison produced:

| Strategy | Hit / recall @ K | MRR | Absolute traps | Absolute redundant | Mean candidates |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 91.7% | 0.651 | 6 | 4 | 5.33 |
| Alias expansion | 100% | 0.746 | 6 | 4 | 5.33 |
| Similarity cap | 91.7% | 0.658 | 6 | 0 | 4.42 |
| Combined | 100% | 0.753 | 6 | 0 | 4.42 |

The combined pipeline also reduced the mean metadata packet by about 15.7% while keeping the absolute known-trap count unchanged.

These results justify the first production policy, but they do not settle future retrieval architecture. The research branches remain evidence and are not production dependencies.

## Deliberate limits

The first policy does not use:

- WordNet or a general thesaurus
- embeddings or a vector database
- model-generated aliases
- a learned project dictionary
- benchmark gold labels during retrieval
- a function call graph
- MMR reranking

The current Python index still does not capture ordinary function-call edges. Future structural retrieval should add and evaluate those relationships explicitly rather than infer that they already exist.

## Future changes

Any broader alias source, structural signal, graph relation, or semantic retriever should be evaluated against the same frozen benchmark before replacing or extending the default policy. Context cost, false similarity, and redundant candidates remain first-class metrics alongside recall and ranking quality.

## Structural retrieval verdict: one-hop CALLS

The `CALLS` extractor landed so that structural retrieval could be
measured rather than assumed. It has now been measured on the pinned
`psf/requests` target at commit `8f8b212d`, scope `src/requests`
(19 files, 300 units, 219 resolved `CALLS` edges).

Production `retrieve_units()` with no structural signal:

| Metric | Baseline |
| --- | ---: |
| Hit@1 | 40.00% |
| Hit@3 | 53.33% |
| Hit@5 | 66.67% |
| Hit@K | 73.33% |
| MRR | 0.500 |
| Mean packet bytes | 4104.3 |

One-hop `CALLS` reranking, fusing
`max(lexical, sqrt(lexical * strongest_anchor))`:

| Direction | Hit@1 | Hit@3 | Hit@8 | MRR | Mean packet bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| outgoing | 40.00% | 53.33% | 73.33% | 0.500 | 4256.9 |
| incoming | 40.00% | 53.33% | 73.33% | 0.493 | 4200.5 |
| union | 40.00% | 53.33% | 73.33% | 0.493 | 4159.1 |

**No hit metric moved in any direction. MRR was flat at best and
regressed in two of three directions. Packet bytes rose in all three.**

One-hop `CALLS` reranking is therefore not adopted, and the production
policy continues to use no call graph.

### What the reachability probe does and does not show

The companion probe reports that 3 of the 4 baseline misses are within
one resolved `CALLS` hop, implying a 93.33% ceiling if an oracle
selected the right neighbour. That ceiling is not evidence for
adoption. The mean one-hop union for a miss is 15.75 units, so
capturing it requires admitting roughly sixteen extra candidates per
miss into a packet whose whole purpose is to stay small. The tested
fusion converted none of that reachability into a single additional
hit.

### Caveat on resolution rate

Only 219 of 790 extracted edges (27.72%) resolve to indexed units; the
rest remain unresolved symbols. This result therefore rejects the
tested fusion at the current resolution rate. It does not prove that
structural retrieval is worthless at a materially higher resolution
rate. Any future attempt should first raise resolution and say so
explicitly, rather than re-testing the same fusion.

### Consequence for external graph integration

Code Steward's own `CALLS` edges are extracted conservatively, verified
against the index, and carry per-edge resolution provenance. They do
not improve retrieval. Importing a second, less careful source of the
same edge type cannot be justified on retrieval grounds, and the case
for an external structural graph must rest on some capability other
than ranking.

### Fixture benchmark versus real repository

Frozen Benchmark v1 reports Hit@K 100% and MRR 0.753 on the synthetic
fixture. The same production pipeline scores Hit@K 73.33% and MRR
0.500 on Requests. The fixture documents 19 of 20 units and uses
queries averaging under four words; real code does neither. Benchmark
v1 remains valid as a regression guard against itself, but its
absolute numbers should not be read as retrieval quality on real
repositories.

## Docstring bodies as a scoring input

`_purpose()` stores the first docstring line, truncated at 240
characters, and that value is emitted into reviewer packets. Until
now it was also the only documentation the scorer ever saw, so every
description paragraph, parameter note, and caveat below the summary
line was discarded before ranking.

`doc_text` now stores the whole docstring, whitespace collapsed and
capped at 4000 characters. It is indexed and scored; it is never
emitted. `purpose` remains the short summary the packet carries, so
richer scoring costs no packet bytes.

### Take the better of summary and body, not the body

The first attempt scored the body in place of the summary and made
things worse: real-repository Hit@K fell from 73.33% to 66.67%.

The cause is specific. `cookiejar_from_dict` has the summary
"Returns a CookieJar from a key/value dictionary", which almost
exactly matches an intent asking for a helper that converts a cookie
dictionary into a `CookieJar`. Its full docstring adds 293 characters
of parameter description that the intent does not mention, so
scoring the body alone diluted a near-perfect summary match and
pushed the gold unit out of the packet entirely.

The production policy therefore scores
`max(summary, body)`. A body match can only ever raise a unit's
score, and a strong summary can no longer be diluted by its own
documentation.

| Metric | Baseline | Body replaces summary | Better of the two |
| --- | ---: | ---: | ---: |
| Hit@1 | 40.00% | 40.00% | **46.67%** |
| Hit@3 | 53.33% | 66.67% | 60.00% |
| Hit@5 | 66.67% | 66.67% | 66.67% |
| Hit@K | 73.33% | 66.67% | 73.33% |
| MRR | 0.500 | 0.511 | **0.550** |
| Mean packet bytes | 4104.3 | 4055.3 | **4039.1** |

Measured on the pinned `psf/requests` target. The final policy
improves Hit@1 and MRR, regresses nothing, and slightly reduces
packet size.

### Neither fixture benchmark can see this

Frozen v1 and the v2 matrix are byte-identical before and after,
because every fixture docstring is a single line, so `doc_text`
equals `purpose` for every fixture unit. This change was measurable
only against `benchmarks/real_repo`. See the fourth validity gap in
`benchmarks/retrieval/README.md`.

## The text-search control arm

Every result above compares Code Steward against Code Steward. The
value claim -- that structured retrieval beats what an agent already
gets from text search -- had never been measured, so
`benchmarks/real_repo/grep_baseline.py` measures it.

The control arm derives search terms from the query by dropping
stopwords, runs a case-insensitive fixed-string scan per term over
every `.py` file, and ranks units by distinct term coverage then hit
density. The scan replicates `rg --ignore-case --fixed-strings --glob
'*.py'` and was verified to return byte-identical candidate lists and
summary metrics; it is implemented in Python so the control arm has no
system dependency and keeps running in CI. It imports no
Code Steward scoring code. It reads unit line spans from the index
only to attribute a matched line to an enclosing unit, which is
segmentation rather than ranking.

### Result

On the same 15 Requests cases, at the same K:

| Metric | Production retrieval | Docstring bodies (PR #40) | Text-search control |
| --- | --- | --- | --- |
| Hit@1 | 40.00% | 46.67% | **53.33%** |
| Hit@3 | 53.33% | 60.00% | **80.00%** |
| Hit@5 | 66.67% | 66.67% | **80.00%** |
| Hit@K | 73.33% | 73.33% | **86.67%** |
| MRR | 0.500 | 0.550 | **0.667** |
| Known trap rate | 2.63% | -- | **1.67%** |
| Bytes handed to the reviewer | **4104** | -- | 21107 |

Plain keyword search beats the production ranker on every retrieval
metric measured. This is the central negative result for the current
scoring design and it should not be softened.

### Where the gap comes from

The four cases production retrieval missed entirely -- `prepare_url`,
`resolve_redirects`, `raise_for_status`, and `build_digest_header` --
the control arm ranked 1, 1, 3, and 2. All four are long,
multi-concept units whose query terms appear in the body: identifiers
like `rebuild_proxies` and `rebuild_auth`, not in the summary line or
the signature.

Production retrieval scores five fields -- purpose, signature,
concepts, name, and qualname. None of them is body text. PR #40 adds
docstring bodies and recovers part of the gap (MRR 0.500 to 0.550) but
moves Hit@K not at all, which localises the missing signal further:
it is in the code, not only in the prose.

### The two methods are complementary, not redundant

Fusing the two candidate lists with reciprocal rank fusion (k=60,
truncated to 8):

| Metric | Best single method | RRF of both |
| --- | --- | --- |
| Hit@1 | 53.33% | 46.67% |
| Hit@3 | 80.00% | 80.00% |
| Hit@K | 86.67% | **100.00%** |
| MRR | 0.667 | 0.631 |

The union of the two top-8 lists contains a gold unit on 15 of 15
cases. Neither method alone reaches that. Naive RRF converts the
complementarity into perfect Hit@K but dilutes MRR below the control
arm, because it demotes the rank-1 wins grep earns on body-heavy
queries. A weighted or score-level fusion is the obvious next
experiment; equal-weight RRF is not the right final answer.

### What this changes

Ranking is not the differentiator. On these cases a reviewer running
plain text search finds the right unit more often than the current pipeline does.
What the pipeline still provides that text search does not is a bounded,
structured packet: 4104 bytes against 21107 to inspect the same number
of candidates, a 5.1x difference, before counting the files an agent
without the index would have to open to segment the matches at all.

The defensible position for v1 is therefore that Code Steward's value
is compression and structure, not recall -- and that its recall should
be repaired by adopting lexical matching rather than by further tuning
the fuzzy weights.

### Validity threats

The gold labels were written while reading the Requests source, so
query wording shares vocabulary with the code it describes. That bias
inflates any lexical method. It applies to both arms, since production
scoring is also lexical, but it inflates the control arm more, because
the control arm matches raw source text while the ranker matches
curated fields. A query set written from the public documentation
rather than the source would test this.

The control arm is also handed unit boundaries for free. An agent with
only text search would pay to segment matches itself, so the
21107-byte cost above understates the real cost of that workflow.

## Packet precision and noise

Every metric above the control-arm section answers "was the right unit
present". None answers "how much of the packet was worth reading",
which is the question the project's noise-reduction goal actually
poses. Hit@K cannot distinguish a packet of seven near-misses from a
packet of seven unrelated functions.

### Protocol

All 204 candidates returned by either arm across the 15 Requests cases
were labeled `relevant`, `plausible`, or `irrelevant`. The labeling was
blind by construction: `benchmarks/real_repo/label_sheet.py` pools the
arms' candidates, strips which arm produced each one, removes the
recorded gold unit and traps, orders candidates by a hash of the
(case, unit) pair so the sequence carries no ranking signal, and
attaches each unit's real source. A labeler who can see that a
candidate was ranked first by the system under evaluation is not an
independent judge of relevance.

The label vocabulary is deliberately three-valued. A forced binary
choice pushes every defensible near-miss into whichever bucket the
labeler favours, and near-misses are exactly the population this
measurement exists to size.

As a check on the labels rather than on either arm, the blind labels
reproduced the recorded gold key on 15 of 15 cases without having seen
it.

### Result

| Arm | Precision (strict) | Precision (lenient) | Noise rate | Wasted bytes/query |
| --- | --- | --- | --- | --- |
| Code Steward | **14.91%** | 43.86% | 56.14% | **2,288** |
| Text-search control | 12.50% | **57.50%** | **42.50%** | 8,124 |

Strict precision counts only `relevant`. Lenient also counts
`plausible`. Wasted bytes applies each arm's noise rate to its byte
cost, assuming candidates within one packet cost about the same --
sound for Code Steward's uniform summary entries, rougher for raw
source, and nowhere near rough enough to close a 3.6x gap.

### Reading

The result splits, and neither half is quotable alone.

By share of the packet, **Code Steward is the noisier of the two**: 56%
of what it returns is judged not worth reading against 42% for keyword
search. Lenient precision says the same thing more sharply -- 43.86%
against 57.50%. The ranking selects worse.

By bytes, **Code Steward wastes 3.6x less**: 2,288 against 8,124. The
packet format is doing real work.

Together these say Code Steward is a good compressor wrapped around a
poor selector. That is the most precise statement of the project's
current position, and it points at exactly one fix: replace the
selector, keep the packet.

### The trap label was never a noise metric

All four units the case set declares as `traps` were independently
judged `plausible`, not `irrelevant`. They are reasonable near-misses.
Every trap-rate number recorded in this document therefore measures
"returned a near-miss", not "returned noise", and must not be cited as
evidence about noise in either direction.

## Body term coverage as a scored field

The text-search control arm has beaten the five-field metadata ranker
on every retrieval metric since it was built. The diagnosis recorded
at the time was that the signal the control finds lives in **code
bodies** — identifiers like `rebuild_proxies` — and that no scored
field read them. This is that diagnosis acted on.

A sixth field, `body`, scores the fraction of distinct query terms
that appear as a substring of the unit's source tokens. The matching
rule is the control's, not a new one: `code_steward/lexical.py` holds
it and `grep_baseline.py` now imports from there, so the control and
the thing it controls cannot disagree about what a query term is.

### The weight was fixed before measuring

`body` takes 0.50; the five existing fields share 0.50 in their
previous proportions. The rationale, decided in advance and not
revisited: a control consisting of nothing but body term coverage
outscored all five metadata fields together, so weighting the body
equal to the whole existing stack is the least presumptuous reading of
that result.

**No weight search was run.** Searching for a weight against these
fifteen cases would convert the benchmark into a target.

### Result on `psf/requests`

| Metric | Five fields | + body | Text-search control |
| --- | --- | --- | --- |
| Hit@1 | 46.67% | **33.33%** | **53.33%** |
| Hit@3 | 60.00% | 66.67% | **80.00%** |
| Hit@5 | — | 86.67% | — |
| Hit@K | 73.33% | **93.33%** | 86.67% |
| MRR | 0.550 | 0.534 | **0.667** |
| Mean packet bytes | 4,039 | 3,987 | 21,107 |

This is a mixed result and both halves matter.

**Recall improved sharply, and the ranker beats the control on Hit@K
for the first time.** Four cases that previously returned *no correct
unit at all* — 007, 010, 011, 013 — now find one. The standing
complaint that "roughly one query in four returns a packet that does
not contain the correct unit" is now roughly one in fifteen.

**Hit@1 regressed, from 46.67% to 33.33%.** Four cases that ranked the
right unit first no longer do, and one case that previously ranked its
unit fourth now misses entirely. Units whose metadata matched well but
whose bodies do not contain the query terms were demoted.

Per case, six improved, five regressed, four were unmoved.

### Why this shipped anyway

The decision to keep the change was made **after** seeing this table,
and a reader is entitled to weigh it differently. The reasoning:

The product emits a **packet of eight candidates**, not a top-1
answer. Both the skill and the reviewer agent already state that the
top candidate is wrong more often than not and require reading a body
before any reuse decision. For a packet, the binding constraint is
whether the correct unit is present at all, and that is the metric
that moved most.

The packet is also no longer the primary path. Measured on 250
held-out functions, drafting the code and comparing it surfaces the
existing duplicate 99.4% of the time against the packet ranker's
45.3%; see [`docs/verdict.md`](verdict.md). The ranker is the fallback
for tasks that cannot be sketched, and a fallback that fails to
contain the answer is worse than one that ranks it third.

### What it costs

The unit's distinct source tokens are stored in the index as a new
`body_terms` column — distinct tokens rather than source, because the
score only asks whether a term occurs. On `psf/requests` the index
grew from 604 KB to 712 KB, about 18%. Build time was unchanged.
Nothing is computed at query time that was not computed before.

### Caveats

**Fifteen cases.** Every difference above is between one and four
cases. Hit@1 46.67% versus 33.33% is seven cases versus five. Treat
the direction as informative and the magnitude as noisy.

**A weight between 0 and 0.5 may get both.** It very likely exists.
Finding it requires a held-out query set, which is
[roadmap item 2](../README.md#next-in-priority-order) and does not
exist yet. Searching for it on these fifteen cases is the thing this
project has committed not to do.

**Frozen Benchmark v1 moved cleanly and says less than it appears
to.** MRR 0.651 → 0.799 and the trap rate halved, with Hit@K unmoved.
That fixture documents 19 of 20 units and uses queries averaging under
four words; it is a regression guard against itself, not evidence
about real code. The mixed table above is the one that counts.
