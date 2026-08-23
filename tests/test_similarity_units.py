"""Check the unit extraction the similarity arms all read from."""

from __future__ import annotations

import ast

from benchmarks.similarity.units import normalise, tokenise


def _fn(source: str) -> ast.AST:
    return ast.parse(source).body[0]


def test_normalise_drops_the_docstring():
    node = _fn('def f(x):\n    """Say something."""\n    return x + 1\n')
    assert "Say something" not in normalise(node)
    assert "return x + 1" in normalise(node)


def test_normalise_drops_comments_and_formatting():
    spaced = _fn("def f(x):\n    # a comment\n    return  x   +   1\n")
    tight = _fn("def f(x):\n    return x + 1\n")
    assert normalise(spaced) == normalise(tight)


def test_normalise_keeps_identifiers():
    left = _fn("def f(alpha):\n    return alpha\n")
    right = _fn("def f(beta):\n    return beta\n")
    assert normalise(left) != normalise(right)


def test_normalise_survives_a_body_that_was_only_a_docstring():
    node = _fn('def f():\n    """Only this."""\n')
    assert normalise(node).strip().endswith("pass")


def test_tokenise_splits_identifiers_from_punctuation():
    assert tokenise("a_b + c(1)") == ("a_b", "+", "c", "(", "1", ")")
