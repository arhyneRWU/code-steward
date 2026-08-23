# Configuration

Code Steward reads optional project settings from the
`[tool.code-steward]` table of `pyproject.toml` at the project root.

## `exclude`

A list of path fragments that must never be indexed. A fragment
matches when it appears anywhere in a file's POSIX path.

```toml
[tool.code-steward]
exclude = [
    "tests/fixtures",
    "benchmarks/retrieval/fixture_repo",
]
```

This is how a repository keeps fixture trees out of its own index.
Fixtures intentionally declare duplicate unit IDs, and the indexer
correctly refuses to index two files that claim the same ID, so a
fixture tree must be excluded rather than tolerated.

Configured excludes apply to both `code-steward build` and
`code-steward update`, so `code-steward build` works with no flags.

### Relationship to `--exclude`

`--exclude` is repeatable on `build` and `update` and is **added to**
the configured list, never a replacement for it:

```bash
code-steward build --exclude scratch   # config excludes + "scratch"
```

### Always-skipped directories

Independently of configuration, these directory names are skipped
wherever they appear: `.git`, `.venv`, `venv`, `__pycache__`,
`.code-steward`, `.code-review-graph`, and `.claude` (agent tooling
creates git worktrees under `.claude/worktrees/`, which are full
copies of the repository).

### TOML support

`tomllib` is stdlib from Python 3.11. On Python 3.10 Code Steward
uses the `tomli` backport, declared as an environment-conditional
dependency, so no extra package is installed on 3.11+. If neither
module is importable, configuration is silently treated as empty
rather than failing the build.

### Validation

Configuration that is present but wrong is an error, not a warning.
An `exclude` that is not a list of non-empty strings, or a
`pyproject.toml` that cannot be parsed, fails the command with the
file named:

```text
build failed: pyproject.toml: [tool.code-steward] exclude must be a
list of strings, got str
```

Silently ignoring a mistyped `exclude` would surface later as an
unrelated indexing failure, which is exactly the debugging problem
persistent excludes exist to remove. A project with no
`pyproject.toml`, or one with no `[tool.code-steward]` table, is not
an error and simply configures no excludes.
