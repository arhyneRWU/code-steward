"""Tests for `trace`, the function follower.

The slice is handed to a model as if it were the whole truth, so the
failures that matter are the ones that would mislead it: a silently
truncated path, a slice that looks isolated when the graph merely
failed to resolve, and a walk that wanders further than asked.
"""

from __future__ import annotations

import json

import pytest

from code_steward.cli import main
from code_steward.db import all_hard_relationships, all_units, connect
from code_steward.maintenance import rebuild_index
from code_steward.models import CodeUnit, HardRelationship
from code_steward.trace import build_slice, render_markdown

SOURCE = '''\
def leaf(value):
    """Innermost helper."""
    total = value * 2
    return total + 1


def middle(value):
    """Calls the leaf."""
    doubled = leaf(value)
    return doubled + 1


def outer(value):
    """Calls the middle."""
    result = middle(value)
    return result * 3


def bystander(value):
    """Related to nothing here."""
    return value
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "chain.py").write_text(SOURCE, encoding="utf-8")
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    return tmp_path


@pytest.fixture
def graph(project):
    conn = connect(project / ".code-steward" / "index.sqlite3")
    units = all_units(conn)
    relationships = all_hard_relationships(conn)
    conn.close()
    return units, relationships


def _roles(sliced):
    return {member.unit.unit_id: member.role for member in sliced.members}


def test_a_slice_reaches_the_caller_and_the_callee(graph):
    units, relationships = graph
    sliced = build_slice("chain::middle", units, relationships)
    roles = _roles(sliced)
    assert roles.get("chain::leaf") == "callee"
    assert roles.get("chain::outer") == "caller"


def test_depth_is_respected_in_both_directions(graph):
    units, relationships = graph
    shallow = build_slice("chain::leaf", units, relationships, callers_depth=1)
    assert "chain::outer" not in _roles(shallow)

    deep = build_slice("chain::leaf", units, relationships, callers_depth=2)
    assert _roles(deep).get("chain::outer") == "caller"


def test_an_unrelated_function_is_never_pulled_in(graph):
    units, relationships = graph
    assert "chain::bystander" not in _roles(build_slice("chain::middle", units, relationships))


def test_the_target_is_never_listed_as_its_own_neighbour(graph):
    units, relationships = graph
    sliced = build_slice("chain::middle", units, relationships, callers_depth=3, callees_depth=3)
    assert "chain::middle" not in _roles(sliced)


def test_an_unknown_unit_returns_none_rather_than_an_empty_slice(graph):
    """Empty and absent must not look the same to a caller."""
    units, relationships = graph
    assert build_slice("chain::nope", units, relationships) is None


def test_truncation_is_reported_rather_than_silent(graph, tmp_path):
    """A cut path handed over as if whole is the worst failure here."""
    units, relationships = graph
    sliced = build_slice("chain::middle", units, relationships, limit=1)
    assert sliced.truncated
    assert len(sliced.members) == 1
    assert "Truncated" in render_markdown(tmp_path, sliced)


def test_an_empty_slice_says_it_may_be_unresolved_not_isolated(tmp_path):
    """Conservative resolution makes those two indistinguishable."""
    unit = CodeUnit(
        unit_id="m::alone",
        path="m.py",
        kind="function",
        name="alone",
        qualname="alone",
        start_line=1,
        end_line=3,
    )
    sliced = build_slice("m::alone", [unit], [])
    rendered = render_markdown(tmp_path, sliced)
    assert "No resolved neighbours" in rendered
    assert "may be incomplete" in rendered


def test_tests_are_included_and_can_be_left_out(graph):
    units, relationships = graph
    extra = HardRelationship(
        source_unit_id="chain::middle",
        relation="TESTED_BY",
        target_kind="unit",
        target_ref="chain::bystander",
        provenance="test",
    )
    with_tests = build_slice("chain::middle", units, [*relationships, extra])
    assert _roles(with_tests).get("chain::bystander") == "test"

    without = build_slice("chain::middle", units, [*relationships, extra], include_tests=False)
    assert "chain::bystander" not in _roles(without)


def test_cli_trace_emits_the_body_and_json_carries_roles(project, capsys):
    assert main(["--root", str(project), "trace", "chain::middle"]) == 0
    out = capsys.readouterr().out
    assert "doubled = leaf(value)" in out
    assert "## callees" in out

    assert main(["--root", str(project), "trace", "chain::middle", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["target"] == "chain::middle"
    assert {row["role"] for row in payload["members"]} == {"caller", "callee"}


def test_cli_trace_rejects_an_unknown_unit(project, capsys):
    """Still exit 2, but the message now says what a target can be.

    A target is a unit ID, a bare name, or path:line, and a caller
    who got the form wrong needs to be told which forms exist.
    """
    assert main(["--root", str(project), "trace", "chain::nope"]) == 2
    err = capsys.readouterr().err
    assert "no unit matches" in err
    assert "path:line" in err


def test_a_caller_reports_the_line_where_it_calls(graph):
    """A follower that makes you hunt for the call is half a tool."""
    units, relationships = graph
    sliced = build_slice("chain::leaf", units, relationships)
    caller = next(m for m in sliced.members if m.unit.unit_id == "chain::middle")
    assert caller.role == "caller"
    assert caller.call_lines
    # `middle` calls `leaf` on its own line, not the target's.
    assert all(
        caller.unit.start_line <= line <= caller.unit.end_line for line in caller.call_lines
    )


def test_a_callee_reports_the_line_in_the_target_that_calls_it(graph):
    """The site belongs to whichever unit does the calling."""
    units, relationships = graph
    sliced = build_slice("chain::middle", units, relationships)
    callee = next(m for m in sliced.members if m.unit.unit_id == "chain::leaf")
    target = sliced.target
    assert callee.role == "callee"
    assert callee.call_lines
    assert all(target.start_line <= line <= target.end_line for line in callee.call_lines)


def test_call_sites_reach_the_rendered_bundle_and_the_json(project, capsys):
    assert main(["--root", str(project), "trace", "chain::leaf", "--signatures"]) == 0
    assert "calls the target at line" in capsys.readouterr().out

    assert main(["--root", str(project), "trace", "chain::leaf", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert all("call_lines" in row for row in payload["members"])


UNDOCUMENTED_SOURCE = '''\
def resolve_target(value):
    total = value * 2
    return total + 1


def caller(value):
    """Calls an undocumented helper."""
    return resolve_target(value)
'''


@pytest.fixture
def undocumented(tmp_path):
    (tmp_path / "plain.py").write_text(UNDOCUMENTED_SOURCE, encoding="utf-8")
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    conn = connect(tmp_path / ".code-steward" / "index.sqlite3")
    units = all_units(conn)
    relationships = all_hard_relationships(conn)
    conn.close()
    return tmp_path, units, relationships


def test_an_undocumented_unit_renders_no_summary(undocumented):
    """A name echo must not be rendered as though it were a docstring.

    `indexer._purpose` falls back to the function name with the
    underscores taken out, so an undocumented `resolve_target`
    carries the purpose "resolve target". Rendering that under the
    heading tells a model the function is documented when it is not.
    """
    project, units, relationships = undocumented
    sliced = build_slice("plain::caller", units, relationships)
    body = render_markdown(project, sliced, source=False)
    assert "resolve target" not in body
