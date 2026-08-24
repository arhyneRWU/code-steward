"""A local record of what this tool was actually asked to do.

Stage 2 of the roadmap is *use it in anger for a week*, and its exit
is an account of what the tool caught and what it wasted time on. A
week of recollection is not that account, and the interesting half --
how often a slice came back empty, how often a command ran and its
answer was ignored -- is exactly the half nobody remembers.

**Off unless asked.** Nothing is written unless
``CODE_STEWARD_FIELD_LOG`` names a file. There is no default path and
nothing leaves the machine: this appends to a local file and does
nothing else. A public tool that reports anything anywhere by default
is not one worth installing.

**Never in the way, but never silent about it either.** Every failure
is swallowed -- a logger that can break `trace` is worse than no
logger. The first version swallowed them *quietly*, and the field
found the consequence within an hour: agents run in a sandbox whose
write allowlist excludes ``$HOME``, so every subagent invocation was
lost and the log read as "tool unused" rather than "log unwritable".

Two changes follow from that. A failed write falls back to the
project's own ``.code-steward`` directory, which a sandbox running in
the project can write. And the first failure prints one line to
stderr, so an empty log can never again mean two different things.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENV_VAR = "CODE_STEWARD_FIELD_LOG"
FALLBACK_NAME = "field-log.jsonl"

# Which one-time notices have been printed. A note on every
# invocation would be noise, and noise gets filtered out.
NOTIFIED: set[str] = set()


def _notice(message: str) -> None:
    if message in NOTIFIED:
        return
    NOTIFIED.add(message)
    try:
        print(message, file=sys.stderr)
    except (OSError, ValueError):
        return


def _append(path: Path, row: dict[str, Any]) -> bool:
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    except (OSError, TypeError, ValueError):
        return False
    return True


def record(entry: dict[str, Any], root: Path | None = None) -> None:
    """Append one line to the field log, if one was asked for."""
    configured = os.environ.get(ENV_VAR)
    if not configured:
        return
    row = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
    if _append(Path(configured), row):
        return

    # The configured path is unwritable. A sandbox is the likely
    # reason, so try the project, which a sandbox can usually write.
    fallback = (root / ".code-steward" / FALLBACK_NAME) if root is not None else None
    if fallback is not None and fallback.parent.is_dir() and _append(fallback, row):
        _notice(f"field log: cannot write {configured}, using {fallback}")
        return
    _notice(f"field log: cannot write {configured}; nothing is being recorded")
