# Code Steward tag protocol

This document records the current **draft** tag semantics being tested in PR #1. The syntax is not stable until the pull request is accepted.

## Design goals

Code Steward should use native parsers wherever a language already provides a reliable declaration boundary. Source tags should add identity or conceptual grouping, not duplicate information that the language can derive.

The protocol payload is intended to be language-neutral. A language adapter supplies the native comment delimiter. Python uses `#` comments:

```python
# code-steward: unit taxonomy.normalize
```

A future JavaScript adapter could represent the same payload as:

```javascript
// code-steward: unit taxonomy.normalize
```

The comment wrapper is language-specific. The `code-steward:` payload is the shared protocol.

## Python declaration aliases

Ordinary Python functions and classes require no tag. Their IDs can be generated from the module and qualified symbol name.

A `unit` tag gives the next declaration a stable semantic ID:

```python
# code-steward: unit taxonomy.normalize
@cached
def normalize_taxon(name: str) -> Taxon:
    """Resolve a supplied name to an accepted taxon."""
    ...
```

For Python, a `unit` tag:

- must immediately precede the declaration or its first decorator
- must use the same indentation as the declaration
- may attach to a function, async function, or class
- replaces the generated module/symbol ID for that indexed unit
- does **not** create an additional search candidate
- is not part of the declaration's content hash

Semantic IDs are repository-wide identities. Two different files cannot claim the same Code Steward ID.

Human-facing documentation remains in normal Python docstrings.

## Conceptual regions

Paired `begin` and `end` tags define a conceptual region that cannot be expressed as one native declaration:

```python
# code-steward: begin taxonomy.validation


def validate_name(name: str) -> None: ...


def validate_rank(rank: str) -> None: ...


# code-steward: end taxonomy.validation
```

A conceptual region is indexed in addition to any native declarations inside it. This duplication is intentional because the region represents a different abstraction.

The marker lines themselves are excluded from the region's source boundary and content hash.

## Boundaries and hashes

For a decorated Python declaration, the code boundary starts at the first decorator and ends at the declaration's AST `end_lineno`.

```text
unit tag             metadata only, excluded from hash
first decorator      included
other decorators     included
def / class           included
body                  included
```

Changing only a `unit` ID therefore changes identity without pretending that the implementation changed.

For conceptual regions, the content hash covers only the source between the `begin` and `end` marker lines.

Hashes and Git commit IDs are generated index metadata. They must never be written into source tags or maintained by a coding model.

## Validation

The Python adapter and repository index should reject:

- unmatched or mismatched region markers
- unclosed regions
- `unit` tags that are not attached to a declaration
- incorrectly indented `unit` tags
- duplicate Code Steward IDs within a file
- duplicate Code Steward IDs claimed by different files

A cross-file conflict must fail before existing index data is mutated. Future validation may also report likely accidental semantic-ID renames across revisions.

## Deliberate non-features

The draft protocol does not include source-maintained fields such as `purpose`, `owns`, `not-own`, hashes, Git SHAs, line counts, callers, or dependencies. Those belong in docstrings or generated index metadata.
