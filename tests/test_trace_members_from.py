"""Assembling a slice from a member list this project did not select.

Measured on 200 Django functions: an external selector found 21
points more of the real caller set than our own conservative
resolution, at a median of 24 bytes fewer once the members were
rendered through our bundle. `docs/context-cost.md` has the run.

This is the seam that lets any selector -- their graph, grep, a
human -- drive our assembly. It must know nothing about who produced
the list.
"""

from __future__ import annotations

from pathlib import Path

from code_steward.models import CodeUnit
from code_steward.trace import (
    parse_member_refs,
    resolve_member_refs,
    slice_from_members,
)


def _unit(path: str, name: str, start: int, end: int, kind: str = "function") -> CodeUnit:
    return CodeUnit(
        unit_id=f"{path.replace('/', '.').removesuffix('.py')}::{name}",
        path=path,
        name=name,
        qualname=name,
        kind=kind,
        signature=f"{name}()",
        start_line=start,
        end_line=end,
    )


def test_a_ref_is_read_as_role_and_target() -> None:
    refs = parse_member_refs("caller:a.py::one\n\n# a comment\nb.py:12\ncallee:mod::two\n")
    assert [(ref.role, ref.ref) for ref in refs] == [
        ("caller", "a.py::one"),
        ("caller", "b.py:12"),
        ("callee", "mod::two"),
    ]


def test_every_addressing_form_resolves() -> None:
    units = [_unit("a.py", "one", 1, 4), _unit("b.py", "two", 10, 20)]
    refs = parse_member_refs("a.py::one\nb.py:12\none\n")
    resolved, unresolved = resolve_member_refs(refs, units)
    assert [unit.name for _, unit in resolved] == ["one", "two", "one"]
    assert unresolved == []


def test_an_unresolvable_ref_is_returned_not_dropped() -> None:
    units = [_unit("a.py", "one", 1, 4)]
    resolved, unresolved = resolve_member_refs(parse_member_refs("a.py::nope"), units)
    assert resolved == []
    assert unresolved == ["a.py::nope"], "a silently dropped ref is a silently wrong bundle"


def test_the_call_site_is_recomputed_from_our_own_ast(tmp_path: Path) -> None:
    """The external list carries no call sites. We have the source."""
    (tmp_path / "a.py").write_text(
        "def target():\n    return 1\n\n\ndef one():\n    x = 0\n    return target()\n",
        encoding="utf-8",
    )
    target = _unit("a.py", "target", 1, 2)
    caller = _unit("a.py", "one", 5, 7)
    sliced = slice_from_members(tmp_path, target, [("caller", caller)])
    assert [member.call_lines for member in sliced.members] == [(7,)]


def test_the_target_is_never_a_member_of_its_own_slice(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def target():\n    return 1\n", encoding="utf-8")
    target = _unit("a.py", "target", 1, 2)
    sliced = slice_from_members(tmp_path, target, [("caller", target)])
    assert sliced.members == []
