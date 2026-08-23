"""Tests for the shipped reuse-similarity comparison.

The constants this module uses are measured values. The benchmark that
produced `docs/similarity.md` imports this module rather than keeping
its own copy, so a change here silently invalidates published numbers.
One test below pins the constants for that reason.
"""

from __future__ import annotations

import ast

import pytest

from code_steward.models import CodeUnit
from code_steward.similarity import (
    MAX_SHINGLE_DOCUMENT_FREQUENCY,
    MIN_LINES,
    MIN_SHARED_SHINGLES,
    MIN_TOKENS,
    SHINGLE_SIZE,
    draft_shingles,
    jaccard,
    normalise,
    rank_against,
    rank_all_pairs,
    rank_similar_units,
    shingles,
    tokenise,
    unit_shingles,
)

RANKER = '''
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

# The same function with a new name, a new signature, and a different
# docstring -- a copy that was pasted and then tidied. This is the
# case the arm has to catch.
RANKER_RENAMED = '''
def order_items(target, entries, cap):
    """Something else entirely."""
    scored = []
    for key, value in entries.items():
        shared = len(target & value)
        if shared < 3:
            continue
        scored.append((key, shared))
    scored.sort(key=lambda row: -row[1])
    return scored[:cap]
'''

# The same function again, with every local also renamed. The arm does
# NOT catch this, and the test below pins that rather than hiding it.
RANKER_REWRITTEN = '''
def order_items(target, entries, cap):
    """Something else entirely."""
    results = []
    for name, payload in entries.items():
        common = len(target & payload)
        if common < 3:
            continue
        results.append((name, common))
    results.sort(key=lambda item: -item[1])
    return results[:cap]
'''

UNRELATED = '''
def send_notification(client, recipient, subject, body):
    """Deliver a message and log the outcome."""
    message = client.compose(recipient, subject)
    message.attach(body)
    receipt = client.deliver(message)
    client.log("sent %s to %s", receipt.id, recipient)
    return receipt.id
