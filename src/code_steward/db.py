from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import CodeUnit, Endpoint, HardRelationship, SoftRelationship

SCHEMA = """
CREATE TABLE IF NOT EXISTS units (
    unit_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    qualname TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    signature TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    returns TEXT NOT NULL,
    purpose TEXT NOT NULL,
    doc_text TEXT NOT NULL DEFAULT '',
    concepts_json TEXT NOT NULL,
    decorators_json TEXT NOT NULL,
    dependencies_json TEXT NOT NULL,
    owns_json TEXT NOT NULL,
    not_owns_json TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    git_file_commit TEXT NOT NULL,
    explicit_region INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_units_path ON units(path);
CREATE INDEX IF NOT EXISTS idx_units_name ON units(name);
CREATE INDEX IF NOT EXISTS idx_units_kind ON units(kind);

CREATE TABLE IF NOT EXISTS endpoints (
    unit_id TEXT NOT NULL,
    path TEXT NOT NULL,
    method TEXT NOT NULL,
    route TEXT NOT NULL,
    response_model TEXT NOT NULL,
    dependencies_json TEXT NOT NULL,
    PRIMARY KEY(unit_id, method, route)
);
CREATE INDEX IF NOT EXISTS idx_endpoints_route ON endpoints(route);

CREATE TABLE IF NOT EXISTS hard_relationships (
    source_unit_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    provenance TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    target_hash TEXT NOT NULL,
    PRIMARY KEY(source_unit_id, relation, target_kind, target_ref, provenance)
);
CREATE INDEX IF NOT EXISTS idx_hard_relationships_source
    ON hard_relationships(source_unit_id);
CREATE INDEX IF NOT EXISTS idx_hard_relationships_target
    ON hard_relationships(target_kind, target_ref);
CREATE INDEX IF NOT EXISTS idx_hard_relationships_relation
    ON hard_relationships(relation);

CREATE TABLE IF NOT EXISTS soft_relationships (
    source_unit_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    target_unit_id TEXT NOT NULL,
    score REAL NOT NULL CHECK(score >= 0.0 AND score <= 1.0),
    provenance TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    target_hash TEXT NOT NULL,
    PRIMARY KEY(source_unit_id, relation, target_unit_id, provenance)
);
CREATE INDEX IF NOT EXISTS idx_soft_relationships_source
    ON soft_relationships(source_unit_id);
CREATE INDEX IF NOT EXISTS idx_soft_relationships_target
    ON soft_relationships(target_unit_id);
CREATE INDEX IF NOT EXISTS idx_soft_relationships_relation
    ON soft_relationships(relation);
"""

FileReplacement = tuple[str, list[CodeUnit], list[Endpoint]]


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _validate_replacements(
    conn: sqlite3.Connection,
    replacements: list[FileReplacement],
    released_paths: set[str],
) -> None:
    seen_paths: set[str] = set()
    seen_ids: dict[str, str] = {}

    for path, units, _ in replacements:
        if path in seen_paths:
            raise ValueError(f"Duplicate Code Steward replacement path: {path!r}")
        seen_paths.add(path)

        for unit in units:
            previous_path = seen_ids.get(unit.unit_id)
            if previous_path is not None:
                if previous_path == path:
                    raise ValueError(
                        f"Duplicate Code Steward unit ID in {path!r}: {unit.unit_id!r}"
                    )
                raise ValueError(
                    f"Duplicate Code Steward unit ID {unit.unit_id!r} across "
                    f"{previous_path!r} and {path!r}"
                )
            seen_ids[unit.unit_id] = path

    for unit_id, path in seen_ids.items():
        existing = conn.execute(
            "SELECT path FROM units WHERE unit_id = ?",
            (unit_id,),
        ).fetchone()
        if existing is not None and existing["path"] not in released_paths:
            raise ValueError(
                f"Code Steward unit ID {unit_id!r} in {path!r} conflicts "
                f"with existing unit in {existing['path']!r}"
            )


