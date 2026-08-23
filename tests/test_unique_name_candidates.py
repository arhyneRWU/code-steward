"""Selecting the call sites the unique-name rule would resolve.

The rule is only safe where the name is unambiguous, so the selection
is where it can go wrong: one extra candidate whose name is not
actually unique is a wrong edge with a plausible-looking provenance.
"""

from __future__ import annotations

from pathlib import Path

from benchmarks.unique_name.candidates import Candidate, attribute_call_sites, unique_names
from code_steward.models import CodeUnit


def _unit(path: str, name: str, start: int, end: int) -> CodeUnit:
    return CodeUnit(
        unit_id=f"{path}::{name}",
        path=path,
        name=name,
        qualname=name,
        kind="function",
        signature=f"{name}()",
        start_line=start,
        end_line=end,
    )


def test_only_names_held_by_exactly_one_unit_are_unique() -> None:
    units = [
        _unit("a.py", "solo", 1, 2),
        _unit("b.py", "shared", 1, 2),
        _unit("c.py", "shared", 1, 2),
    ]
    assert unique_names(units) == {"solo"}


def test_a_call_site_is_found_with_its_line_and_column(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(
        "def caller(obj):\n    return obj.solo()\n",
        encoding="utf-8",
    )
    sites = attribute_call_sites(tmp_path, [Path("m.py")], {"solo"})
    assert sites == [Candidate(path="m.py", line=2, column=15, attribute="solo", caller="caller")]


def test_a_plain_call_is_not_a_candidate(tmp_path: Path) -> None:
    """`solo()` already resolves. Only `obj.solo()` is in scope."""
    (tmp_path / "m.py").write_text("def caller():\n    return solo()\n", encoding="utf-8")
    assert attribute_call_sites(tmp_path, [Path("m.py")], {"solo"}) == []


def test_an_ambiguous_attribute_is_not_a_candidate(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("def caller(obj):\n    return obj.shared()\n", encoding="utf-8")
    assert attribute_call_sites(tmp_path, [Path("m.py")], {"solo"}) == []
