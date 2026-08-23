"""The context-cost harness, on the parts that can be got wrong quietly.

Byte accounting and claim confirmation both fail silently: a
double-counted span or a claim confirmed by a name collision looks
exactly like a real number.
"""

from __future__ import annotations

from pathlib import Path

from benchmarks.context_cost.arms import (
    GcrNode,
    confirmed_claims,
    span_bytes,
)


def _node(path: str, name: str, start: int, end: int) -> GcrNode:
    return GcrNode(
        name=name,
        qualified_name=f"{path}::{name}",
        path=path,
        start_line=start,
        end_line=end,
        kind="Function",
    )


def test_overlapping_spans_are_counted_once(tmp_path: Path) -> None:
    source = tmp_path / "m.py"
    source.write_text("\n".join(f"line {i}" for i in range(1, 21)), encoding="utf-8")
    nodes = [_node("m.py", "a", 1, 10), _node("m.py", "b", 5, 10)]
    once = span_bytes(tmp_path, [nodes[0]])
    both = span_bytes(tmp_path, nodes)
    assert both == once, "an agent reads a line once, not once per node claiming it"


def test_a_claim_is_confirmed_only_when_the_call_is_there(tmp_path: Path) -> None:
    source = tmp_path / "m.py"
    source.write_text(
        "def caller():\n"
        "    return target()\n"
        "\n"
        "def bystander():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    claims = [_node("m.py", "caller", 1, 2), _node("m.py", "bystander", 4, 5)]
    confirmed = confirmed_claims(tmp_path, "target", claims)
    assert [node.name for node in confirmed] == ["caller"]


def test_the_caller_key_is_built_without_either_graph(tmp_path: Path) -> None:
    """The key must be able to contradict both tools.

    A union of the tools' own claims cannot: where one tool returns
    nothing, the other scores 1.0 by construction. That is what the
    smoke test found, and this is the replacement.
    """
    from benchmarks.context_cost.arms import caller_index

    (tmp_path / "a.py").write_text(
        "def target():\n    return 1\n\ndef caller():\n    return target()\n",
        encoding="utf-8",
    )
    (tmp_path / "b.py").write_text(
        "def far_caller():\n    return target()\n\ndef stranger():\n    return 2\n",
        encoding="utf-8",
    )
    index = caller_index(tmp_path, [Path("a.py"), Path("b.py")])
    assert index["target"] == {("a.py", "caller"), ("b.py", "far_caller")}
    assert "stranger" not in {name for pair in index.values() for _, name in pair}
