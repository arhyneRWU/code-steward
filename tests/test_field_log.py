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


def test_it_falls_back_to_the_project_when_home_is_unwritable(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Found in the field: agents run sandboxed and cannot write $HOME.

    Every subagent invocation was silently lost, and the swallow that
    keeps the logger out of the way is what hid it.
    """
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "forbidden" / "field.jsonl"))
    project = tmp_path / "project"
    (project / ".code-steward").mkdir(parents=True)
    record({"command": "trace"}, root=project)
    fallback = project / ".code-steward" / "field-log.jsonl"
    assert fallback.exists(), "a log that cannot write should try the project first"
    assert "field log" in capsys.readouterr().err.lower()


def test_the_failure_notice_is_printed_once(tmp_path: Path, monkeypatch, capsys) -> None:
    """A note every time would be noise, and noise gets ignored."""
    import code_steward.fieldlog as module

    module.NOTIFIED.clear()
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "nope" / "field.jsonl"))
    for _ in range(3):
        record({"command": "trace"})
    assert capsys.readouterr().err.count("field log") == 1


def test_silence_still_means_unused_when_the_path_works(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    log = tmp_path / "field.jsonl"
    monkeypatch.setenv(ENV_VAR, str(log))
    record({"command": "trace"})
    assert capsys.readouterr().err == "", "a working log must say nothing at all"
