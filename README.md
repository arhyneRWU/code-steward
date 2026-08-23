# Code Steward

**Context-efficient code intelligence and stewardship for Claude Code.**

Code Steward tells you when you have just written a function the repository already has. It indexes a repository into stable code-unit IDs, compares the functions you changed against them, and reports the overlaps — or asserts that there are none.

```bash
code-steward trace "pkg.mod::fn"      # this function, its callers, callees, tests
code-steward check                    # what does this branch duplicate?
code-steward check --rate             # is this repo quiet enough to gate on?
```

`trace` is the context-window half: one function plus the path around it as a self-contained bundle, for handing to a model that cannot hold the repository. Measured at **10.3x** compression against reading the files on Django, mean bundle 4,170 bytes — with the honest caveat that call resolution only reaches 54.7% of Django's functions. See [`docs/trace.md`](docs/trace.md).

**Where this landed, and why.** The project set out to make the reuse decision *before* any code existed — from a task sentence. Measurement moved it twice, and the second move was the important one:

| What is compared | Duplicate found |
| --- | --- |
| A task sentence, through the packet ranker | 0.459 |
| A body an agent drafted from a name and docstring | 0.460 |
| **The real body** | **1.000** |

Same held-out cases. The comparison is not the variable — how much of the function exists when you run it is. So the useful moment is not before the code is written but after, and before it is kept: late enough that a real body exists, early enough that deleting it is cheap. That is what `check` does. [`docs/direction.md`](docs/direction.md) records the reframes and the assumptions that did not survive them.

The main coding session should receive **decisions and selected code units, not the full history of repository exploration**. Instead of repeatedly searching large files, rediscovering callers and tests, or writing something that already exists, Code Steward builds a compact map of a codebase, retrieves the relevant existing units, and delegates deeper investigation to isolated review agents.

> **Project status:** early development. The architecture is being implemented and tested first against Python and FastAPI codebases. The public API, plugin behavior, and storage format may change.

