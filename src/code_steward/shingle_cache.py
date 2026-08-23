"""Persist computed shingle sets so `similar` stays interactive.

Comparing a draft against a repository means having a shingle set for
every indexed unit. Building those from source costs a parse of every
file plus a normalisation of every unit: measured at 13.9 seconds on a
9,300-file tree. A tool meant to run before each function is written
cannot cost that every time.

The sets themselves are small -- 7.4 MB raw for 63,597 units -- so
they are cached rather than recomputed. The key is the unit's
`body_hash`, which the indexer already stores, so the cache is exact
by construction: a changed body produces a different hash and misses.
There is no invalidation logic to get wrong, and no approximation that
would change what the benchmark measured.

The cache is disposable. Deleting it costs one slow call.
"""

from __future__ import annotations

import sqlite3
import struct
import zlib
from collections.abc import Iterable
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS shingles (
    body_hash TEXT PRIMARY KEY,
    payload   BLOB NOT NULL
) WITHOUT ROWID;
"""

# Signed 64-bit, because these are Python hash() values.
_PACK = "<q"


def cache_path(project_root: Path) -> Path:
    """Locate the shingle cache beside the index."""
    return project_root / ".code-steward" / "shingles.sqlite3"


# Pack and unpack whole sets in one call each. Doing it per element
# was measured at roughly a million struct calls for one repository,
# which cost more than the parsing the cache exists to avoid.
_ITEM = struct.calcsize(_PACK)


def _encode(values: frozenset[int]) -> bytes:
    ordered = sorted(values)
    packed = struct.pack(f"<{len(ordered)}q", *ordered)
    return zlib.compress(packed, 1)


def _decode(payload: bytes) -> frozenset[int]:
    raw = zlib.decompress(payload)
    return frozenset(struct.unpack(f"<{len(raw) // _ITEM}q", raw))


def connect(path: Path) -> sqlite3.Connection:
    """Open the cache, creating it if this is the first call."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def read(conn: sqlite3.Connection, body_hashes: Iterable[str]) -> dict[str, frozenset[int]]:
    """Fetch every cached set among the given hashes."""
    wanted = [value for value in dict.fromkeys(body_hashes) if value]
    found: dict[str, frozenset[int]] = {}
    # SQLite caps host parameters, so read in blocks rather than
    # building one statement the size of the repository.
    block = 500
    for start in range(0, len(wanted), block):
        chunk = wanted[start : start + block]
        placeholders = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"SELECT body_hash, payload FROM shingles WHERE body_hash IN ({placeholders})",
            chunk,
        ).fetchall()
        for body_hash, payload in rows:
            try:
                found[body_hash] = _decode(payload)
            except (zlib.error, struct.error):
                # A corrupt row is a cache problem, not a data
                # problem. Treat it as a miss and let it be rewritten.
                continue
    return found


def write(conn: sqlite3.Connection, entries: dict[str, frozenset[int]]) -> None:
    """Store newly computed sets, replacing any stale row."""
    conn.executemany(
        "INSERT OR REPLACE INTO shingles (body_hash, payload) VALUES (?, ?)",
        [(body_hash, _encode(values)) for body_hash, values in entries.items() if body_hash],
    )
    conn.commit()
