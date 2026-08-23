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
