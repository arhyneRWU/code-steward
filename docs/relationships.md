# Relationship storage

Code Steward stores deterministic code facts separately from inferred similarity.

This is a graph data model implemented in SQLite. It does not require a graph database.

## Deterministic relationships

`HardRelationship` represents facts produced by a parser, framework enricher, test mapper, or another deterministic source.

Each edge stores:

- `source_unit_id`, the indexed unit that owns the relationship
- `relation`, such as `CALLS`, `IMPORTS`, `RETURNS_TYPE`, or `TESTED_BY`
- `target_kind`, a language-neutral target category
- `target_ref`, the stable reference within that category
- `provenance`, the extractor or rule that produced the edge
- structured `evidence`
- the current source body hash
- the target body hash when the target is another indexed unit

A deterministic target does not have to be a code unit. For example, an import can initially point to `target_kind="module"` and `target_ref="json"`. A resolved call can use `target_kind="unit"` and the Code Steward unit ID.

Hard edges are derived from their source. Reindexing a source unit removes its outgoing hard edges. Reindexing a target that keeps the same stable unit ID preserves incoming hard edges and refreshes their target hash. Removing the target unit removes resolved incoming hard edges.

## Inferred relationships

`SoftRelationship` is reserved for scored inferences between indexed code units, such as:

- `SIMILAR_TO`
- `RELATED_TO`
- `SAME_INTENT`
- `POSSIBLE_CLONE`

Each inferred edge stores its score, provenance, evidence, and the body hashes of both units. Deterministic facts and inferred similarity never share a table.

Scores are normalized to the closed interval from 0 to 1. The storage layer does not define what a score means across different inference methods. Provenance is therefore required.

Soft relationships depend on both bodies. Reindexing either unit invalidates the cached edge.

## Replacement semantics

Relationship writers can replace either the full outgoing hard set or one deterministic provenance source:

- `replace_hard_relationships`
- `replace_hard_relationships_for_provenance`
- `replace_soft_relationships`

Provenance-scoped replacement lets independent deterministic extractors refresh their own evidence without deleting facts produced by other extractors.

All proposed edges are validated before existing outgoing edges are deleted. Invalid targets, malformed scores, duplicate edges, or source mismatches therefore leave the previous relationship set intact.

## Python call relationships

The first deterministic extractor uses Python ASTs to produce `CALLS` edges with `python-ast` provenance.

Resolution is deliberately conservative. Same-module declarations and unambiguous imports can become `target_kind="unit"` edges. Calls that cannot be resolved safely remain `target_kind="symbol"` relationships with the original expression and line evidence.

Call extraction does not by itself change retrieval ranking. Structural retrieval remains a separate benchmarked decision.

## External graph facts

Code Steward may consume facts produced by an external code-intelligence
tool, but those facts are never authoritative and never enter the
tables described above.

**Externally derived facts live in a separate opt-in store.** They are
not written to `hard_relationships` under a new `provenance`, and they
are not written to `soft_relationships`. Provenance separates
extractors that Code Steward controls and can reproduce. An external
tool is a different category: its availability, version, and
completeness are outside this project's control.

The reason is reproducibility. `hard_relationships` backs the frozen
retrieval benchmark and the real-repository validation harness, both
of which exist to produce numbers that are comparable across machines
and across CI runs. An index whose contents depend on whether an
external tool happened to be installed at build time is not
comparable, and nothing in the resulting artifact would say which
variant was produced.

Three rules follow:

1. An enrichment pass is opt-in and explicit. It never runs as a side
   effect of `build` or `update`.
2. No frozen-benchmark path and no real-repository validation path may
   invoke it. Benchmark results must be reproducible from this
   repository and a Python interpreter alone.
3. Any consumer of external facts must gate on completeness and
   staleness before reading them. A partially built external graph
   answers queries about the fraction of the repository it has seen,
   usually without signalling that it is incomplete, so an ungated
   consumer will silently record confident facts about a small sample.

These rules constrain where external facts may be stored and when they
may be read. They do not settle whether any particular integration is
worth building; see `docs/retrieval.md` for the measured verdict on
structural retrieval.

## Deliberate limits

This storage and extraction layer does not yet:

- calculate structural similarity
- select a graph traversal algorithm
- introduce FTS, embeddings, or a vector database
- introduce Neo4j or another graph database

Those are independent retrieval questions. The purpose of this layer is to give later experiments a stable, provenance-preserving intermediate representation.
