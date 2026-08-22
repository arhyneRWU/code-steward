# Contributing to Code Steward

Code Steward is in early development. Contributions are welcome, especially those that improve context efficiency, code stewardship, retrieval quality, and the reliability of agent decisions.

## Before opening a change

For substantial changes, please open an issue first so the design can be discussed before implementation. Small documentation fixes and narrowly scoped corrections can go directly to a pull request.

Good early contribution areas include:

- Python AST indexing and stable code-unit identity
- FastAPI route and dependency mapping
- low-context candidate retrieval
- fuzzy, typed, and structural matching
- Graph Code Review integration
- duplicate-code and reuse analysis
- isolated reviewer-agent workflows
- tests and benchmarks for context use and decision quality

## Development principles

Changes should follow the same principles Code Steward is intended to enforce:

- search for existing behavior before adding parallel implementations
- prefer small, focused changes over broad rewrites
- keep deterministic analysis outside model context when practical
- avoid adding abstractions solely to eliminate superficial duplication
- preserve clear boundaries between indexing, retrieval, graph analysis, and agent reasoning
- include tests for behavior that can be tested deterministically
- document important architectural decisions and external dependencies

## Pull requests

Keep pull requests focused on one coherent change. A good pull request should explain:

1. what problem it addresses
2. why the chosen approach is appropriate
3. how it was tested
4. whether it changes context use, retrieval behavior, or public interfaces

Commit messages should be concise but informative. Prefer messages such as:

```text
feat: add AST function indexing
fix: preserve async function boundaries
docs: explain reviewer packet format
test: cover tagged code-unit extraction
```

Avoid very long commit subjects or commits that combine unrelated work.

## Public project expectations

Do not commit secrets, credentials, private datasets, proprietary code, or repository-specific material that cannot be redistributed publicly.

When adding examples, use synthetic or openly redistributable code and data. Clearly attribute third-party projects, specifications, and borrowed ideas where appropriate.

## Tests

New deterministic behavior should include tests when practical. As the project matures, automated formatting, linting, type checking, and CI requirements will be documented here.

## Licensing

By contributing to Code Steward, you agree that your contributions will be licensed under the repository's MIT License.
