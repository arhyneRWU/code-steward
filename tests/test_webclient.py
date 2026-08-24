"""Frontend call sites: where the browser actually hits the API.

A full-stack repository keeps half its call graph on the other side of
an HTTP boundary. `trace` on a route handler stopped at that boundary
and showed nothing of the JavaScript that calls it.

This scans for `fetch` and `axios` call sites and reports the URL when
it is written as a literal. It does not chase a computed URL back to
its definition -- an unbound call site is reported as unbound, with
its file and line, because a half map you can see the edges of is
useful and one that looks complete is worse than none.

Tree-sitter rather than a regex, for the two cases at the bottom:
a commented-out call and a URL quoted inside another string both
produce phantom edges under a regex, and phantom edges are the
failure mode this project has already been bitten by.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_steward import webclient

requires_parser = pytest.mark.skipif(not webclient.available(), reason="tree-sitter not installed")


def _scan(tmp_path: Path, source: str) -> list[webclient.ClientCall]:
    (tmp_path / "app.js").write_text(source, encoding="utf-8")
    return webclient.scan_calls(tmp_path, [Path("app.js")])


def test_route_pattern_collapses_a_template_placeholder() -> None:
    assert webclient.route_pattern("/api/items/${id}/edit") == "/api/items/{}/edit"


def test_route_pattern_collapses_a_fastapi_path_parameter() -> None:
    assert webclient.route_pattern("/api/items/{item_id}/edit") == "/api/items/{}/edit"


def test_route_pattern_drops_a_query_string() -> None:
    assert webclient.route_pattern("/api/items?page=2") == "/api/items"


def test_route_pattern_leaves_a_plain_path() -> None:
    assert webclient.route_pattern("/api/items") == "/api/items"


@requires_parser
def test_a_literal_fetch_defaults_to_get(tmp_path: Path) -> None:
    (call,) = _scan(tmp_path, "fetch('/api/items');\n")
    assert (call.path, call.line, call.url, call.method) == ("app.js", 1, "/api/items", "GET")


@requires_parser
def test_a_literal_method_is_read_from_the_options(tmp_path: Path) -> None:
    (call,) = _scan(tmp_path, "fetch('/api/items', { method: 'POST' });\n")
    assert call.method == "POST"


@requires_parser
def test_a_template_literal_url_is_captured_with_its_placeholder(tmp_path: Path) -> None:
    (call,) = _scan(tmp_path, "fetch(`/api/items/${id}`);\n")
    assert call.url == "/api/items/${id}"


@requires_parser
def test_axios_names_its_method_from_the_call(tmp_path: Path) -> None:
    (call,) = _scan(tmp_path, "axios.post('/api/items', body);\n")
    assert (call.url, call.method) == ("/api/items", "POST")


@requires_parser
def test_a_computed_url_is_reported_as_unbound_not_dropped(tmp_path: Path) -> None:
    (call,) = _scan(tmp_path, "const url = base + '/items';\nfetch(url);\n")
    assert (call.url, call.line) == ("", 2)


@requires_parser
def test_an_external_url_is_not_a_call_into_this_api(tmp_path: Path) -> None:
    assert _scan(tmp_path, "fetch('https://example.com/api/items');\n") == []


@requires_parser
def test_a_commented_out_call_is_not_a_call_site(tmp_path: Path) -> None:
    assert _scan(tmp_path, "// fetch('/api/items');\n/* fetch('/api/other'); */\n") == []


@requires_parser
def test_a_url_quoted_inside_another_string_is_not_a_call_site(tmp_path: Path) -> None:
    assert _scan(tmp_path, "const help = \"call fetch('/api/items') to load\";\n") == []


@requires_parser
def test_an_unparsable_file_is_skipped_rather_than_raising(tmp_path: Path) -> None:
    (tmp_path / "broken.js").write_text("function (((", encoding="utf-8")
    assert webclient.scan_calls(tmp_path, [Path("broken.js")]) == []


def test_minified_and_vendored_javascript_is_not_walked(tmp_path: Path) -> None:
    """A bundle is not source, and one 200KB line is not a call site."""
    from code_steward.indexer import iter_javascript_files

    (tmp_path / "app").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "app" / "pins.js").write_text("fetch('/api/x');\n", encoding="utf-8")
    (tmp_path / "app" / "jquery.min.js").write_text("fetch('/api/y');\n", encoding="utf-8")
    (tmp_path / "app" / "bundle.bundle.js").write_text("fetch('/api/z');\n", encoding="utf-8")
    (tmp_path / "node_modules" / "dep.js").write_text("fetch('/api/w');\n", encoding="utf-8")

    walked = sorted(p.relative_to(tmp_path).as_posix() for p in iter_javascript_files(tmp_path))

    assert walked == ["app/pins.js"]


def test_without_the_parser_the_scan_reports_nothing(tmp_path: Path, monkeypatch) -> None:
    """Degradation must be silence in the data, never a wrong answer."""
    monkeypatch.setattr(webclient, "_LANGUAGE", None)
    (tmp_path / "app.js").write_text("fetch('/api/items');\n", encoding="utf-8")

    assert webclient.available() is False
    assert webclient.scan_calls(tmp_path, [Path("app.js")]) == []


def test_without_the_parser_a_refresh_leaves_existing_edges_alone(monkeypatch) -> None:
    """Clearing edges a working install recorded would be data loss."""
    monkeypatch.setattr(webclient, "_LANGUAGE", None)

    assert webclient.refresh_web_client_relationships(None, Path(".")) == (0, 0)


def test_without_the_parser_unbound_says_what_is_missing(tmp_path: Path, monkeypatch, capsys):
    """Silence would read as full coverage, which is the wrong answer."""
    from code_steward.cli import cmd_unbound

    monkeypatch.setattr(webclient, "_LANGUAGE", None)

    exit_code = cmd_unbound(tmp_path, [], [])

    assert exit_code == 1
    assert "code-steward[js]" in capsys.readouterr().err
