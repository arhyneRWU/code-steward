"""Two verdicts that were wrong in the same way: confidently absent.

Both were found by directed field use on a private repository, and
both cost the same thing -- a reader concluding something is not there
when the truth is that this tool cannot see it.

`trace app/static/js/foo.js:120` failed identically to a missing
symbol. Four of a session's five traces were spent that way: the
target was JavaScript, JavaScript carries no indexed unit, and
"unknown unit" reads as "no such function".

`endpoints --unbound` called an interpolated URL "no route", which is
the verdict that invites deleting the endpoint. On that repository 18
of 34 such verdicts were interpolated -- `/document/${endpoint}` has a
whole variable path segment, and collapsing it to `/document/{}` and
pronouncing it dead is a guess wearing a result's clothes.
"""

from __future__ import annotations

from code_steward.trace import unindexed_reason
from code_steward.webclient import ClientCall, unbound_reason


def test_a_javascript_path_says_the_language_is_not_indexed() -> None:
    reason = unindexed_reason("app/static/js/validation.js:120")
    assert "JavaScript" in reason
    assert "not indexed" in reason


def test_the_reason_names_what_does_work() -> None:
    """A dead end without a next step is half an error message."""
    assert "endpoints --unbound" in unindexed_reason("app/static/js/a.js:12")


def test_a_python_path_has_no_such_reason() -> None:
    assert unindexed_reason("app/routes/review.py:120") == ""


def test_a_bare_name_has_no_such_reason() -> None:
    assert unindexed_reason("list_items") == ""


def test_an_unknown_extension_is_reported_generically() -> None:
    reason = unindexed_reason("app/templates/page.html:9")
    assert ".html" in reason and "not indexed" in reason


def test_a_computed_url_reads_as_computed() -> None:
    call = ClientCall("a.js", 1, "", "GET")
    assert unbound_reason(call) == "computed URL"


def test_an_interpolated_url_is_unresolved_not_dead() -> None:
    call = ClientCall("a.js", 1, "/document/${endpoint}", "POST")
    reason = unbound_reason(call)
    assert "unresolved" in reason
    assert "no route" not in reason


def test_a_fully_literal_url_may_still_be_called_dead() -> None:
    """The one case where the strong verdict is earned."""
    call = ClientCall("a.js", 1, "/api/gone", "GET")
    assert unbound_reason(call) == "no route for GET /api/gone"
