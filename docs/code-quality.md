# Code quality policy

Code Steward treats code quality checks as part of the public interface. The goal is not to enable every available lint rule. The goal is to define a small, reproducible contract that catches correctness and maintainability problems without forcing unnecessary style churn.

## Supported Python versions

The package currently declares Python 3.10 or newer. CI therefore runs the test suite on Python 3.10, 3.11, 3.12, 3.13, and 3.14.

If the minimum supported Python version changes, the CI matrix and Ruff target version should change in the same pull request.

## Formatting

Ruff is the project formatter. Code Steward does not also run Black, because two formatters with overlapping responsibility add maintenance cost without improving the result.

Current formatting rules:

- spaces for indentation
- double quotes
- LF line endings
- 99-character maximum code line length
- code examples inside docstrings may be formatted by Ruff

PEP 8 recommends 79 characters by default but explicitly permits a team-agreed limit up to 99 characters. Code Steward uses that upper bound to balance readable diffs with modern typed Python signatures.

Comments and docstrings should generally remain within 72 characters. Ruff's `W505` check is enabled for this purpose.

## Linting

Ruff is pinned for reproducibility. The project explicitly selects lint rule families instead of relying on Ruff defaults, because default rule sets can change between Ruff releases.

The initial contract includes:

- `E4`, `E7`, `E9`: core pycodestyle errors
- `E501`: code line length
- `W505`: comment and docstring line length
- `F`: Pyflakes correctness checks
- `I`: import ordering
- `UP`: safe modernization for the minimum Python version
- `B`: likely bugs and design mistakes from flake8-bugbear
- `SIM`: straightforward simplifications
- `PLE`: Pylint error-class checks implemented by Ruff
- `RUF`: Ruff-specific correctness checks

We are intentionally not enabling every Ruff rule family yet. New rule families should be introduced deliberately, with existing violations reviewed rather than hidden by broad ignores.

## Docstrings and machine-readable tags

Human-facing function and class documentation belongs in normal Python docstrings and should follow PEP 257 conventions. Code Steward tags are machine-readable boundary or identity metadata, not a replacement for docstrings.

The tag syntax is currently experimental. Tests on the `test/tag-conventions` branch characterize how candidate tag forms interact with Python's AST and tokenizer before the syntax is declared stable.

For normal Python functions and classes, AST-derived boundaries remain authoritative. Explicit tags should only add information that Python syntax cannot already express cleanly, such as a conceptual region spanning several symbols or a stable architectural alias.

## CI gates

Pull requests run two groups of checks.

### Quality

On Python 3.14:

1. `ruff check`
2. `ruff format --check`
3. `python -m compileall -q src tests`
4. `python -m code_steward --help`
5. `python -m pip check`

### Compatibility tests

On every supported Python version from 3.10 through 3.14:

1. install the package with test dependencies
2. run `python -m pytest -q`
3. run `python -m pip check`

## Checks not yet enforced

Standalone Pylint and a static type checker such as mypy or Pyright are not blocking CI yet. Ruff already covers many Pylint-derived checks, and the type-analysis policy should be chosen after the public data model and plugin interfaces settle enough to make the signal useful.

Those tools can be added later as separate, justified quality gates rather than as overlapping dependencies added by default.
