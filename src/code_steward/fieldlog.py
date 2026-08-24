"""A local record of what this tool was actually asked to do.

Stage 2 of the roadmap is *use it in anger for a week*, and its exit
is an account of what the tool caught and what it wasted time on. A
week of recollection is not that account, and the interesting half --
how often a slice came back empty, how often a command was run and
its answer ignored -- is exactly the half nobody remembers.

**Off unless asked.** Nothing is written unless
``CODE_STEWARD_FIELD_LOG`` names a file. There is no default path, no
directory created behind your back, and nothing leaves the machine:
this appends to a local file and does nothing else. A public tool
that reports anything anywhere by default is not one worth
installing.

**Never in the way.** Every failure here is swallowed. A logger that
can break `trace` is worse than no logger, and the record is a
convenience, never a result.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

ENV_VAR = "CODE_STEWARD_FIELD_LOG"


def record(entry: dict[str, Any]) -> None:
    """Append one line to the field log, if one was asked for."""
    path = os.environ.get(ENV_VAR)
    if not path:
        return
    row = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    except (OSError, TypeError, ValueError):
        # Deliberate: a command must not fail because its diary did.
        return
