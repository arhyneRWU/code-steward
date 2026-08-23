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

## Deliberate limits

This storage and extraction layer does not yet:

- calculate structural similarity
- select a graph traversal algorithm
- introduce FTS, embeddings, or a vector database
- introduce Neo4j or another graph database

Those are independent retrieval questions. The purpose of this layer is to give later experiments a stable, provenance-preserving intermediate representation.
