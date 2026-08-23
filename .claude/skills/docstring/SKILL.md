---
name: docstring
description: Write or review docstrings in the Code Steward codebase itself. Use when adding a function, class, or method to src/code_steward, when make docs-check reports coverage below the ratchet, or when reviewing a docstring for retrieval quality.
---

# Docstrings in Code Steward

This skill is for people and agents working **on** Code Steward. It
governs docstrings in `src/code_steward/`, `benchmarks/`, `scripts/`,
and `tests/`.

It is **not** the published plugin surface. The `skills/` directory at
the repository root is what people **using** Code Steward install. Do
not confuse the two, and do not move content between them.

## Why docstrings matter here

In most projects a docstring is documentation. In this one it is also
a **retrieval input**.

- `indexer._purpose()` reads the docstring of a function or class and
  stores it in the `CodeUnit.purpose` field.
- `search.search_units()` weights `purpose` at **0.35** — the largest
  single term in the score, ahead of `signature` (0.20), `concepts`
  (0.20), `name` (0.15), and `qualname` (0.10).
- When a unit has no docstring, `purpose` falls back to
  `node.name.replace("_", " ")`. Three of the five scoring fields
  (`purpose`, `concepts`, `name`) then collapse into re-encodings of
  the same identifier, and the unit can only be found by people who
  already know its name.

**Current limitation, stated honestly:** `_purpose()` keeps only the
first line of the docstring, truncated to 240 characters. Everything
below the summary line — description paragraphs, argument notes,
caveats — is discarded before scoring **today**. Indexing the body as
a separate scoring text is planned but not implemented. Write the body
anyway (see below); write the summary line as if it is the only thing
indexed, because right now it is.

## House conventions

1. **Imperative one-line summary.** `"""Rank indexed units against a
   coding intent."""`, not `"""Ranks units."""` and not
   `"""This function ranks units."""`. Ruff enforces the mood (`D401`),
   the period (`D400`), and the capital (`D403`).
2. **Wrap docstring lines at 72 characters.** `max-doc-length = 72` in
   `pyproject.toml` is a **line-wrap limit on this repository's own
   source**. It is not a budget on total docstring length, and it says
   nothing about the codebases Code Steward indexes — real projects
   have long multi-paragraph docstrings and that is good for
   retrieval, not bad.
3. **Plain prose.** No Sphinx roles, no reStructuredText directives,
   no `Args:`/`Returns:` section grammar. Mention a parameter inline
   when it genuinely needs explaining.
4. **Summary first, body after a blank line** (`D205`, `D212`).
5. **Do not document what the signature already says.** Types are in
   the annotations and are indexed separately.

## Write for the searcher, not for the reader who found it

The person retrieving this unit does not know its name. They type the
task they are trying to do. Your summary line is the text their query
is scored against.

- Lead with the **distinguishing behaviour** — what this unit does
  that its neighbours do not.
- Use the **words a searcher would type**: domain nouns (`route`,
  `commit`, `packet`, `region`, `tag`, `candidate`), not internal
  jargon.
- Do not restate the identifier. If every content word in the
  docstring is already in the function name, the docstring adds no
  discriminating token.

### Measured: name fallback vs generic vs real

`rapidfuzz.fuzz.token_set_ratio`, the function `search_units()` uses
for the `purpose` field.

Query: `represent an http route in the index`, target `models.Endpoint`

| `purpose` text | score |
| --- | ---: |
| `Endpoint` (no docstring, name fallback) | 22.7 |
| `Endpoint model.` (restates the name) | 31.4 |
| `One FastAPI route discovered on an indexed unit.` | **52.4** |

Query: `read code-steward comment tags out of source`,
target `markers.parse_markers_text`

| `purpose` text | score |
| --- | ---: |
| `parse markers text` (no docstring, name fallback) | 29.0 |
| `Parse the markers text.` (restates the name) | 29.9 |
| `Parse Code Steward unit tags and regions from source.` | **61.9** |

The generic docstring is worth roughly nothing over having none. The
real one roughly doubles the field score. Whole-corpus effect of the
same two edits, ranking every indexed unit for those queries:
`models.Endpoint` moved from rank 83 to rank 9, and
`markers.parse_markers_text` from rank 37 to rank 3.

### The body: vocabulary, not volume

Length itself neither helps nor hurts. `token_set_ratio` compares the
query's token set against the target's, so what matters is whether the
extra words are **words a searcher would use**.

Summary: `Parse Code Steward unit tags and regions from source.`
Body adds: *Only own-line comments recognised by the tokenizer can be
tags, so text inside a string literal is never treated as a tag.*

| query | summary only | summary + body |
| --- | ---: | ---: |
| `is a tag inside a string literal recognised` | 46.8 | **94.9** |
| `which comment lines count as tags` | 41.9 | 35.0 |

A body that carries the vocabulary of a real question doubles the
score for that question. A body that talks about something else
dilutes an unrelated query slightly. Neither is an argument for
brevity — it is an argument for writing the body in the language of
the questions the unit actually answers. (These body numbers describe
the planned behaviour; today only the summary line is indexed.)

## Worked examples from this codebase

```python
# Bad — restates the identifier, adds no searchable token.
def search_units(units, query, limit=8): ...
    """Search units."""

# Good — names the mechanism and the inputs a searcher would type.
def search_units(units, query, limit=8): ...
    """Score code units by lexical and typed metadata similarity."""
```

```python
# Bad — true, but every word is already in the name.
def file_last_commit(project_root, path): ...
    """Get the file last commit."""

# Good — says what comes back and from where.
def file_last_commit(project_root, path): ...
    """Return the short Git commit that last touched a file."""
```

```python
# Bad — Sphinx grammar this project does not use, and a summary
# that describes the arguments instead of the behaviour.
def add_region(self, unit_id, start_line, end_line): ...
    """
    :param unit_id: the region ID
    :param start_line: first line
    :param end_line: last line
    """

# Good.
def add_region(self, unit_id, start_line, end_line): ...
    """Record a tagged region spanning several declarations."""
```

## What to document first

Coverage is not the goal; retrievability is. Prioritise:

1. functions named as stable interfaces in `docs/retrieval.md` and
   `docs/relationships.md`
2. anything imported across module boundaries
3. public dataclasses in `models.py`, which carry the vocabulary of
   the whole index

Deprioritise trivial repetitive methods such as the `to_dict()`
family. Documenting them raises the coverage number without making
anything easier to find.

## Verification checklist

Before you call a docstring done:

- [ ] First line is one imperative sentence ending in a period.
- [ ] The summary names behaviour a searcher would describe, not the
      identifier spelled out in words.
- [ ] At least one content word in the summary is **not** already in
      the function or class name.
- [ ] Any body text uses the vocabulary of questions this unit
      answers, and is separated from the summary by a blank line.
- [ ] No Sphinx roles, RST directives, or `Args:` sections.
- [ ] Docstring lines wrap at 72 characters.
- [ ] `make lint` passes (`D200`–`D419` subset is enforced).
- [ ] `make docs-check` passes and coverage did not fall.
- [ ] If coverage improved, `make docs-check-update` was run and
      `scripts/docstring_baseline.json` is part of the change.
