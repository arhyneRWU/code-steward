"""End-to-end tests for `check`, the post-write duplication pass.

`check` is the command the measurements actually support: comparing a
real body finds its duplicate 1.000 of the time, where comparing a
sketch manages 0.460. The failure modes worth pinning are the ones
that would make it either useless or unusable -- missing an obvious
copy, or firing on a function's own previous revision.
"""

from __future__ import annotations

import json

import pytest

from code_steward.cli import main
from code_steward.maintenance import rebuild_index
from code_steward.similarity import REUSE_FLOOR

HELPER = '''\
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

COPIED = '''\
def order_items(needle, rows, limit):
    """Copied and lightly tidied."""
    scored = []
    for key, value in rows.items():
        shared = len(needle & value)
        if shared < 3:
            continue
        scored.append((key, shared))
    scored.sort(key=lambda row: -row[1])
    return scored[:limit]
'''

UNRELATED = '''\
def send_invoice(mailer, customer, amount):
    """Render an invoice and email it."""
    body = mailer.render("invoice", customer=customer, amount=amount)
    message = mailer.compose(customer.email, "Your invoice", body)
    receipt = mailer.deliver(message)
    mailer.audit(receipt.id, customer.id)
    return receipt.id
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "a.py").write_text(HELPER, encoding="utf-8")
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    return tmp_path


def _run(project, *argv):
    return main(["--root", str(project), *argv])


def test_check_finds_a_copied_function(project, capsys):
    new = project / "b.py"
    new.write_text(COPIED, encoding="utf-8")
    assert _run(project, "check", str(new)) == 0
    out = capsys.readouterr().out
    assert "order_items" in out
    assert "a::rank_things" in out


def test_check_stays_quiet_on_unrelated_code(project, capsys):
    new = project / "b.py"
    new.write_text(UNRELATED, encoding="utf-8")
    assert _run(project, "check", str(new)) == 0
    assert "none overlap existing code" in capsys.readouterr().out


def test_check_does_not_match_a_function_against_its_own_older_revision(project, capsys):
    """The failure that would make the command useless in practice.

    ``a.py`` is already indexed. Checking it unchanged must not report
    it as a duplicate of itself.
    """
    assert _run(project, "check", str(project / "a.py")) == 0
    assert "none overlap existing code" in capsys.readouterr().out


def test_check_reports_how_many_functions_it_looked_at(project, capsys):
    """A silent result means nothing without the denominator."""
    new = project / "b.py"
    new.write_text(UNRELATED, encoding="utf-8")
    assert _run(project, "check", str(new)) == 0
    assert "1 changed function(s) checked" in capsys.readouterr().out


def test_check_can_fail_a_build_when_asked(project, capsys):
    new = project / "b.py"
    new.write_text(COPIED, encoding="utf-8")
    assert _run(project, "check", str(new), "--fail-on-overlap") == 1
    assert _run(project, "check", str(new)) == 0


def test_check_json_carries_the_floor_and_the_denominator(project, capsys):
    new = project / "b.py"
    new.write_text(COPIED, encoding="utf-8")
    assert _run(project, "check", str(new), "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["floor"] == REUSE_FLOOR
    assert payload["checked"] == 1
    assert payload["findings"][0]["overlaps"][0]["unit"] == "a::rank_things"


def test_check_skips_a_file_that_does_not_parse(project, capsys):
    """An author's syntax error is not this command's failure."""
    broken = project / "broken.py"
    broken.write_text("def nope(:\n", encoding="utf-8")
    assert _run(project, "check", str(broken)) == 0
    assert "0 changed function(s) checked" in capsys.readouterr().out


def test_check_raising_the_floor_suppresses_a_weak_overlap(project, capsys):
    new = project / "b.py"
    new.write_text(COPIED, encoding="utf-8")
    assert _run(project, "check", str(new), "--floor", "0.99") == 0
    assert "none overlap existing code" in capsys.readouterr().out


def test_check_rate_reports_the_repository_baseline(project, capsys):
    """The alarm rate is repo-dependent, so the tool must measure it.

    The doc quotes 14% to 63% across four codebases. A user should
    not have to guess which end they are on.
    """
    (project / "b.py").write_text(COPIED, encoding="utf-8")
    rebuild_index(project, project / ".code-steward" / "index.sqlite3")
    assert _run(project, "check", "--rate") == 0
    out = capsys.readouterr().out
    assert "2 of 2 indexed function(s) overlap another" in out
    assert "100.0%" in out


def test_check_rate_says_a_high_share_is_not_a_fault(project, capsys):
    """A baseline is information, not a verdict on the codebase."""
    assert _run(project, "check", "--rate") == 0
    assert "not a fault" in capsys.readouterr().out
