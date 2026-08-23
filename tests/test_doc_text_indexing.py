"""Full docstring bodies are indexed for scoring but not emitted."""

from dataclasses import replace
from pathlib import Path

from code_steward.indexer import DOC_TEXT_LIMIT, index_python_file
from code_steward.models import CodeUnit
from code_steward.packet import build_packet
from code_steward.search import search_units

MULTILINE = '''
def wait_for_server(timeout):
    """Send the request and return the response.

    :param timeout: how long to wait for the server to send data
        before giving up, as a float.
    """
    return timeout
'''


def _index(tmp_path: Path, source: str) -> list[CodeUnit]:
    (tmp_path / "mod.py").write_text(source, encoding="utf-8")
    units, _ = index_python_file(tmp_path, tmp_path / "mod.py")
    return units


def test_doc_text_holds_the_whole_docstring(tmp_path: Path) -> None:
    unit = _index(tmp_path, MULTILINE)[0]

    assert unit.purpose == "Send the request and return the response."
    assert "how long to wait" in unit.doc_text
    assert "\n" not in unit.doc_text


def test_doc_text_is_empty_without_a_docstring(tmp_path: Path) -> None:
    unit = _index(tmp_path, "def plain():\n    return 1\n")[0]

    assert unit.doc_text == ""
    assert unit.purpose == "plain"


def test_doc_text_is_capped(tmp_path: Path) -> None:
    body = "word " * 4000
    unit = _index(tmp_path, f'def big():\n    """Summary.\n\n    {body}\n    """\n')[0]

    assert len(unit.doc_text) <= DOC_TEXT_LIMIT


def test_body_wording_can_retrieve_a_unit(tmp_path: Path) -> None:
    """A query matching only the body must still find the unit."""
    units = _index(tmp_path, MULTILINE)
    query = "how long to wait before giving up on a slow server"

    scored = search_units(units, query)
    stripped = [replace(unit, doc_text="") for unit in units]

    assert scored[0].score > search_units(stripped, query)[0].score


def test_a_strong_summary_is_not_diluted_by_its_body(tmp_path: Path) -> None:
    """Score the better of summary and body, never the body alone."""
    units = _index(tmp_path, MULTILINE)
    query = "send the request and return the response"

    summary_only = [replace(unit, doc_text="") for unit in units]

    assert search_units(units, query)[0].score >= search_units(summary_only, query)[0].score


def test_packet_emits_the_summary_not_the_body(tmp_path: Path) -> None:
    units = _index(tmp_path, MULTILINE)

    packet = build_packet("send a request", search_units(units, "send a request"), [])
    emitted = packet["candidates"][0]

    assert emitted["purpose"] == "Send the request and return the response."
    assert "how long to wait" not in str(packet)
