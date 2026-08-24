from __future__ import annotations

import os
import sqlite3
import tempfile
from collections.abc import Iterable, Sequence
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
from .relationships import refresh_relationships
from .webclient import refresh_web_client_relationships


@dataclass(frozen=True, slots=True)
class SkippedFile:
    """One file the build could not index, and why."""

    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class BuildStats:
    files: int
    units: int
    endpoints: int
    skipped: tuple[SkippedFile, ...] = ()


@dataclass(frozen=True, slots=True)
class UpdateStats:
    primary_units: int
    updated_paths: tuple[str, ...]
    removed_paths: tuple[str, ...]


INDEXING_ERRORS = (OSError, sqlite3.Error, SyntaxError, UnicodeDecodeError, ValueError)

# Errors that describe the file rather than the project. Real trees
# contain Python the running interpreter cannot parse -- vendored
# Python 2, syntax from a newer release, generated stubs, templates
# with a .py suffix. A whole-index abort on one of those makes the
# tool unusable on the repository, which is a worse outcome than an
# index that is one file short and says so.
#
# Everything else still aborts. A duplicate or malformed
# `# code-steward:` tag is a mistake in the project that someone has
# to fix, and a storage or filesystem failure is not a property of any
# one file. Both keep the previous index intact.
SKIPPABLE_ERRORS = (SyntaxError, UnicodeDecodeError)


def _located(rel: str, exc: BaseException) -> BaseException:
    """Rebuild an indexing failure with its source path.

    The path is prefixed onto the message so callers can tell which
    file aborted the build.
    """
    message = f"{rel}: {exc}"
    try:
        return type(exc)(message)
    except Exception:
        return ValueError(message)


def refresh_all_relationships(
    conn: sqlite3.Connection,
    project_root: Path,
    excludes: Iterable[str] = (),
) -> None:
    """Re-derive every deterministic edge, Python and frontend alike.

    The two extractors live in separate modules because they answer to
    different evidence -- one to the Python AST, one to literal URLs
    across an HTTP boundary -- and orchestrating them here keeps
    `relationships` from having to import the web client, which would
    close an import cycle through `routing`.
    """
    refresh_relationships(conn, project_root)
    refresh_web_client_relationships(conn, project_root, excludes)


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
        skipped: list[SkippedFile] = []
        for path in iter_python_files(project_root, excludes):
            rel = path.relative_to(project_root).as_posix()
            try:
                units, endpoints = index_python_file(project_root, path)
                replace_file(conn, rel, units, endpoints)
            except SKIPPABLE_ERRORS as exc:
                skipped.append(SkippedFile(rel, f"{type(exc).__name__}: {exc}"))
                continue
            except INDEXING_ERRORS as exc:
                raise _located(rel, exc) from exc
            file_count += 1
            unit_count += len(units)
            endpoint_count += len(endpoints)

        refresh_all_relationships(conn, project_root, excludes)
        conn.close()
        conn = None
        os.replace(temporary, destination)
        return BuildStats(file_count, unit_count, endpoint_count, tuple(skipped))
    except BaseException:
        if conn is not None:
            conn.close()
        temporary.unlink(missing_ok=True)
        raise


def _index_replacement(project_root: Path, path: Path) -> FileReplacement:
    rel = path.relative_to(project_root).as_posix()
    try:
        units, endpoints = index_python_file(project_root, path)
    except INDEXING_ERRORS as exc:
        raise _located(rel, exc) from exc
    return rel, units, endpoints


def update_index_file(
    conn: sqlite3.Connection,
    project_root: Path,
    path: Path,
) -> UpdateStats:
    """Update one path while reconciling stale semantic-ID owners."""
    return update_index_files(conn, project_root, [path])


def update_index_files(
    conn: sqlite3.Connection,
    project_root: Path,
    paths: Sequence[Path],
) -> UpdateStats:
    """Update several paths, refreshing relationships exactly once.

    The refresh re-derives edges across the whole index, so its cost
    is per call and not per file. Doing it inside a per-file loop is
    what made `update` unusable on a large repository: 22.9 seconds
    for one file, measured on 14,791 units, which pushed real sessions
    into full rebuilds instead. Batch first, refresh last.
    """
    project_root = project_root.resolve()
    # A JavaScript file holds no indexed unit. It still reaches here,
    # because editing one changes which routes have a frontend caller,
    # and the refresh at the end is what records that. Handing it to
    # the Python indexer would raise a SyntaxError on valid source.
    resolved = [item.resolve() for item in paths if item.suffix == ".py"]

    remove_paths = {
        indexed for indexed in indexed_paths(conn) if not (project_root / indexed).exists()
    }
    replacements: dict[str, FileReplacement] = {}
    primary_units = 0
    for path in resolved:
        rel = path.relative_to(project_root).as_posix()
        if not path.exists():
            remove_paths.add(rel)
            continue
        replacement = _index_replacement(project_root, path)
        replacements[rel] = replacement
        primary_units += len(replacement[1])

    if not replacements:
        for rel in sorted(remove_paths):
            remove_file(conn, rel)
        refresh_all_relationships(conn, project_root)
        return UpdateStats(0, (), tuple(sorted(remove_paths)))

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
    refresh_all_relationships(conn, project_root)
    return UpdateStats(
        primary_units=primary_units,
        updated_paths=tuple(sorted(replacements)),
        removed_paths=tuple(sorted(remove_paths)),
    )
