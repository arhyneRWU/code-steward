"""Tell the caller when the index no longer matches the source.

The first field session produced one finding that outranked every
feature request: **a stale index is silently wrong, not silently
incomplete.** It handed back a function labelled with a neighbouring
function's line range, and reported one caller where two existed, on
a function the agent had just edited.

Both are the judgement this tool exists to support, inverted. Neither
is detectable by the reader, because a bundle carries no marker of
its own freshness -- it looks exactly as authoritative when it is
wrong. The project's own documentation claimed a stale index was
"quietly incomplete rather than loudly wrong", which was false for
line ranges specifically.

Detection is deliberately crude and cheap: a source file modified
more recently than the index database was written cannot be trusted.
It over-reports -- touching a file without changing it counts -- and
over-reporting is the correct direction for a warning whose remedy is
one fast command.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def stale_paths(project_root: Path, database: Path, paths: Iterable[str]) -> list[str]:
    """Which of ``paths`` are newer on disk than the index."""
    try:
        indexed_at = database.stat().st_mtime
    except OSError:
        return []
    stale: list[str] = []
    for relative in dict.fromkeys(paths):
        source = project_root / relative
        try:
            if source.stat().st_mtime > indexed_at:
                stale.append(relative)
        except OSError:
            # A deleted file is a different problem with a different
            # message, and not this function's business.
            continue
    return stale


def warning(stale: list[str]) -> str:
    """Build the message; empty when there is nothing to say."""
    if not stale:
        return ""
    shown = ", ".join(stale[:3])
    more = f" and {len(stale) - 3} more" if len(stale) > 3 else ""
    return (
        f"warning: {shown}{more} changed since the index was built. "
        "Line ranges and callers in this bundle may be wrong, not "
        "merely incomplete. Run: code-steward update " + " ".join(stale[:3])
    )
