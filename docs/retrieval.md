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