> **What is measured today.** Both halves of the project have been compared against a simple control on real repositories.
>
> - **Reuse detection** works and ships. Five-token shingle comparison measures macro precision **1.000** and F1 **0.577** across three pinned public repositories, ahead of jscpd (0.506) and of this project's own metadata comparison (0.385), at 2.3× to 3.6× fewer bytes. See [Reuse similarity](#reuse-similarity).
> - **Drafting and comparing beats describing the task — on recall, not by as much as it looked.** Comparing a function's real body surfaces its duplicate **99.4%** of the time against **45.9%** for a task sentence. With bodies an agent drafted from a name and docstring, that becomes **46.0%** end to end. The remaining advantage is precision, not recall. See [What a realistic draft is actually worth](#what-a-realistic-draft-is-actually-worth).
> - **Extra evidence in the packet did not change the verdict.** Sixty held-out cases put to a blinded reviewer agent, paired across arms: 0.683 without reuse evidence, 0.733 with, exact two-sided **p = 0.549**. Null. See [Does the verdict change](#does-the-verdict-change).
> - **Retrieval ranking** is split against plain text search on `psf/requests`: ahead on Hit@K (93.33% vs 86.67%) after body term coverage became a scored field, behind on Hit@1 (33.33% vs 53.33%) and MRR. Its larger contribution is still compression — 3,987 bytes of packet against 21,107 bytes of source. See [Measured position](#measured-position).
>
> Treat the roadmap as open questions rather than delivered features.

## Goals

Code Steward is being designed around two forms of stewardship:

1. **Steward the context window.** Keep broad repository exploration, graph traversal, history inspection, and duplicate analysis out of the main coding context whenever they can be handled deterministically or inside a disposable subagent context.
2. **Steward the codebase.** Search before implementation, reuse existing behavior where appropriate, understand the impact of changes, and avoid unnecessary duplication or parallel abstractions. The duplication half of this is now measured; see [Reuse similarity](#reuse-similarity).

A third has been added by measurement rather than design:

3. **Be willing to say no.** On a third of cases where the right answer was to write the function, a reviewer handed the packet was talked into reusing something instead — because retrieval returned its eight best candidates whether or not any fitted. `similar` now applies a **relevance floor of 0.27**, chosen on a held-out cross-corpus null distribution as the smallest value holding the false-positive rate at or under 1%. It keeps 167 of the 170 labelled duplicates. An empty result is now something the tool can assert rather than a search that failed. See [`docs/floor.md`](docs/floor.md).

   The packet ranker is still unfloored: its score is on a different scale and no null distribution has been measured for it. Inventing a threshold for an uncharacterised scale would be the same mistake in a new place.

The first two reduce to one operational claim: **an agent should read less code, and less irrelevant code, to make the same decision.** Those are two separate claims and the evidence splits between them. Fewer bytes: measured, holds by a wide margin. A higher *share* of what the agent sees being relevant: measured, and currently not true — the packets are proportionally noisier than plain keyword search, but much cheaper per unit of noise. See [Measured position](#measured-position).

The intended workflow is:

```text
request
  |
  v
compact code index
  |
  +-- names / signatures / types
  +-- summaries / concepts
  +-- endpoints
  +-- hashes / Git metadata
  |
  v
ranked candidate units
  |
  v
isolated review agent
  |
  +-- REUSE
  +-- EXTEND
  +-- REFACTOR
  +-- CREATE
  +-- UNCERTAIN
  |
  v
main coding agent receives only the selected units and decision
```

## Measured position

Code Steward is validated against `psf/requests` pinned at `8f8b212d`, using 15 hand-verified retrieval cases. Frozen Benchmark v1 runs on a synthetic fixture and reports much better numbers; those numbers are a regression guard against themselves and should not be read as quality on real code.

The control arm is plain text search: drop stopwords from the query, scan every `.py` file case-insensitively for each remaining term, rank units by how many distinct terms they contain. No Code Steward code is involved in its ranking.

| Metric | Code Steward | Text-search control |
| --- | --- | --- |
| Hit@1 | 33.33% | **53.33%** |
| Hit@3 | 66.67% | **80.00%** |
| Hit@K | **93.33%** | 86.67% |
| MRR | 0.534 | **0.667** |
| Bytes handed to the reviewer | **3,987** | 21,107 |

The position is now split rather than a clean loss. Body term coverage was added as a scored field — the control's own matching rule, shared from one implementation — with the weight fixed before measuring and no weight search run.

**Recall improved sharply and the ranker beats the control on Hit@K for the first time**, 93.33% against 86.67%. Four cases that previously returned no correct unit at all now find one. **Hit@1 regressed**, 46.67% to 33.33%, because units whose metadata matched but whose bodies do not contain the query terms were demoted.

The change shipped on the grounds that the product emits a packet of eight, not a top-1 answer, and that the packet is now the fallback path rather than the primary one — see [Does the evidence arrive](#does-the-evidence-arrive). That decision was made after seeing the numbers and a reader may weigh it differently. Fifteen cases, so every difference above is one to four cases. Full table, per-case movement, and reasoning in [`docs/retrieval.md`](docs/retrieval.md).

The Code Steward column reflects the current pipeline, which scores whole docstring bodies as well as summaries. Before that change it read Hit@1 40.00% and MRR 0.500; the improvement is real and does not close the gap. `docs/retrieval.md` carries both.

Two things follow.

**Compression is still the larger contribution.** 3,987 bytes against 21,107 to inspect the same candidates is 5.3x, and that understates the gap: the control arm is handed unit boundaries by the index for free, so an agent with only text search would pay more again to work out where each match begins and ends.

**Fuzzy field scoring was not the differentiator.** Lexical body matching is now a scored field. It fixed recall and cost top-1 accuracy; finding a weight that keeps both needs a held-out query set rather than more passes over these fifteen cases. Fusing the two candidate lists already reaches Hit@K 100% on all 15 cases, which says the methods are complementary rather than competing.

### Noise

The project's goal is to reduce what an agent has to read *and* how much of it is irrelevant. Both halves are now measured.

Every candidate either arm returned — 204 across the 15 cases — carries a relevance label. The candidate sets were captured before docstring-body indexing landed, so the precision figures below describe that pipeline; re-running the arms regenerates any candidate the labels do not yet cover, and `precision.py` refuses to score a packet with an unlabeled candidate rather than quietly understating noise. Labels were assigned blind: the labeler saw the query and the unit's source, never which arm produced the candidate, its rank, or the recorded gold unit. As a check on the labels themselves, they independently reproduced the gold key on 15 of 15 cases.

| Arm | Precision (strict) | Precision (lenient) | Noise rate | Wasted bytes per query |
| --- | --- | --- | --- | --- |
| Code Steward | **14.91%** | 43.86% | 56.14% | **2,288** |
| Text-search control | 12.50% | **57.50%** | **42.50%** | 8,124 |

The answer splits cleanly, and neither half should be quoted without the other:

- **By share of the packet, Code Steward is noisier.** 56% of what it returns is judged not worth reading, against 42% for keyword search. It shows the agent a *higher proportion* of junk.
- **By bytes, Code Steward wastes 3.6x less.** 2,288 wasted bytes per query against 8,124. The junk it shows is far cheaper to skip.

The packet format is doing the work here and the ranking is not. That is a fixable shape, and it is why the measurement came before the fix.

One incidental finding: all four units the benchmark had declared "traps" were judged *plausible*, not irrelevant. They are reasonable near-misses, not noise, so the trap rate reported elsewhere in this project was never a noise metric and should not be read as one.

Reproduce with `benchmarks/real_repo/label_sheet.py` (emits blind sheets) and `benchmarks/real_repo/precision.py` (scores them). Labels live in `benchmarks/real_repo/requests_candidate_labels.json`.

### Reuse similarity

Answering *does this already exist* before an agent writes it again. Three public repositories pinned to full commit SHAs (`home-assistant/core`, `apache/airflow`, `django/django`), sampled by a stated hash rule rather than by hand. Candidate pairs pooled from three independent generators, provenance stripped, 308 pairs labelled blind. Four arms scored from one label file at depth 30.

| Arm | Precision | Recall (in pool) | F1 | Bytes |
| --- | --- | --- | --- | --- |
| **token-shingle** | **1.000** | **0.406** | **0.577** | **37,342** |
| jscpd | 0.878 | 0.356 | 0.506 | 135,934 |
| `metadata_similarity` | 0.667 | 0.271 | 0.385 | 85,145 |
| body-rapidfuzz | unevaluated | 0.210 | 0.321 | 89,400 |

Macro means over the three corpora. Five-token shingle comparison came first and now ships as `code_steward.similarity`; see [Finding reuse before the code exists](#finding-reuse-before-the-code-exists). The benchmark imports that module rather than keeping its own copy, so the measured code and the shipped code are the same code.

`metadata_similarity`, which this project already had, came last of the three evaluable arms. It stays where it is — deduplicating a result set — and is not used for reuse detection.

`body-rapidfuzz` returned 44 of 90 pairs that nobody labelled, and 29 of 30 on Django. Its precision is a bracket, so it is reported as unevaluated rather than as the 1.000 its labelled subset suggests.

Two results that bear on how much to trust the rest:

- A generator-free random sample of 45 pairs contained **0 positives**, in all three corpora. That is the base rate the pooled 84.4% sits above.
- Django was chosen as the hard-negative corpus and did not behave like one: 85.2% pooled positive rate, higher than Airflow's 82.4%. It has real intra-file duplication. The selection rule was published beforehand and was not changed afterwards.
- This is the **second** gold set. The first excluded every decorated function, because unit lookup keyed on the `def` line while the indexer records a decorated function's start as its first decorator. Fixing that grew the corpora 27–133% and invalidated the first set, so it was rebuilt rather than patched. The result went the same way and further: the shipped arm rose from 0.571 to 0.577 F1 and `metadata_similarity` fell from 0.431 to 0.385.

Depth 30 is both the pool depth and the measurement ceiling. Reading the same ranking deeper looks better and is not interpretable: at depth 480 the arm returns 1,440 pairs of which 90% are unlabelled, so its apparent precision of 0.993 covers a tenth of its own output. Recall past depth 30 is unknown rather than probably-higher.

Full numbers, method, and the validity threats are in [`docs/similarity.md`](docs/similarity.md). Reproduce with `make bench-similarity-corpora` then `make bench-similarity`.

### Finding reuse before the code exists

The measurement decided the mechanism; this is the surface it ships behind.

```bash
code-steward similar src.app.orders::apply_discount     # an indexed unit
code-steward similar --draft new_function.py            # code not written yet
code-steward packet "apply a percentage discount" --reuse
```

`--draft` is the case the rest of the design is aimed at. An agent about to write a function can ask what already resembles it, using the same comparison the indexed path uses, before the code exists to be indexed. `packet --reuse` attaches near-duplicate evidence to each candidate, which is what separates a REUSE from a REFACTOR: a candidate that already exists three times over should not be reused a fourth time.

Comparison runs over normalised function bodies — `ast.unparse` output, so comments, formatting, and docstrings are invisible to it. Identifiers are kept.

**What it catches and what it does not.** On a fixture function, overlap against modified copies of itself:

| Change to the copy | Overlap |
| --- | --- |
| docstring rewritten | 1.000 |
| function renamed | 0.941 |
| whole signature renamed | 0.535 |
| every local variable also renamed | 0.015 |

A function that was copied, pasted, and tidied is found. A function that was independently reimplemented in different words is not. Catching that needs a structural comparator, which is a different tool and has not been measured here. The limitation is pinned by a test so it cannot quietly change.

There is nothing novel in the comparison itself — near-duplicate detection by token shingles is long-established, and jscpd is a mature tool that placed second on this benchmark. What is different here is where it sits: at indexed-unit granularity, keyed to stable IDs, answering the question before the change is kept, and returning a packet an agent acts on rather than a report a person reads. The measured edge over jscpd is modest on F1 (0.571 against 0.521) and larger on bytes (2.3x fewer), and bytes are what make it affordable inside an agent's context.

### Does the evidence arrive

The numbers above are about a comparison arm. This one is about the product: given a function someone is about to write, does the existing duplicate actually reach the reviewer?

A case takes a function whose duplicate is already labelled, removes it from the repository, and uses its docstring summary as the task an agent would type. 496 cases built, 250 scored, 246 excluded.

| Arm | Duplicate surfaced | False positives | Mean bytes |
| --- | --- | --- | --- |
| `packet` (control) | 0.459 | 0.176 | 2,782 |
| `packet --reuse` | 0.654 | 0.264 | 4,405 |
| **`similar --draft`** | **0.994** | 0.264 | **2,636** |

**Drafting and comparing dominates.** It finds the existing function in 158 of 159 cases, at fewer bytes than the plain packet and no worse a false-positive rate. The skill and reviewer agent were already told to draft-and-compare before falling back to the ranker; that ordering was reasoned from a component number and is now measured.

**`--reuse` gets the evidence there and does not change the answer.** Twenty more cases in a hundred where the duplicate arrives, for 58% more bytes — and, when the verdict itself is scored, no measurable improvement. See below.

### Does the verdict change

The table above measures evidence *arriving*. It does not measure a decision *changing*, which is the actual claim. So sixty of the held-out cases were put to a reviewer agent twice, once per packet arm, with candidates blinded to labels `C1..C8` so the reviewer could not open the file and answer from the source.

| Arm | Positive | Negative | Overall |
| --- | --- | --- | --- |
| `packet` | 0.700 | 0.667 | 0.683 |
| `packet --reuse` | 0.733 | 0.733 | 0.733 |

**This came back null.** The arms are paired on the same cases, so the test is McNemar's: eleven cases disagreed, four favouring the plain packet and seven the reuse packet, exact two-sided **p = 0.549**. The five-point gap is noise at n=60. On the evidence so far, the extra 58% of bytes buys a better-populated packet and no better answer.

**The expensive failure is one nobody was measuring.** On a third of the negative cases the reviewer was talked into REUSE or EXTEND when the right answer was to write the function. Retrieval always returns its eight best candidates, and a reviewer handed eight plausible functions tends to pick one. A missed duplicate costs some redundancy; a wrong reuse wires the caller to code that does not do the job.

Caveats, and they matter: the reviewer sample stratifies by corpus, which over-weights Django where retrieval is strongest, so its surfaced rate is 0.733 against 0.459 pooled — read these as the reviewer's skill *given good retrieval*, not as an end-to-end number. n=30 per polarity per arm can detect a large effect and cannot rule out a small one. Blinding withholds paths a real reviewer would see, so the figures are a floor. One reviewer model, one prompt.

Three further limits on the table above, none of them small:

- **246 of 496 cases were excluded** because the function has no docstring, so its task text would have been its own identifier. That means this speaks only about documented functions — and undocumented code is where the ranker is documented to do worst, so the control's 0.459 is its score on favourable ground.
- **`similar` has no score floor**, which is visible in the false positives on negative cases. Choosing one is deliberately not done here: it would be tuning against the gold set.

Full method and caveats in [`docs/verdict.md`](docs/verdict.md). Reproduce with `make bench-verdict`.

### How often `check` fires

Treating every function as newly written and comparing it against the rest of its own repository, at the shipped 0.27 floor:

| Codebase | Functions | Overlap something |
| --- | --- | --- |
| Airflow providers | 5,638 | 63.3% |
| Home Assistant integrations | 1,176 | 45.5% |
| Django | 5,541 | 29.7% |
| Code Steward, `src/` only | 147 | 14.3% |

**Alarm rates, not error rates** — nothing there is labelled. Airflow's providers duplicate each other by design, so most of that 63% is probably the tool being right, and it is unusable as a blocking gate there anyway. Django is the low-duplication corpus and is still near 30%.

So `check` ships as a report rather than a gate. `--fail-on-overlap` is opt-in, and `code-steward check --rate` gives you the figure for your own repository first.

**By default it reports only the overlaps your change introduced.** A function that already duplicated something before you touched it is not your finding. Replaying real commits — index each commit's parent, check the commit against it:

| Repository | Commits | Every overlap | Only introduced | |
| --- | --- | --- | --- | --- |
| Django | 13 | 261 (20.1/commit) | **16 (1.2/commit)** | **16.3x** |
| Code Steward | 32 | 223 (7.0/commit) | **72 (2.2/commit)** | **3.1x** |

The spread is the interesting part: Django is mature, so its changed functions had already accumulated whatever overlap they have and almost none of it is newly introduced. Code Steward is young and actively being written, so more of its changed functions are genuinely new code. Both runs are small and neither is labelled. `--all-overlaps` restores the unfiltered view. See [`docs/check.md`](docs/check.md).

### Validity threats on record

- The benchmark queries were written while reading the Requests source, so their wording shares vocabulary with the code. That inflates any lexical method, and it inflates the raw-text control more than the field-based ranker. A query set written from public documentation would test it.
- Frozen Benchmark v1's fixture documents 19 of 20 units and uses queries averaging under four words. Real code does neither.

- Every cost figure in this README is measured in bytes, which is a proxy for tokens. Calibrated against `tiktoken`, the proxy is within ±3.6% on ordinary Python source but **10.9% off on packets**, in the direction that flatters the compression claim. The true token compression is therefore somewhat below the 5.2x quoted above. See [`docs/token-calibration.md`](docs/token-calibration.md).

Full numbers, per-case results, and diagnosis live in [`docs/retrieval.md`](docs/retrieval.md). The control arm is `benchmarks/real_repo/grep_baseline.py`; run it with `make bench-grep`.

## Architecture

Code Steward combines several complementary sources of code intelligence rather than rebuilding all of them. Each subsection below states whether the piece is built, tested and rejected, or not yet implemented.

### Local Python and FastAPI index

The first implementation targets Python and FastAPI and extracts information that is cheap and deterministic to obtain:

- functions, classes, and exact source boundaries
- function signatures and parameter names
- type annotations and return types
- docstrings and compact purpose summaries
- FastAPI routes, response models, and dependencies
- source hashes and Git metadata
- optional stable aliases and conceptual code-unit regions

### Low-context retrieval

Candidate generation should happen before model reasoning whenever possible. The current implementation scores six fields per unit — body, purpose, signature, concepts, name, and qualname. Five are RapidFuzz-style similarity over metadata; `body` is term coverage over the unit's source tokens, using the same matching rule as the text-search control arm and sharing one implementation with it. The purpose field scores the better of the docstring summary and the whole docstring body, so documentation below the summary line reaches the ranker without reaching the packet.

The goal is to reduce a large repository to a small evidence packet before an agent is asked to make an architectural decision. The packet part works. The ranking now beats a stopword-stripped keyword scan on Hit@K and loses to it on Hit@1 and MRR. See [Measured position](#measured-position).

### Comparison before implementation

The reuse question is asked against an indexed unit or against a draft that has not been written yet. Both paths normalise through `ast.unparse` and compare the same way, so a draft and its eventual indexed self produce the same result. Nothing is stored: shingles are built on demand from source, so no index schema depends on this and no benchmark number moves because the feature exists.

### Isolated review agents

A reviewer should receive only the task and a small candidate packet. It can then pull exact code units, tests, history, and graph relationships only when needed. Its final result should be compact and structured so that exploratory material does not accumulate in the main coding session.

### Structural graph integration (tested, not adopted)

An earlier plan was to enrich retrieval with an external structural graph such as [Graph Code Review](https://github.com/tirth8205/code-review-graph). That plan was tested and dropped.

Code Steward extracts its own conservative `CALLS` edges. Reranking candidates by one resolved `CALLS` hop moved no retrieval metric in any direction — not Hit@K, not MRR, not the trap rate. Importing a second, less carefully verified source of the same edge type cannot be justified on ranking grounds when the carefully verified one does nothing. The verdict and its caveat — only 27.72% of extracted edges resolve to indexed units, so this rejects the tested fusion at the current resolution rate rather than structural retrieval in general — are recorded in [`docs/retrieval.md`](docs/retrieval.md).

Structural relationships are still stored and still useful for impact analysis and test discovery. They are simply not a ranking input, and the case for an external graph has to rest on a capability other than ranking.

### Reuse detection

`code_steward.similarity` compares five-token windows of normalised function bodies. It is the arm that won the benchmark, promoted unchanged, and the benchmark imports it rather than keeping a copy.

Duplicate findings are evidence for a decision, not an instruction to abstract every repeated block. A candidate carrying duplicates points at REFACTOR rather than REUSE; it does not settle the question, and the reviewer still has to.

[jscpd](https://github.com/kucherenko/jscpd) is benchmarked as one of the four arms and reaches F1 0.506, second of four. It is not a dependency: it needs Node, and it returned 2.3x the bytes for slightly worse F1.

## Code Steward and Graph Code Review

[Graph Code Review](https://github.com/tirth8205/code-review-graph) is the closest neighbouring project, and the two overlap more than either README would suggest. This section exists because reading their source changed what this project should claim.

**Their retrieval layer is this project's design, arrived at independently.** Same SQLite unit table, same metadata fields, same fixed-cap truncation, same content-hash staleness check. Their embeddings run over that same field set and, like Code Steward's scorer, never read a function body. Neither project should present its ranking as a differentiator against the other.

**Their moat is elsewhere, and it is real.** A Tree-sitter parser across roughly 55 languages against this project's Python-only AST index, and a typed edge graph against Code Steward's conservative `CALLS` and `TESTED_BY` extraction. Blast-radius analysis from a diff is theirs; Code Steward has nothing equivalent.

**Graph Code Review does not compare one node to another.** A search across its package for `duplicate|clone|jaccard|simhash|minhash|levenshtein|difflib` returns 38 hits, and all of them are deduplication by identity, a `difflib` call that renders a refactor preview, or a cosine similarity used once — as `_cosine_similarity(query_vec, vec)`, which is query-to-node, not node-to-node. There is no way to ask which two functions resemble each other, and none is claimed. Worth noting that they store a per-node embedding already, so node-to-node is not far away for them; unoccupied is not the same as defensible.

| Question | Code Steward | Graph Code Review |
| --- | --- | --- |
| Rank a query against a unit | RapidFuzz over metadata | MiniLM over the same metadata |
| Function bodies scored | no | not embedded |
| Language coverage | Python | ~55 languages |
| Typed call / import edges | conservative, Python only | the moat |
| Blast radius from a diff | none | weighted SQL relaxation |
| Similar / duplicate functions | measured and shipped | absent, not claimed |

They answer *what breaks if I change this*. Code Steward answers *what is the smallest thing you can read to decide*. Those compose.

### On quoting their numbers

Their headline figure is a **65x** token reduction. Their own FAQ states the baseline: it is measured against feeding the **whole corpus** to the model, which is not what an agent with ordinary search tools does. Code Steward's compression numbers are measured against the source of the same candidates, which is a different and much less flattering baseline — 5.2x, not 65x — and the two figures are not comparable in either direction.

One methodological note, recorded because this project would want it recorded about itself: their multi-hop score moved from 0.545 to 0.909 by tuning two heuristics against the same eleven tasks within one session. That is the failure mode the [design principles](#design-principles) below exist to prevent, and it is why the similarity gold set here was frozen before it was scored and is listed under [deliberately not doing](#deliberately-not-doing) as a tuning target.

The boundary a real integration would have to respect — what it may read, what happens when their graph is absent, stale, or wrong, and the rule that no benchmark number may move because their tool is installed — is specified in [`docs/companion.md`](docs/companion.md). It is a specification with nothing implemented behind it, and nothing in it has been measured.

Read at commit `3887605`. Neither project is a dependency of the other.

## Code-unit addressing

Ordinary Python functions and classes are addressed from native AST boundaries and require no source modification. A one-line Code Steward tag can optionally give the next declaration a stable semantic ID:

```python
# code-steward: unit taxonomy.normalize
@cached
def normalize_taxon(name: str) -> Taxon:
    """Resolve a supplied name to its accepted taxon."""
    ...
```

The tag must immediately precede the declaration or its first decorator. It replaces the generated module/symbol ID for that unit rather than creating a second search candidate.

Paired tags are reserved for conceptual regions that span multiple native declarations:

```python
# code-steward: begin taxonomy.validation


def validate_name(name: str) -> None: ...


def validate_rank(rank: str) -> None: ...


# code-steward: end taxonomy.validation
```

Human documentation remains in normal language-native documentation such as Python docstrings. Hashes, Git metadata, callers, dependencies, and other generated facts stay in the index, never in source tags.

For the full draft semantics being tested, see [`docs/tag-protocol.md`](docs/tag-protocol.md).

## Design principles

- **Search before implementation.**
- **Reuse before creating parallel behavior.**
- **Do not abstract merely because code looks similar.**
- **Use deterministic tools before spending model tokens.**
- **Keep repository exploration out of the parent context when possible.**
- **Return compact decisions, not investigation transcripts.**
- **Prefer integration with mature tools over unnecessary reimplementation.**
- **Measure context savings and decision quality, not just feature count.**
- **Measure against a control, not against yourself.** Every feature that claims to beat ordinary agent behavior is compared to ordinary agent behavior on the same cases. A number that only improves against a previous version of Code Steward proves nothing about whether Code Steward is worth running.
- **Publish results that go against the project.** The text-search control arm and the rejected graph fusion are both in this README because a tool that hides its negative results cannot be trusted about its positive ones.

## Initial scope

The first development target is:

- Python 3
- FastAPI
- Claude Code skills, plugins, and subagents
- local AST-based indexing
- fuzzy and typed candidate retrieval
- exact code-unit extraction
- optional jscpd duplicate evidence (not implemented)

The architecture is intentionally broader than FastAPI so that support for other Python frameworks and languages can be considered later without changing the core model.

## Roadmap

### Built

- repository and plugin scaffold
- Python AST index with stable unit identifiers and optional source tags
- FastAPI endpoint enrichment
- compact candidate search and reviewer packets (`search`, `packet`, `read`, `map`)
- `check`, the post-write duplication pass: compares changed functions against the index and asserts when nothing overlaps
- `trace`, the function follower: one unit plus its callers, callees, and tests as a compact bundle
- introduced-only reporting, so duplication that predates a change stays out of its review
- a commit-replay benchmark that measures what the command would have said on real history
- read-only reuse reviewer agent and the search-before-implement skill
- conservative `CALLS` and `TESTED_BY` relationship extraction
- Frozen Benchmark v1, a validity matrix, real-repository validation on `psf/requests`, and a text-search control arm
- docstring-body indexing as a scoring input
- body term coverage as a scored field, sharing one implementation with the control arm
- a relevance floor on `similar`, chosen on a held-out null distribution, so an empty result is an assertion
- stable cross-process shingle hashing, which made the shingle cache work for the first time
- blind candidate labeling and packet precision/noise measurement
- a reuse-similarity gold set over three pinned public repositories, with four scored arms
- reuse detection (`similar`, `packet --reuse`), including comparison against unwritten drafts
- the skill and reviewer agent updated to draft-and-compare before falling back to the ranker
- a held-out measurement of whether the reuse evidence reaches the reviewer at all
- a blinded reviewer-agent run scoring the verdict itself, which returned null for `--reuse`
- benchmark anti-inflation guards: a rate with no denominator raises rather than publishing a perfect zero
- exclusion accounting: a run that drops a file or a case reports it as dropped
- pins enforced by tests rather than by documentation
- byte figures calibrated against `tiktoken`, with per-population error published
- documentation coverage enforcement in CI

### Next, in priority order

Reordered after the reviewer measurement. See [`docs/direction.md`](docs/direction.md) for why the old order was wrong: it was built on the assumption that recall was the binding constraint, and it isn't.

1. ~~**Report only the overlaps a change introduces.**~~ Done and now the default: 16.3x fewer findings on Django, 3.1x on this repository.
2. ~~**Let the packet return nothing.**~~ Done for the `similar` path: a 0.27 floor chosen on held-out data, an empty result that reports how many candidates it suppressed, and a decision contract where writing new code is a normal outcome. Still open for the packet ranker, which needs its own null distribution first.
3. ~~**Point the skill and reviewer agent at `check`.**~~ Done. Both now lead with the 0.459 / 0.460 / 1.000 table, treat pre-implementation search as one cheap attempt, and end on `check`. The reviewer agent grades its own `NO_CANDIDATE` by which route produced it.
4. ~~**Measure draft-and-compare on a realistic draft.**~~ Done, and it came back low: 0.700 unfloored, **0.460** with the shipped floor and counting unusable drafts. The reframe's headline margin is gone; a precision-based justification remains and has not itself been put to a reviewer. See [`docs/verdict.md`](docs/verdict.md).
5. **Test whether the draft path escapes the docstring problem.** The verdict benchmark excludes 246 of 496 cases for having no docstring, and undocumented code is where the ranker is worst. Draft-and-compare never reads a docstring, so it may simply not have this failure — testable, untested.
6. **Size the reimplementation blind spot before building for it.** Shingles miss a function rewritten in different words, and the gold set cannot say how often that happens — two of its three generators are lexical, so the population is largely absent from the pool by construction. Sizing it needs a pool built by a non-lexical generator.
7. **Write a second query set from documentation rather than source.** It sizes the vocabulary-overlap bias in every retrieval number above. Demoted, not dropped: it bears on the fallback path rather than the primary one.
8. **Fix `_module_key` for src-layout projects**, which currently caps `TESTED_BY` at 13 edges and degrades call resolution.
9. ~~**Post-change DRY and blast-radius review.**~~ The DRY half is `check`. Blast radius is still open.

### Deliberately not doing

- **External structural graph integration for ranking.** Tested, no metric moved. See [Structural graph integration](#structural-graph-integration-tested-not-adopted).
- **Further tuning of the existing five-field fuzzy weights.** The control arm shows the ceiling of that approach is below plain keyword search.
- **`metadata_similarity` as a reuse ranker.** Measured at macro F1 0.385 against 0.577, at 2.3x the bytes. It stays where it is, deduplicating a result set.
- **jscpd as a dependency.** Second of four arms, but it needs Node and returns 3.6x the bytes.
- **Tuning any arm against the similarity gold set.** The set was built, frozen, and measured once. Tuning against it would convert a benchmark into a target.
- **Adding further signal to the packet.** Two of the last three changes did exactly that. Recall improved both times; the verdict did not move. Until something moves verdict accuracy with abstention, more evidence per candidate is not the lever.

## Claude Code plugin surface

Code Steward ships a small plugin surface so an agent can use the indexer without a human
driving the CLI by hand.

```text
.claude-plugin/plugin.json
skills/searching-before-implementing/SKILL.md   # the search-before-implement workflow
skills/searching-before-implementing/references/retrieval-limits.md
agents/reuse-reviewer.md                        # read-only reviewer subagent
```

Both are written around the accuracy gap between the two tools: `similar` measured precision 1.000, the packet ranker measured Hit@1 46.67%. The skill and the agent are told to draft and compare first where that is possible, and to fall back to the ranker when it is not.

- **`searching-before-implementing`** teaches the workflow: run `code-steward packet` before
  broad exploration, treat candidates as evidence rather than answers, read the minimum number
  of unit bodies, classify the change, and fall back to ordinary exploration when the packet is
  insufficient. It states plainly when Code Steward should *not* be used.
- **`reuse-reviewer`** is the "isolated review agent" box in the diagram above. It receives a
  task, runs `packet` and `read` in its own context, and returns a compact structured decision
  so candidate evaluation never lands in the main session.

Both are deliberately conservative about the ranker's quality, for the reasons set out in
[Measured position](#measured-position): the top candidate is wrong more often than not,
roughly one query in four returns a packet that does not contain the correct unit at all, and
a plain keyword scan does better on both counts. They are also conservative about `similar`,
for a different reason — it cannot see a function reimplemented in different words, so a
silent result is not proof of absence either. Both require verification before any reuse
decision. The reviewer's no-result verdict is `NO_CANDIDATE` ("I did not find it"), not
`CREATE`.

Known gaps in this surface:

- The plugin does not install the CLI. `code-steward` must already be on `PATH`
  (`pip install -e .`) for the skill or the agent to do anything.
- There are no commands and no hooks. Indexing is not automatic; the index goes stale until
  `code-steward update <path>` or `code-steward build` is run.
- The reviewer agent holds `Bash` because that is the only way to invoke the CLI. Its
  read-only contract is enforced by instruction, not by the tool allowlist.
- Neither the skill nor the agent runs a text search alongside the packet, even though the
  control arm shows that would find units the packet misses. Doing so is roadmap item 2.
- Whether the reuse evidence actually changes a reviewer's verdict is unmeasured. The arm has
  a number; its effect on a decision does not.

## Why this project exists

Modern coding agents are capable of exploring large repositories, but exploration itself has a cost. Repeated searches, broad file reads, graph results, test discovery, and Git history can consume a substantial portion of a long-running context window. That material is often useful only long enough to make one decision.

Code Steward is an experiment in moving that work into deterministic indexes and short-lived review contexts, while preserving the information the main coding agent actually needs to make and implement a sound change.

## Contributing

The project is in an early architecture phase. Contributions and design discussion are welcome, particularly around context-efficient retrieval, code-unit identity, Python/FastAPI static analysis, and measurable evaluation of agent context use.

Contributor guidance lives in [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

Code Steward is released under the MIT License. See [`LICENSE`](LICENSE).

## Acknowledgments

Code Steward learns from existing open-source code intelligence and duplicate-analysis tools, in particular Graph Code Review and jscpd. Neither is currently a dependency: graph-based reranking was tested and rejected on measured evidence, and clone analysis is benchmarked but not wired up. Graph Code Review's benchmark engineering is better than this project's in several specific places and some of it has been adopted here; the comparison and what was borrowed are in [Code Steward and Graph Code Review](#code-steward-and-graph-code-review). Code Steward is an independent project and is not affiliated with those projects or Anthropic.
