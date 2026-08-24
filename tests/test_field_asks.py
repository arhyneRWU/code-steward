"""Three asks from the first Stage 2 session, each with its evidence.

1. A stale index is silently **wrong**, not silently incomplete. It
   handed one function labelled with another's line range, and
   reported one caller where two existed. Both are the judgement the
   tool exists to support, inverted, and both are invisible unless
   you already know the answer.
2. `similar` accepted only a unit ID while `trace` accepted three
   forms. That single gap was 100% of the session's tool failures.
3. `trace --endpoints` emitted 119,621 lines on a 296-route app,
   which is unusable without piping to grep.
"""

from __future__ import annotations

from pathlib import Path

from code_steward.staleness import stale_paths


def _indexed(tmp_path: Path) -> Path:
    from code_steward.maintenance import rebuild_index

    (tmp_path / "a.py").write_text("def one():\n    return 1\n", encoding="utf-8")
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    return tmp_path


def test_a_file_edited_after_indexing_is_reported_stale(tmp_path: Path) -> None:
    root = _indexed(tmp_path)
    database = root / ".code-steward" / "index.sqlite3"
    import os
    import time

    later = time.time() + 10
    (root / "a.py").write_text("def one():\n    return 2\n", encoding="utf-8")
    os.utime(root / "a.py", (later, later))
    assert stale_paths(root, database, ["a.py"]) == ["a.py"]


def test_an_untouched_file_is_not_reported(tmp_path: Path) -> None:
    root = _indexed(tmp_path)
    database = root / ".code-steward" / "index.sqlite3"
    assert stale_paths(root, database, ["a.py"]) == []


def test_a_missing_file_is_not_reported_as_stale(tmp_path: Path) -> None:
    """A deleted file is a different problem, with its own message."""
    root = _indexed(tmp_path)
    database = root / ".code-steward" / "index.sqlite3"
    assert stale_paths(root, database, ["gone.py"]) == []
