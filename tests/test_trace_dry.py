"""DRY across a whole traced path, not just the functions you changed.

The pipeline this serves is search, then follow the path, then check
the path for duplication -- and until now the two halves did not
compose. `check` worked on changed files and `trace` emitted a slice,
so nothing ever ran duplication across the path a function sits on.
"""

from __future__ import annotations

import json

import pytest

from code_steward.cli import main
from code_steward.maintenance import rebuild_index

# `middle` and `sibling` have the same body. A duplicate that only a
# path-level pass finds: nobody changed `sibling`, so `check` would
# never look at it, and `trace` would show it without noticing.
SOURCE = '''\
def leaf(rows, limit):
    """Innermost helper."""
    total = 0
    for key, value in rows.items():
        if value is None:
            continue
        total += value
    return total, limit


def middle(rows, limit):
    """Calls the leaf."""
    scored = []
    for key, value in rows.items():
        if value is None:
            continue
        scored.append((key, value))
    scored.sort(key=lambda row: -row[1])
    return leaf(dict(scored), limit)


def sibling(rows, limit):
    """A near-copy of middle, unchanged and uncalled by the target."""
    scored = []
    for key, value in rows.items():
        if value is None:
            continue
        scored.append((key, value))
    scored.sort(key=lambda row: -row[1])
    return leaf(dict(scored), limit)


def outer(rows, limit):
    """Calls the middle."""
    result = middle(rows, limit)
    return result
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "chain.py").write_text(SOURCE, encoding="utf-8")
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    return tmp_path


def test_dry_reports_a_duplicate_of_a_function_on_the_path(project, capsys):
    """The finding no existing command could produce.

    `sibling` duplicates `middle`, which is on `outer`'s path.
    `check` never looks at it because nothing changed, and plain
    `trace` lists the path without comparing it to anything.
    """
    assert main(["--root", str(project), "trace", "chain::outer", "--dry"]) == 0
    out = capsys.readouterr().out
    assert "## duplication" in out
    assert "chain::sibling" in out


def test_dry_is_absent_unless_asked_for(project, capsys):
    assert main(["--root", str(project), "trace", "chain::outer"]) == 0
    assert "## duplication" not in capsys.readouterr().out


def test_dry_reaches_the_json(project, capsys):
    assert main(["--root", str(project), "trace", "chain::outer", "--dry", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["duplication"]
