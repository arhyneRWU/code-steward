"""Tests for selecting the functions that need a docstring written.

The selector is the whole reason this half of the design survived
measurement: every heuristic for finding *drifted* docstrings failed,
but "has no docstring" is exact. So the failures that matter here are
a unit offered for documentation that already has one, and a unit
offered that nobody would ever want documented.
"""

from __future__ import annotations

import pytest

from code_steward.cli import main
from code_steward.db import all_units, connect
from code_steward.maintenance import rebuild_index
from code_steward.trace import undocumented_units

SOURCE = '''\
def documented(value):
    """Already has a docstring."""
    total = value * 2
    return total + 1


def undocumented_helper(value):
    total = value * 2
    return total + 1
'''


@pytest.fixture
def units(tmp_path):
    (tmp_path / "mixed.py").write_text(SOURCE, encoding="utf-8")
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    conn = connect(tmp_path / ".code-steward" / "index.sqlite3")
    found = all_units(conn)
    conn.close()
    return found


def test_only_functions_without_a_docstring_are_selected(units):
    selected = [unit.unit_id for unit in undocumented_units(units)]
    assert selected == ["mixed::undocumented_helper"]


TRIVIAL_SOURCE = """\
class Thing:
    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = value

    def __repr__(self):
        return "Thing()"


def worth_documenting(value):
    total = value * 2
    scaled = total + 1
    return scaled * 3
"""


@pytest.fixture
def trivial(tmp_path):
    (tmp_path / "trivial.py").write_text(TRIVIAL_SOURCE, encoding="utf-8")
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    conn = connect(tmp_path / ".code-steward" / "index.sqlite3")
    found = all_units(conn)
    conn.close()
    return found


def test_dunder_methods_are_not_offered(trivial):
    """Nobody wants a generated docstring on `__repr__`."""
    selected = [unit.name for unit in undocumented_units(trivial)]
    assert "__repr__" not in selected


def test_property_accessors_are_not_offered(trivial):
    """A property reads as an attribute; documenting it is noise."""
    selected = [unit.name for unit in undocumented_units(trivial)]
    assert "name" not in selected


def test_a_body_too_small_to_describe_is_not_offered(trivial):
    """A one-line return has nothing a docstring could add.

    This repository defers the missing-docstring rules on purpose
    (see `docs/code-quality.md`), so blanket coverage that emits
    "Return the name." is noise that buries the real docstrings.
    """
    selected = [unit.name for unit in undocumented_units(trivial)]
    assert selected == ["worth_documenting"]


CLI_SOURCE = """\
def resolve_target(value):
    total = value * 2
    return total + 1


def caller(value):
    \"\"\"Calls an undocumented helper.\"\"\"
    return resolve_target(value)
"""


@pytest.fixture
def cli_project(tmp_path):
    (tmp_path / "app.py").write_text(CLI_SOURCE, encoding="utf-8")
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    return tmp_path


def test_undocumented_emits_a_bundle_for_each_selected_function(cli_project, capsys):
    """One complete slice per function that needs a docstring.

    That is the whole point of the surviving half of the design.
    """
    assert main(["--root", str(cli_project), "trace", "--undocumented"]) == 0
    out = capsys.readouterr().out
    assert "# app::resolve_target" in out
    assert "## callers" in out
    assert "app::caller" in out


def test_undocumented_reports_when_nothing_needs_a_docstring(tmp_path, capsys):
    """An empty result is an answer, not a failure to produce output.

    Silence reads as "the command broke".
    """
    (tmp_path / "done.py").write_text(
        'def thorough(value):\n    """Documented."""\n    total = value * 2\n'
        "    return total + 1\n",
        encoding="utf-8",
    )
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    assert main(["--root", str(tmp_path), "trace", "--undocumented"]) == 0
    assert "no undocumented functions" in capsys.readouterr().out
