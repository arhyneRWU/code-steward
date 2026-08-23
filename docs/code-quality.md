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

It also includes a subset of pydocstyle (`D`) rules covering docstring
formatting and consistency:

- `D200`, `D201`, `D202`, `D204`, `D205`, `D207`, `D208`, `D209`, `D210`,
  `D211`, `D212`: docstring layout, indentation, and blank lines
- `D400`, `D401`, `D402`, `D403`, `D404`: imperative one-line summary that
  ends with a period, is capitalized, is not the signature, and does not
  begin with "This"
- `D418`, `D419`: no docstring on an `@overload` stub, and no empty
  docstring

Every one of those rules passes with zero violations today, so they cost
no cleanup and prevent style drift from here on.

The following `D` rules are deliberately deferred:

- `D1xx` (missing docstrings). Package docstring coverage is currently
  31%. Enabling `D100`-`D107` today would fail on most of the codebase.
  Coverage is instead governed by the ratchet in `make docs-check`, which
  lets coverage rise without a flag-day rewrite.
- `D203` and `D213`. Both are mutually exclusive with rules we prefer
  (`D211` and `D212`).
- `D206` and `D300`. The Ruff formatter already owns indentation style
  and quote style; selecting them duplicates the formatter.
- `D405`-`D417`, `D214`, `D215`. These govern `Args:`/`Returns:` section
  grammar. Code Steward docstrings are plain imperative prose with no
  section headers, so these rules are inert here.
- `D415`. Redundant with the stricter `D400`.

We are intentionally not enabling every Ruff rule family yet. New rule families should be introduced deliberately, with existing violations reviewed rather than hidden by broad ignores.

## Docstrings and machine-readable tags

Human-facing function and class documentation belongs in normal Python docstrings and should follow PEP 257 conventions. Code Steward tags are machine-readable boundary or identity metadata, not a replacement for docstrings.

Docstrings in this project are also a **retrieval input**, not only
human documentation. `indexer._purpose()` stores the docstring summary
line in the `purpose` field of an indexed unit, and `purpose` carries the
largest single weight in `search.search_units`. A unit with no docstring
falls back to its own name, so it can only be found by someone who
already knows what it is called. Contributor guidance for writing
docstrings that retrieve well lives in `.claude/skills/docstring/SKILL.md`.

The tag syntax is currently experimental. Tests on the `test/tag-conventions` branch characterize how candidate tag forms interact with Python's AST and tokenizer before the syntax is declared stable.

For normal Python functions and classes, AST-derived boundaries remain authoritative. Explicit tags should only add information that Python syntax cannot already express cleanly, such as a conceptual region spanning several symbols or a stable architectural alias.

## CI gates

Pull requests run two groups of checks.

### Quality

On Python 3.14:

1. `ruff check`
2. `ruff format --check`
3. `python scripts/docs_check.py`
4. `python -m compileall -q src tests`
5. `python -m code_steward --help`
6. `python -m pip check`

### Compatibility tests

On every supported Python version from 3.10 through 3.14:

1. install the package with test dependencies
2. run `python -m pytest -q`
3. run `python -m pip check`

## Documentation checks

`make docs-check` runs `scripts/docs_check.py`, which enforces three
things and is wired into CI as its own `Docs` job.

**Docstring coverage with a ratchet.** Coverage is measured for
`src/code_steward` overall and per module and compared against
`scripts/docstring_baseline.json`. The check fails if coverage falls
below the committed number. It does not require any particular target.
Raise the ratchet with `make docs-check-update` in the same change that
raises coverage; never lower it by hand.

**Documented commands exist.** Every shell command quoted in `README.md`,
`CONTRIBUTING.md`, `docs/*.md`, `benchmarks/*/README.md`, and the Claude
asset directories is parsed. Each `code-steward <subcommand>` must be a
real subcommand of the argparse parser, each `make <target>` must be a
real Makefile target, every module run with `python -m` must import,
and every script path must exist.

Only two commands are actually executed: `python -m code_steward --help`
and `make -n help`. Those are read-only, take under a second, and prove
that the console script and the Makefile really load. Everything else
documented here builds an index, writes into the repository, clones an
upstream project, or takes minutes, so it is verified statically. The
line is drawn at side effects and runtime, not at importance.

**Documented symbols resolve.** Backtick-quoted dotted identifiers rooted
at a package module (for example `retrieval.rank_units`) are imported and
resolved. Bare names are only checked when written as a call such as
`retrieve_units()` or when listed in the script's explicit allowlist of
promised API names. Prose contains far too many ordinary words to check
every backtick span, so the check deliberately under-reports rather than
producing noise.

## Checks not yet enforced

Standalone Pylint and a static type checker such as mypy or Pyright are not blocking CI yet. Ruff already covers many Pylint-derived checks, and the type-analysis policy should be chosen after the public data model and plugin interfaces settle enough to make the signal useful.

Those tools can be added later as separate, justified quality gates rather than as overlapping dependencies added by default.

## Type checking

`make types` runs mypy over `src` and `benchmarks`; CI runs it in the
lint job.

It is deliberately not strict. The value it earns is narrow and
specific: **catching a call that cannot work** -- a wrong argument
count, a name used before it exists -- in code the test suite does
not execute.

That matters because of where this project's defects live. The
benchmark layer is larger than the product (2,517 statements against
1,953) and half covered (50.1% against 89.7%), and running most of it
needs pinned corpora that CI does not have. When `load_units` gained
a required parameter, **three callers were left broken and merged to
main while 331 tests passed**, because nothing executes them without
a corpus. mypy found all three in under a minute, on a codebase that
had never been type-checked.

The whole baseline was twelve findings: three real breakages and
five pieces of typing hygiene. That is cheap enough that leaving it
off was the more expensive choice.

Coverage is the wrong instrument for this. Every one of the defects
found on 2026-08-23 executed its lines -- the shingle cache wrote its
rows, the introduced-only filter ran its comparison, `render_markdown`
rendered its purpose, `load_units` recorded every exclusion. What
they had in common was a value computed and then discarded or
misused, with plausible output. Raising coverage would not have
caught one of them.
