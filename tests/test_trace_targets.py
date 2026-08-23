"""Naming a target the way you actually have it to hand.

`trace` took a unit ID and nothing else, which is a real gap in the
pipeline: grep gives you a file and a line, a traceback gives you a
function name, and neither is a unit ID. There was no way to get from
"I know roughly where this is" to a slice without already knowing the
index's own naming scheme.

Resolution here is deterministic on purpose. It matches or it does
not, and an ambiguous query lists what it found rather than picking.
Ranking a shortlist is the one thing this project has measured itself
into never doing.
"""

from __future__ import annotations

import pytest

from code_steward.cli import main
from code_steward.maintenance import rebuild_index

SOURCE = '''\
def normalise(name):
    """Strip and case-fold a submitted name."""
    cleaned = name.strip()
    lowered = cleaned.lower()
    return lowered


def persist(name):
    """Write the record and return it."""
    key = normalise(name)
    record = {"name": key}
    return record
'''

OTHER = '''\
def normalise(value):
    """A second function with the same bare name."""
    trimmed = str(value).strip()
    return trimmed.upper()
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "core.py").write_text(SOURCE, encoding="utf-8")
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    return tmp_path


@pytest.fixture
def ambiguous(tmp_path):
    (tmp_path / "core.py").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "other.py").write_text(OTHER, encoding="utf-8")
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    return tmp_path


def test_a_bare_function_name_resolves(project, capsys):
    """What a traceback or a code review comment gives you."""
    assert main(["--root", str(project), "trace", "normalise"]) == 0
    assert "# core::normalise" in capsys.readouterr().out


def test_a_path_and_line_resolves(project, capsys):
    """What grep gives you."""
    assert main(["--root", str(project), "trace", "core.py:8"]) == 0
    assert "# core::persist" in capsys.readouterr().out


def test_a_line_inside_the_body_resolves(project, capsys):
    """You rarely land on the `def` line itself."""
    assert main(["--root", str(project), "trace", "core.py:10"]) == 0
    assert "# core::persist" in capsys.readouterr().out


def test_a_unit_id_still_resolves(project, capsys):
    assert main(["--root", str(project), "trace", "core::persist"]) == 0
    assert "# core::persist" in capsys.readouterr().out


def test_an_ambiguous_name_lists_candidates_rather_than_choosing(ambiguous, capsys):
    """Picking one would be ranking, which this project does not do."""
    assert main(["--root", str(ambiguous), "trace", "normalise"]) == 2
    err = capsys.readouterr().err
    assert "core::normalise" in err
    assert "other::normalise" in err


def test_an_unknown_target_says_so(project, capsys):
    assert main(["--root", str(project), "trace", "nope"]) == 2
    assert "no unit matches" in capsys.readouterr().err
