"""End-to-end tests for `similar` and packet reuse evidence."""

from __future__ import annotations

import json

import pytest

from code_steward.cli import main
from code_steward.maintenance import rebuild_index
from code_steward.similarity import REUSE_FLOOR

RANKER = '''\
def rank_things(needle, rows, limit):
    """Rank rows by overlap with a needle."""
    scored = []
    for key, value in rows.items():
        shared = len(needle & value)
        if shared < 3:
            continue
        scored.append((key, shared))
    scored.sort(key=lambda row: -row[1])
    return scored[:limit]
'''

RANKER_COPY = '''\
def order_items(target, entries, cap):
    """A different summary entirely."""
    scored = []
    for key, value in entries.items():
        shared = len(target & value)
        if shared < 3:
            continue
        scored.append((key, shared))
    scored.sort(key=lambda row: -row[1])
    return scored[:cap]
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "a.py").write_text(RANKER, encoding="utf-8")
    (tmp_path / "b.py").write_text(RANKER_COPY, encoding="utf-8")
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    return tmp_path


def _run(project, *argv):
    return main(["--root", str(project), *argv])


def test_similar_finds_the_copy_of_an_indexed_unit(project, capsys):
    assert _run(project, "similar", "a::rank_things", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert [row["unit_id"] for row in payload["matches"]] == ["b::order_items"]
    assert payload["matches"][0]["score"] > 0.3
    assert payload["floor"] == REUSE_FLOOR


def test_similar_reports_nothing_rather_than_failing(project, capsys):
    """No candidate is the common and correct answer."""
    (project / "c.py").write_text(
        "def unrelated(client, to, subject):\n"
        '    """Send a message."""\n'
        "    message = client.compose(to, subject)\n"
        "    receipt = client.deliver(message)\n"
        "    client.log(receipt.id)\n"
        "    return receipt.id\n",
        encoding="utf-8",
    )
    rebuild_index(project, project / ".code-steward" / "index.sqlite3")
    assert _run(project, "similar", "c::unrelated") == 0
    assert "no existing unit overlaps" in capsys.readouterr().out


def test_similar_rejects_an_unknown_unit(project, capsys):
    assert _run(project, "similar", "nope::missing") == 2
    assert "unknown unit" in capsys.readouterr().err


def test_similar_matches_a_draft_that_is_not_indexed(project, capsys):
    """The pre-implementation case, through the CLI."""
    draft = project / "draft.txt"
    draft.write_text(RANKER_COPY, encoding="utf-8")
    assert _run(project, "similar", "--draft", str(draft), "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert "a::rank_things" in {row["unit_id"] for row in payload["matches"]}


def test_similar_rejects_a_draft_that_does_not_parse(project, tmp_path, capsys):
    draft = tmp_path / "bad.py"
    draft.write_text("def broken(:\n", encoding="utf-8")
    assert _run(project, "similar", "--draft", str(draft)) == 2
    assert "does not parse" in capsys.readouterr().err


def test_similar_needs_a_unit_or_a_draft(project):
    with pytest.raises(SystemExit):
        _run(project, "similar")


# `packet` is no longer a command -- see tests/test_cli_surface.py --
# but `build_packet` is still imported by six benchmark modules, so
# the behaviour is tested where it now lives rather than deleted with
# the CLI surface.


def _packet_for(project, query, **kwargs):
    from code_steward.db import all_endpoints, all_units, connect
    from code_steward.packet import build_packet
    from code_steward.search import search_units

    conn = connect(project / ".code-steward" / "index.sqlite3")
    units = all_units(conn)
    endpoints = all_endpoints(conn)
    conn.close()
    results = search_units(units, query, limit=8)
    return build_packet(query, results, endpoints, **kwargs)


def test_packet_omits_duplicates_unless_asked(project):
    packet = _packet_for(project, "rank rows by overlap")
    assert all("duplicates" not in row for row in packet["candidates"])
    assert "duplicates_note" not in packet["review_contract"]


def test_similar_reports_what_the_floor_suppressed(project, capsys):
    """An empty result must say whether anything was checked.

    "Checked, found none" and "checked, found six, none close
    enough" are different facts, and a reviewer deciding whether to
    write new code needs to tell them apart.
    """
    assert _run(project, "similar", "a::rank_things", "--floor", "0.99") == 0
    out = capsys.readouterr().out
    assert "nothing above the 0.99 floor" in out
    assert "suppressed" in out


def test_similar_floor_can_be_lowered_to_see_weak_matches(project, capsys):
    assert _run(project, "similar", "a::rank_things", "--floor", "0.0", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["matches"]
    assert "below_floor" not in payload
