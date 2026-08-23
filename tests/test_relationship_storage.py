from pathlib import Path

import pytest

from code_steward.db import (
    all_hard_relationships,
    all_soft_relationships,
    connect,
    replace_file,
    replace_hard_relationships,
    replace_soft_relationships,
)
from code_steward.models import CodeUnit, HardRelationship, SoftRelationship


def _unit(unit_id: str, path: str, body_hash: str) -> CodeUnit:
    return CodeUnit(
        unit_id=unit_id,
        path=path,
        kind="function",
        name=unit_id.split(".")[-1],
        qualname=unit_id,
        start_line=1,
        end_line=2,
        body_hash=body_hash,
    )


def _seed(conn) -> None:
    replace_file(conn, "a.py", [_unit("a.source", "a.py", "hash-a")], [])
    replace_file(conn, "b.py", [_unit("b.target", "b.py", "hash-b")], [])


def test_hard_relationships_support_unit_and_external_targets(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    _seed(conn)

    replace_hard_relationships(
        conn,
        "a.source",
        [
            HardRelationship(
                "a.source",
                "CALLS",
                "unit",
                "b.target",
                "python-ast",
                {"call": "target"},
            ),
            HardRelationship(
                "a.source",
                "IMPORTS",
                "module",
                "json",
                "python-ast",
                {"alias": ""},
            ),
        ],
    )

    relationships = all_hard_relationships(conn)
    assert [(edge.relation, edge.target_kind, edge.target_ref) for edge in relationships] == [
        ("CALLS", "unit", "b.target"),
        ("IMPORTS", "module", "json"),
    ]
    assert relationships[0].source_hash == "hash-a"
    assert relationships[0].target_hash == "hash-b"
    assert relationships[1].source_hash == "hash-a"
    assert relationships[1].target_hash == ""


def test_soft_relationships_store_score_provenance_evidence_and_hashes(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    _seed(conn)

    replace_soft_relationships(
        conn,
        "a.source",
        [
            SoftRelationship(
                "a.source",
                "SIMILAR_TO",
                "b.target",
                0.82,
                "metadata-v1",
                {"purpose": 0.9, "signature": 0.4},
            )
        ],
    )

    relationship = all_soft_relationships(conn)[0]
    assert relationship.score == pytest.approx(0.82)
    assert relationship.provenance == "metadata-v1"
    assert relationship.evidence == {"purpose": 0.9, "signature": 0.4}
    assert relationship.source_hash == "hash-a"
    assert relationship.target_hash == "hash-b"


def test_hard_and_soft_relationships_are_stored_independently(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    _seed(conn)

    replace_hard_relationships(
        conn,
        "a.source",
        [HardRelationship("a.source", "CALLS", "unit", "b.target", "python-ast")],
    )
    replace_soft_relationships(
        conn,
        "a.source",
        [SoftRelationship("a.source", "RELATED_TO", "b.target", 0.7, "metadata-v1")],
    )

    assert len(all_hard_relationships(conn)) == 1
    assert len(all_soft_relationships(conn)) == 1


def test_reindexing_related_unit_invalidates_relationship_cache(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    _seed(conn)

    replace_hard_relationships(
        conn,
        "a.source",
        [HardRelationship("a.source", "CALLS", "unit", "b.target", "python-ast")],
    )
    replace_soft_relationships(
        conn,
        "a.source",
        [SoftRelationship("a.source", "SIMILAR_TO", "b.target", 0.82, "metadata-v1")],
    )

    replace_file(conn, "b.py", [_unit("b.target", "b.py", "hash-b2")], [])

    assert all_hard_relationships(conn) == []
    assert all_soft_relationships(conn) == []


def test_invalid_hard_relationship_does_not_replace_valid_edges(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    _seed(conn)
    valid = HardRelationship("a.source", "IMPORTS", "module", "json", "python-ast")
    replace_hard_relationships(conn, "a.source", [valid])

    with pytest.raises(ValueError, match="Unknown Code Steward unit ID"):
        replace_hard_relationships(
            conn,
            "a.source",
            [HardRelationship("a.source", "CALLS", "unit", "missing.unit", "python-ast")],
        )

    assert [(edge.relation, edge.target_ref) for edge in all_hard_relationships(conn)] == [
        ("IMPORTS", "json")
    ]


def test_invalid_soft_score_does_not_replace_valid_edges(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    _seed(conn)
    valid = SoftRelationship("a.source", "SIMILAR_TO", "b.target", 0.8, "metadata-v1")
    replace_soft_relationships(conn, "a.source", [valid])

    with pytest.raises(ValueError, match="between 0 and 1"):
        replace_soft_relationships(
            conn,
            "a.source",
            [SoftRelationship("a.source", "SIMILAR_TO", "b.target", 1.2, "metadata-v1")],
        )

    assert all_soft_relationships(conn)[0].score == pytest.approx(0.8)