'''


def _write(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source.lstrip(), encoding="utf-8")
    return path


def _unit(name, path, source):
    lines = source.lstrip().splitlines()
    return CodeUnit(
        unit_id=name,
        path=path,
        kind="function",
        name=name,
        qualname=name,
        start_line=1,
        end_line=len(lines),
    )


def test_constants_match_the_measured_values():
    """These produced docs/similarity.md. They are not knobs."""
    assert SHINGLE_SIZE == 5
    assert MAX_SHINGLE_DOCUMENT_FREQUENCY == 60
    assert MIN_SHARED_SHINGLES == 3
    assert MIN_LINES == 5
    assert MIN_TOKENS == 20


def test_the_benchmark_imports_this_module_rather_than_copying_it():
    """Measured code and shipped code must not be able to drift."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = (root / "benchmarks" / "similarity" / "generators.py").read_text(encoding="utf-8")
    assert "from code_steward.similarity import" in source
    assert "rank_all_pairs" in source


def test_normalise_drops_docstrings_and_formatting():
    spaced = ast.parse('def f(x):\n    """Doc."""\n    return  x  +  1\n').body[0]
    tight = ast.parse("def f(x):\n    return x + 1\n").body[0]
    assert normalise(spaced) == normalise(tight)


def test_tokenise_separates_identifiers_from_punctuation():
    assert tokenise("a_b + c(1)") == ("a_b", "+", "c", "(", "1", ")")


def test_jaccard_is_zero_for_two_empty_sets():
    assert jaccard(frozenset(), frozenset()) == 0.0


def test_jaccard_is_one_for_identical_sets():
    assert jaccard(frozenset({1, 2}), frozenset({1, 2})) == 1.0


def test_shingles_of_a_short_body_are_empty():
    assert shingles(("a", "b")) == frozenset()


def test_a_docstring_rewrite_is_completely_invisible():
    """Normalisation must make prose changes cost nothing."""
    changed = RANKER.replace("Rank rows by overlap with a needle.", "Different words.")
    assert jaccard(draft_shingles(RANKER), draft_shingles(changed)) == 1.0


def test_a_pasted_and_tidied_copy_still_overlaps_strongly():
    """A new name, a new signature, a new docstring: still caught."""
    assert jaccard(draft_shingles(RANKER), draft_shingles(RANKER_RENAMED)) > 0.3


def test_renaming_every_local_defeats_the_arm():
    """A measured limitation, pinned so it cannot be forgotten.

    Shingles are windows over identifiers. Renaming the signature
    leaves most windows intact; renaming every local changes nearly
    all of them. On this fixture the overlap falls from 0.535 to
    0.015. A reimplementation written from scratch in different words
    is therefore invisible to this arm, and `docs/similarity.md` says
    so. Detecting it needs a structural comparator, which is a
    different tool that has not been measured.
    """
    assert jaccard(draft_shingles(RANKER), draft_shingles(RANKER_REWRITTEN)) < 0.05


def test_an_unrelated_function_does_not_overlap():
    assert jaccard(draft_shingles(RANKER), draft_shingles(UNRELATED)) < 0.05


def test_a_draft_that_does_not_parse_raises_rather_than_returning_nothing():
    """Empty and malformed need different responses from a caller."""
    with pytest.raises(SyntaxError):
        draft_shingles("def broken(:\n")


def test_a_draft_with_no_function_is_empty():
    assert draft_shingles("x = 1\n") == frozenset()


def test_a_draft_below_the_token_floor_is_empty():
    assert draft_shingles("def f():\n    return 1\n") == frozenset()


def test_unit_shingles_skips_units_below_the_line_floor(tmp_path):
    _write(tmp_path, "small.py", "def f():\n    return 1\n")
    unit = CodeUnit(
        unit_id="small",
        path="small.py",
        kind="function",
        name="f",
        qualname="f",
        start_line=1,
        end_line=2,
    )
    assert unit_shingles(tmp_path, [unit]) == {}


def test_unit_shingles_skips_classes(tmp_path):
    _write(tmp_path, "ranker.py", RANKER)
    unit = _unit("ranker", "ranker.py", RANKER)
    unit.kind = "class"
    assert unit_shingles(tmp_path, [unit]) == {}


def test_unit_shingles_survives_a_missing_file(tmp_path):
    unit = _unit("gone", "gone.py", RANKER)
    assert unit_shingles(tmp_path, [unit]) == {}


def test_rank_similar_units_finds_the_renamed_copy(tmp_path):
    _write(tmp_path, "a.py", RANKER)
    _write(tmp_path, "b.py", RANKER_RENAMED)
    _write(tmp_path, "c.py", UNRELATED)
    units = [
        _unit("a", "a.py", RANKER),
        _unit("b", "b.py", RANKER_RENAMED),
        _unit("c", "c.py", UNRELATED),
    ]
    prepared = unit_shingles(tmp_path, units)
    matches = rank_similar_units("a", units, prepared)
    assert [match.unit.unit_id for match in matches] == ["b"]
    assert matches[0].shared_shingles >= MIN_SHARED_SHINGLES


def test_a_unit_is_never_similar_to_itself(tmp_path):
    _write(tmp_path, "a.py", RANKER)
    units = [_unit("a", "a.py", RANKER)]
    prepared = unit_shingles(tmp_path, units)
    assert rank_similar_units("a", units, prepared) == []


def test_an_unknown_target_returns_nothing_rather_than_raising(tmp_path):
    assert rank_similar_units("missing", [], {}, 5) == []


def test_rank_against_finds_the_indexed_original_from_a_draft(tmp_path):
    """The pre-implementation case: the code does not exist yet."""
    _write(tmp_path, "a.py", RANKER)
    _write(tmp_path, "c.py", UNRELATED)
    units = [_unit("a", "a.py", RANKER), _unit("c", "c.py", UNRELATED)]
    prepared = unit_shingles(tmp_path, units)
    matches = rank_against(draft_shingles(RANKER_RENAMED), units, prepared)
    assert [match.unit.unit_id for match in matches] == ["a"]


def test_rank_against_an_empty_needle_returns_nothing(tmp_path):
    assert rank_against(frozenset(), [], {}, 5) == []


def test_rank_all_pairs_is_order_independent(tmp_path):
    _write(tmp_path, "a.py", RANKER)
    _write(tmp_path, "b.py", RANKER_RENAMED)
    units = [_unit("a", "a.py", RANKER), _unit("b", "b.py", RANKER_RENAMED)]
    prepared = unit_shingles(tmp_path, units)
    forward = rank_all_pairs(prepared, 10)
    backward = rank_all_pairs(dict(reversed(list(prepared.items()))), 10)
    assert [(row[0], row[1]) for row in forward] == [(row[0], row[1]) for row in backward]


def test_similar_unit_serialises_the_fields_a_packet_needs(tmp_path):
    _write(tmp_path, "a.py", RANKER)
    _write(tmp_path, "b.py", RANKER_RENAMED)
    units = [_unit("a", "a.py", RANKER), _unit("b", "b.py", RANKER_RENAMED)]
    prepared = unit_shingles(tmp_path, units)
    payload = rank_similar_units("a", units, prepared)[0].to_dict()
    for field in ("unit_id", "path", "lines", "score", "shared_shingles"):
        assert field in payload