def _insert_file(
    conn: sqlite3.Connection,
    units: list[CodeUnit],
    endpoints: list[Endpoint],
) -> None:
    for unit in units:
        conn.execute(
            """INSERT INTO units VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                unit.unit_id,
                unit.path,
                unit.kind,
                unit.name,
                unit.qualname,
                unit.start_line,
                unit.end_line,
                unit.signature,
                json.dumps(unit.parameters, separators=(",", ":")),
                unit.returns,
                unit.purpose,
                unit.doc_text,
                json.dumps(unit.concepts, separators=(",", ":")),
                json.dumps(unit.decorators, separators=(",", ":")),
                json.dumps(unit.dependencies, separators=(",", ":")),
                json.dumps(unit.owns, separators=(",", ":")),
                json.dumps(unit.not_owns, separators=(",", ":")),
                unit.body_hash,
                unit.git_file_commit,
                int(unit.explicit_region),
            ),
        )

    for endpoint in endpoints:
        conn.execute(
            "INSERT INTO endpoints VALUES (?,?,?,?,?,?)",
            (
                endpoint.unit_id,
                endpoint.path,
                endpoint.method,
                endpoint.route,
                endpoint.response_model,
                json.dumps(endpoint.dependencies, separators=(",", ":")),
            ),
        )


def _unit_ids_for_paths(conn: sqlite3.Connection, paths: set[str]) -> set[str]:
    if not paths:
        return set()
    placeholders = ",".join("?" for _ in paths)
    query = f"SELECT unit_id FROM units WHERE path IN ({placeholders})"
    rows = conn.execute(query, tuple(sorted(paths))).fetchall()
    return {row["unit_id"] for row in rows}


def _invalidate_relationships(
    conn: sqlite3.Connection,
    released_unit_ids: set[str],
    replacement_unit_ids: set[str],
) -> set[str]:
    if not released_unit_ids:
        return set()

    placeholders = ",".join("?" for _ in released_unit_ids)
    values = tuple(sorted(released_unit_ids))
    removed_unit_ids = released_unit_ids - replacement_unit_ids

    if removed_unit_ids:
        removed_placeholders = ",".join("?" for _ in removed_unit_ids)
        removed_values = tuple(sorted(removed_unit_ids))
        conn.execute(
            f"""
            DELETE FROM hard_relationships
            WHERE source_unit_id IN ({placeholders})
               OR (
                    target_kind = 'unit'
                    AND target_ref IN ({removed_placeholders})
               )
            """,
            (*values, *removed_values),
        )
    else:
        conn.execute(
            f"DELETE FROM hard_relationships WHERE source_unit_id IN ({placeholders})",
            values,
        )

    conn.execute(
        f"""
        DELETE FROM soft_relationships
        WHERE source_unit_id IN ({placeholders})
           OR target_unit_id IN ({placeholders})
        """,
        (*values, *values),
    )
    return released_unit_ids & replacement_unit_ids


def _refresh_hard_target_hashes(
    conn: sqlite3.Connection,
    target_unit_ids: set[str],
) -> None:
    for unit_id in sorted(target_unit_ids):
        target_hash = _unit_hash(conn, unit_id)
        conn.execute(
            """
            UPDATE hard_relationships
            SET target_hash = ?
            WHERE target_kind = 'unit' AND target_ref = ?
            """,
            (target_hash, unit_id),
        )


def replace_files(
    conn: sqlite3.Connection,
    replacements: list[FileReplacement],
    remove_paths: set[str] | None = None,
) -> None:
    """Apply several file replacements as one validated transaction."""
    replacement_paths = {path for path, _, _ in replacements}
    released_paths = replacement_paths | set(remove_paths or ())
    _validate_replacements(conn, replacements, released_paths)

    with conn:
        released_unit_ids = _unit_ids_for_paths(conn, released_paths)
        replacement_unit_ids = {unit.unit_id for _, units, _ in replacements for unit in units}
        retained_targets = _invalidate_relationships(
            conn,
            released_unit_ids,
            replacement_unit_ids,
        )
        for path in sorted(released_paths):
            conn.execute("DELETE FROM endpoints WHERE path = ?", (path,))
            conn.execute("DELETE FROM units WHERE path = ?", (path,))
        for _, units, endpoints in replacements:
            _insert_file(conn, units, endpoints)
        _refresh_hard_target_hashes(conn, retained_targets)


def replace_file(
    conn: sqlite3.Connection,
    path: str,
    units: list[CodeUnit],
    endpoints: list[Endpoint],
) -> None:
    replace_files(conn, [(path, units, endpoints)])


def remove_file(conn: sqlite3.Connection, path: str) -> None:
    replace_files(conn, [], {path})


def indexed_paths(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT path FROM units UNION SELECT path FROM endpoints").fetchall()
    return {row["path"] for row in rows}


def unit_owners(conn: sqlite3.Connection, unit_ids: set[str]) -> dict[str, str]:
    if not unit_ids:
        return {}
    placeholders = ",".join("?" for _ in unit_ids)
    query = f"SELECT unit_id, path FROM units WHERE unit_id IN ({placeholders})"
    rows = conn.execute(query, tuple(sorted(unit_ids))).fetchall()
    return {row["unit_id"]: row["path"] for row in rows}


def _unit_hash(conn: sqlite3.Connection, unit_id: str) -> str:
    row = conn.execute(
        "SELECT body_hash FROM units WHERE unit_id = ?",
        (unit_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown Code Steward unit ID: {unit_id!r}")
    return str(row["body_hash"])


def _prepare_hard_relationships(
    conn: sqlite3.Connection,
    source_unit_id: str,
    relationships: list[HardRelationship],
    required_provenance: str | None = None,
) -> tuple[str, list[tuple[HardRelationship, str]]]:
    source_hash = _unit_hash(conn, source_unit_id)
    prepared: list[tuple[HardRelationship, str]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for relationship in relationships:
        if relationship.source_unit_id != source_unit_id:
            raise ValueError("Hard relationship source does not match replacement source")
        if not (relationship.relation and relationship.target_kind and relationship.target_ref):
            raise ValueError("Hard relationship fields must be non-empty")
        if not relationship.provenance:
            raise ValueError("Hard relationship provenance must be non-empty")
        if required_provenance is not None and relationship.provenance != required_provenance:
            raise ValueError("Hard relationship provenance does not match replacement provenance")

        key = (
            relationship.relation,
            relationship.target_kind,
            relationship.target_ref,
            relationship.provenance,
        )
        if key in seen:
            raise ValueError(f"Duplicate hard relationship: {key!r}")
        seen.add(key)

        target_hash = ""
        if relationship.target_kind == "unit":
            target_hash = _unit_hash(conn, relationship.target_ref)
        prepared.append((relationship, target_hash))

    return source_hash, prepared


def _insert_hard_relationships(
    conn: sqlite3.Connection,
    source_hash: str,
    prepared: list[tuple[HardRelationship, str]],
) -> None:
    for relationship, target_hash in prepared:
        conn.execute(
            "INSERT INTO hard_relationships VALUES (?,?,?,?,?,?,?,?)",
            (
                relationship.source_unit_id,
                relationship.relation,
                relationship.target_kind,
                relationship.target_ref,
                relationship.provenance,
                json.dumps(relationship.evidence, separators=(",", ":"), sort_keys=True),
                source_hash,
                target_hash,
            ),
        )


def replace_hard_relationships(
    conn: sqlite3.Connection,
    source_unit_id: str,
    relationships: list[HardRelationship],
) -> None:
    """Replace every hard outgoing relationship for one code unit."""
    source_hash, prepared = _prepare_hard_relationships(
        conn,
        source_unit_id,
        relationships,
    )
    with conn:
        conn.execute(
            "DELETE FROM hard_relationships WHERE source_unit_id = ?",
            (source_unit_id,),
        )
        _insert_hard_relationships(conn, source_hash, prepared)


def replace_hard_relationships_for_provenance(
    conn: sqlite3.Connection,
    source_unit_id: str,
    provenance: str,
    relationships: list[HardRelationship],
) -> None:
    """Replace hard relationships from one provenance source."""
    if not provenance:
        raise ValueError("Hard relationship provenance must be non-empty")
    source_hash, prepared = _prepare_hard_relationships(
        conn,
        source_unit_id,
        relationships,
        provenance,
    )
    with conn:
        conn.execute(
            """
            DELETE FROM hard_relationships
            WHERE source_unit_id = ? AND provenance = ?
            """,
            (source_unit_id, provenance),
        )
        _insert_hard_relationships(conn, source_hash, prepared)


def replace_soft_relationships(
    conn: sqlite3.Connection,
    source_unit_id: str,
    relationships: list[SoftRelationship],
) -> None:
    """Replace inferred outgoing relationships for one code unit."""
    source_hash = _unit_hash(conn, source_unit_id)
    prepared: list[tuple[SoftRelationship, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for relationship in relationships:
        if relationship.source_unit_id != source_unit_id:
            raise ValueError("Soft relationship source does not match replacement source")
        if not relationship.relation or not relationship.provenance:
            raise ValueError("Soft relationship relation and provenance must be non-empty")
        if not 0.0 <= relationship.score <= 1.0:
            raise ValueError("Soft relationship score must be between 0 and 1")

        key = (
            relationship.relation,
            relationship.target_unit_id,
            relationship.provenance,
        )
        if key in seen:
            raise ValueError(f"Duplicate soft relationship: {key!r}")
        seen.add(key)

        target_hash = _unit_hash(conn, relationship.target_unit_id)
        prepared.append((relationship, target_hash))

    with conn:
        conn.execute(
            "DELETE FROM soft_relationships WHERE source_unit_id = ?",
            (source_unit_id,),
        )
        for relationship, target_hash in prepared:
            conn.execute(
                "INSERT INTO soft_relationships VALUES (?,?,?,?,?,?,?,?)",
                (
                    relationship.source_unit_id,
                    relationship.relation,
                    relationship.target_unit_id,
                    relationship.score,
                    relationship.provenance,
                    json.dumps(relationship.evidence, separators=(",", ":"), sort_keys=True),
                    source_hash,
                    target_hash,
                ),
            )


def _row_to_hard_relationship(row: sqlite3.Row) -> HardRelationship:
    return HardRelationship(
        source_unit_id=row["source_unit_id"],
        relation=row["relation"],
        target_kind=row["target_kind"],
        target_ref=row["target_ref"],
        provenance=row["provenance"],
        evidence=json.loads(row["evidence_json"]),
        source_hash=row["source_hash"],
        target_hash=row["target_hash"],
    )


def all_hard_relationships(conn: sqlite3.Connection) -> list[HardRelationship]:
    rows = conn.execute(
        """
        SELECT * FROM hard_relationships
        ORDER BY source_unit_id, relation, target_kind, target_ref, provenance
        """
    ).fetchall()
    return [_row_to_hard_relationship(row) for row in rows]


def hard_relationships_for_provenance(
    conn: sqlite3.Connection,
    provenance: str,
    relation: str | None = None,
) -> list[HardRelationship]:
    """Read hard edges written by one deterministic extractor."""
    query = "SELECT * FROM hard_relationships WHERE provenance = ?"
    parameters: list[str] = [provenance]
    if relation is not None:
        query += " AND relation = ?"
        parameters.append(relation)
    query += " ORDER BY source_unit_id, relation, target_kind, target_ref"
    rows = conn.execute(query, tuple(parameters)).fetchall()
    return [_row_to_hard_relationship(row) for row in rows]


def all_soft_relationships(conn: sqlite3.Connection) -> list[SoftRelationship]:
    rows = conn.execute(
        """
        SELECT * FROM soft_relationships
        ORDER BY source_unit_id, relation, target_unit_id, provenance
        """
    ).fetchall()
    return [
        SoftRelationship(
            source_unit_id=row["source_unit_id"],
            relation=row["relation"],
            target_unit_id=row["target_unit_id"],
            score=row["score"],
            provenance=row["provenance"],
            evidence=json.loads(row["evidence_json"]),
            source_hash=row["source_hash"],
            target_hash=row["target_hash"],
        )
        for row in rows
    ]


def _row_to_unit(row: sqlite3.Row) -> CodeUnit:
    return CodeUnit(
        unit_id=row["unit_id"],
        path=row["path"],
        kind=row["kind"],
        name=row["name"],
        qualname=row["qualname"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        signature=row["signature"],
        parameters=json.loads(row["parameters_json"]),
        returns=row["returns"],
        purpose=row["purpose"],
        doc_text=row["doc_text"],
        concepts=json.loads(row["concepts_json"]),
        decorators=json.loads(row["decorators_json"]),
        dependencies=json.loads(row["dependencies_json"]),
        owns=json.loads(row["owns_json"]),
        not_owns=json.loads(row["not_owns_json"]),
        body_hash=row["body_hash"],
        git_file_commit=row["git_file_commit"],
        explicit_region=bool(row["explicit_region"]),
    )


def all_units(conn: sqlite3.Connection) -> list[CodeUnit]:
    return [
        _row_to_unit(row) for row in conn.execute("SELECT * FROM units ORDER BY path,start_line")
    ]


def get_unit(conn: sqlite3.Connection, unit_id: str) -> CodeUnit | None:
    row = conn.execute("SELECT * FROM units WHERE unit_id = ?", (unit_id,)).fetchone()
    return _row_to_unit(row) if row else None


def all_endpoints(conn: sqlite3.Connection) -> list[Endpoint]:
    rows = conn.execute("SELECT * FROM endpoints ORDER BY route,method").fetchall()
    return [
        Endpoint(
            unit_id=row["unit_id"],
            path=row["path"],
            method=row["method"],
            route=row["route"],
            response_model=row["response_model"],
            dependencies=json.loads(row["dependencies_json"]),
        )
        for row in rows
    ]
