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

## Inferred relationships

`SoftRelationship` is reserved for scored inferences between indexed code units, such as:

- `SIMILAR_TO`
- `RELATED_TO`
- `SAME_INTENT`
- `POSSIBLE_CLONE`

Each inferred edge stores its score, provenance, evidence, and the body hashes of both units. Deterministic facts and inferred similarity never share a table.

Scores are normalized to the closed interval from 0 to 1. The storage layer does not define what a score means across different inference methods. Provenance is therefore required.

## Cache invalidation

Relationships are cache entries derived from indexed units. Reindexing or deleting a unit removes every stored relationship where that unit is either the source or a resolved unit target.

This makes body hashes an audit record of the inputs used to create an edge while keeping invalidation simple and conservative. Future extractors can regenerate relationships after an index update.

## Replacement semantics

Relationship writers replace the complete outgoing set for one source unit and one relationship class:

- `replace_hard_relationships`
- `replace_soft_relationships`

All proposed edges are validated before existing outgoing edges are deleted. Invalid targets, malformed scores, duplicate edges, or source mismatches therefore leave the previous relationship set intact.

## Deliberate limits

This storage layer does not yet:

- extract ordinary Python call edges
- resolve imports to local units
- calculate structural similarity
- select a graph traversal algorithm
- introduce FTS, embeddings, or a vector database
- introduce Neo4j or another graph database

Those are independent retrieval and extraction questions. The purpose of this layer is to give later experiments a stable, provenance-preserving intermediate representation.
