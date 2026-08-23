"""Lexical query matching, shared by the ranker and its control arm.

The text-search control arm beats the five-field metadata ranker on
every retrieval metric measured on `psf/requests`. That result stood
for months with the obvious conclusion unacted on: the signal the
control finds lives in **code bodies** -- identifiers like
`rebuild_proxies` -- and no scored field read them.

This module is that signal, extracted once so both sides use the same
rule. `benchmarks/real_repo/grep_baseline.py` imports it, and so does
`search.py`. A control arm and the thing it controls must not disagree
about what a query term is.

The matching rule is the control's, deliberately: a term matches when
it appears as a **substring** of the body text, not when it equals a
token. That is what lets a query saying "rebuild" find
`rebuild_proxies`, and it is the behaviour that wins.
"""

from __future__ import annotations

import re

# Words that carry no retrieval signal in a code-search query. The
# tail of this list is task phrasing -- "find", "helper", "existing" --
# which appears in almost every query an agent writes and matches
# almost every unit.
_STOPWORD_TEXT = """
    a an and are as at be been being but by can code could did do does
    doing done for from get gets given handle handles has have having
    how in into is it its like make makes of on or over per put return
    returns should so some such take takes than that the their them then
    there these they this those to use used uses using was were what
    when where which while who why will with would
    find locate search identify show where's wheres helper helpers
    function functions method methods class classes reusable existing
    logic implementation implementations piece part area thing
"""

STOPWORDS = frozenset(_STOPWORD_TEXT.split())

# Three characters minimum: shorter runs are loop variables and
# operators, and they match everywhere.
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")


def query_terms(query: str) -> list[str]:
    """Reduce a query to the distinct terms worth searching for."""
    terms: list[str] = []
    seen: set[str] = set()
    for match in TOKEN_RE.finditer(query):
        term = match.group(0).lower()
        if term in STOPWORDS or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def body_terms(text: str) -> str:
    """Reduce a unit's source to its distinct lowercase tokens.

    Stored rather than the source itself: the ranker only needs to ask
    whether a term occurs, and the distinct-token form is a fraction
    of the size. Joined by spaces so a caller can substring-search the
    whole thing in one pass.
    """
    seen: dict[str, None] = {}
    for match in TOKEN_RE.finditer(text):
        seen.setdefault(match.group(0).lower(), None)
    return " ".join(seen)


def term_coverage(terms: list[str], haystack: str) -> float:
    """Fraction of query terms present in a body, as a 0-100 score.

    Substring matching, matching the control arm. Returns 0.0 for an
    empty query rather than 100.0: a query with no searchable terms
    has not matched anything, and scoring it perfect would hand every
    unit in the repository a full mark.
    """
    if not terms or not haystack:
        return 0.0
    found = sum(1 for term in terms if term in haystack)
    return 100.0 * found / len(terms)
