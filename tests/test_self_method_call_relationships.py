from pathlib import Path

from code_steward.db import all_hard_relationships, connect
from code_steward.maintenance import rebuild_index


def _calls(root: Path):
    database = root / ".code-steward" / "index.sqlite3"
    rebuild_index(root, database)
    conn = connect(database)
    try:
        return [edge for edge in all_hard_relationships(conn) if edge.relation == "CALLS"]
    finally:
        conn.close()


def test_same_class_self_method_resolves_to_indexed_unit(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text(
        "class Worker:\n"
        "    def helper(self, value: str) -> str:\n"
        "        return value.strip()\n\n"
        "    def run(self, value: str) -> str:\n"
        "        return self.helper(value)\n",
        encoding="utf-8",
    )

    edges = _calls(root)
    matches = [
        edge
        for edge in edges
        if edge.source_unit_id == "app::Worker.run"
        and edge.target_kind == "unit"
        and edge.target_ref == "app::Worker.helper"
    ]

    assert len(matches) == 1
    assert matches[0].evidence["expressions"] == ["self.helper"]
    assert matches[0].evidence["resolutions"] == ["same-class-self"]


def test_non_self_attribute_call_remains_unresolved(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text(
        "class Worker:\n"
        "    def helper(self, value: str) -> str:\n"
        "        return value\n\n"
        "    def run(self, other, value: str) -> str:\n"
        "        return other.helper(value)\n",
        encoding="utf-8",
    )

    edges = _calls(root)
    matches = [
        (edge.target_kind, edge.target_ref)
        for edge in edges
        if edge.source_unit_id == "app::Worker.run"
    ]

    assert ("symbol", "other.helper") in matches
    assert ("unit", "app::Worker.helper") not in matches


def test_inherited_self_method_remains_unresolved(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text(
        "class Base:\n"
        "    def helper(self, value: str) -> str:\n"
        "        return value\n\n"
        "class Child(Base):\n"
        "    def run(self, value: str) -> str:\n"
        "        return self.helper(value)\n",
        encoding="utf-8",
    )

    edges = _calls(root)
    matches = [
        (edge.target_kind, edge.target_ref)
        for edge in edges
        if edge.source_unit_id == "app::Child.run"
    ]

    assert ("symbol", "self.helper") in matches
    assert ("unit", "app::Base.helper") not in matches


def test_ambiguous_same_class_method_remains_unresolved(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text(
        "class Worker:\n"
        "    # code-steward: unit worker.helper-one\n"
        "    def helper(self, value: str) -> str:\n"
        "        return value\n\n"
        "    # code-steward: unit worker.helper-two\n"
        "    def helper(self, value: str) -> str:\n"
        "        return value.strip()\n\n"
        "    def run(self, value: str) -> str:\n"
        "        return self.helper(value)\n",
        encoding="utf-8",
    )

    edges = _calls(root)
    matches = [
        (edge.target_kind, edge.target_ref)
        for edge in edges
        if edge.source_unit_id == "app::Worker.run"
    ]

    assert ("symbol", "self.helper") in matches
    assert not any(kind == "unit" and "helper" in target for kind, target in matches)


def test_nested_function_self_call_remains_unresolved(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text(
        "class Worker:\n"
        "    def helper(self, value: str) -> str:\n"
        "        return value\n\n"
        "    def run(self, value: str) -> str:\n"
        "        def inner() -> str:\n"
        "            return self.helper(value)\n"
        "        return inner()\n",
        encoding="utf-8",
    )

    edges = _calls(root)
    matches = [
        (edge.target_kind, edge.target_ref)
        for edge in edges
        if edge.source_unit_id == "app::Worker.run.inner"
    ]

    assert ("symbol", "self.helper") in matches
    assert ("unit", "app::Worker.helper") not in matches


def test_cls_method_call_is_not_resolved_by_self_rule(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text(
        "class Worker:\n"
        "    @classmethod\n"
        "    def helper(cls, value: str) -> str:\n"
        "        return value\n\n"
        "    @classmethod\n"
        "    def run(cls, value: str) -> str:\n"
        "        return cls.helper(value)\n",
        encoding="utf-8",
    )

    edges = _calls(root)
    matches = [
        (edge.target_kind, edge.target_ref)
        for edge in edges
        if edge.source_unit_id == "app::Worker.run"
    ]

    assert ("symbol", "cls.helper") in matches
    assert ("unit", "app::Worker.helper") not in matches
