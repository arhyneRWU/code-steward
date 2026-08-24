"""The Stage 2 field log: off unless asked, and never in the way.

Stage 2 of the roadmap is "use it in anger for a week", whose exit is
a written account of what the tool caught and what it wasted time on.
A week of recollection is not that. This records what actually ran.

Two properties matter more than the contents. It must be **off by
default** -- a public tool that phones anything anywhere by default
is not one I would install -- and it must **never fail a command**,
because a logger that can break `trace` is worse than no log.
"""

from __future__ import annotations

import json
from pathlib import Path

from code_steward.fieldlog import ENV_VAR, record


def test_nothing_is_written_without_the_environment_variable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    record({"command": "trace"})
    assert list(tmp_path.iterdir()) == []


def test_one_json_line_per_invocation(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "field.jsonl"
    monkeypatch.setenv(ENV_VAR, str(log))
    record({"command": "trace", "members": 9})
    record({"command": "check", "members": 0})
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [row["command"] for row in lines] == ["trace", "check"]
    assert lines[0]["members"] == 9
    assert all("at" in row for row in lines), "a record with no time is not a record"


def test_an_unwritable_path_never_breaks_the_command(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "no" / "such" / "dir" / "field.jsonl"))
    record({"command": "trace"})  # must not raise
