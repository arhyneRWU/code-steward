"""Tracing from the entry points, which is where a reader starts.

An endpoint is a **selector**: it names the root of a path. Following
it downward carves the request handler and everything it calls out of
the program, which is the shape that made a function follower useful
when context windows were small.

Callers are not walked by default here. Nothing in the repository
calls a route handler -- the framework does -- so walking up from an
endpoint finds nothing, and walking down finds the implementation.
"""

from __future__ import annotations

import json

import pytest

from code_steward.cli import main
from code_steward.maintenance import rebuild_index

SOURCE = '''\
from fastapi import APIRouter

router = APIRouter()


def normalise(name):
    """Strip and case-fold a submitted name."""
    cleaned = name.strip()
    lowered = cleaned.lower()
    return lowered


def persist(name):
    """Write the organism and return its identifier."""
    key = normalise(name)
    record = {"name": key}
    return record


@router.post("/organisms")
def create_organism(name: str):
    """Create one organism."""
    return persist(name)
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "api.py").write_text(SOURCE, encoding="utf-8")
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    return tmp_path


def test_endpoints_emits_a_bundle_per_route(project, capsys):
    assert main(["--root", str(project), "trace", "--endpoints"]) == 0
    out = capsys.readouterr().out
    assert "# api::create_organism" in out
    assert "POST /organisms" in out


def test_the_route_bundle_reaches_the_implementation(project, capsys):
    """A handler that delegates twice is the normal shape.

    One hop finds `persist` and hands over a call with no body behind
    it, so the default depth for this mode has to be two.
    """
    assert main(["--root", str(project), "trace", "--endpoints"]) == 0
    out = capsys.readouterr().out
    assert "api::persist" in out
    assert "api::normalise" in out


def test_endpoints_reaches_the_json(project, capsys):
    assert main(["--root", str(project), "trace", "--endpoints", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["endpoint"] == "POST /organisms"


def test_endpoints_composes_with_dry(project, capsys):
    """The stitch: entry point, whole path, duplication, one bundle."""
    assert main(["--root", str(project), "trace", "--endpoints", "--dry"]) == 0
    assert "## duplication" in capsys.readouterr().out


def test_a_repository_with_no_routes_says_so(tmp_path, capsys):
    (tmp_path / "plain.py").write_text(
        "def helper(value):\n    total = value * 2\n    return total + 1\n", encoding="utf-8"
    )
    rebuild_index(tmp_path, tmp_path / ".code-steward" / "index.sqlite3")
    assert main(["--root", str(tmp_path), "trace", "--endpoints"]) == 0
    assert "no FastAPI endpoints" in capsys.readouterr().out
