from __future__ import annotations

import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .db import (
    FileReplacement,
    connect,
    indexed_paths,
    remove_file,
    replace_file,
    replace_files,
    unit_owners,
)
from .indexer import index_python_file, iter_python_files


@dataclass(frozen=True, slots=True)
class BuildStats:
    files: int
    units: int
    endpoints: int


@dataclass(frozen=True, slots=True)
class UpdateStats:
    primary_units: int
    updated_paths: tuple[str, ...]
    removed_paths: tuple[str, ...]


def rebuild_index(
    project_root: Path,
    destination: Path,
    excludes: list[str] | tuple[str, ...] = (),
) -> BuildStats:
    """Build a complete index, then atomically replace the database."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(fd)
    temporary = Path(temporary_name)
    conn: sqlite3.Connection | None = None

    try:
        conn = connect(temporary)
        file_count = unit_count = endpoint_count = 0
        for path in iter_python_files(project_root, excludes):
            units, endpoints = index_python_file(project_root, path)
            rel = path.relative_to(project_root).as_posix()
            replace_file(conn, rel, units, endpoints)
            file_count += 1
            unit_count += len(units)
            endpoint_count += len(endpoints)

        conn.close()
        conn = None
        os.replace(temporary, destination)
        return BuildStats(file_count, unit_count, endpoint_count)
    except BaseException:
        if conn is not None:
            conn.close()
        temporary.unlink(missing_ok=True)
        raise


def _index_replacement(project_root: Path, path: Path) -> FileReplacement:
    units, endpoints = index_python_file(project_root, path)
    rel = path.relative_to(project_root).as_posix()
    return rel, units, endpoints


def update_index_file(
    conn: sqlite3.Connection,
    project_root: Path,
    path: Path,
) -> UpdateStats:
    """Update one path while reconciling stale semantic-ID owners."""
    project_root = project_root.resolve()
    path = path.resolve()
    rel = path.relative_to(project_root).as_posix()

    if not path.exists():
        remove_file(conn, rel)
        return UpdateStats(0, (), (rel,))

    primary = _index_replacement(project_root, path)
    replacements: dict[str, FileReplacement] = {rel: primary}
    remove_paths = {
        indexed for indexed in indexed_paths(conn) if not (project_root / indexed).exists()
    }

    while True:
        claimed_ids = {unit.unit_id for _, units, _ in replacements.values() for unit in units}
        owners = unit_owners(conn, claimed_ids)
        conflict_paths = {
            owner
            for owner in owners.values()
            if owner not in replacements and owner not in remove_paths
        }
        if not conflict_paths:
            break

        for conflict_rel in sorted(conflict_paths):
            conflict_path = project_root / conflict_rel
            if not conflict_path.exists():
                remove_paths.add(conflict_rel)
                continue
            replacements[conflict_rel] = _index_replacement(project_root, conflict_path)

    replace_files(conn, list(replacements.values()), remove_paths)
    return UpdateStats(
        primary_units=len(primary[1]),
        updated_paths=tuple(sorted(replacements)),
        removed_paths=tuple(sorted(remove_paths)),
    )
