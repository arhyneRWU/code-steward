"""The frontend half of the map, end to end through the index.

Building an index over a tree with both Python routes and JavaScript
that calls them should leave `FETCHED_BY` edges hanging off the route
handlers -- and should leave none behind on a handler whose caller has
since been deleted, which is the failure mode a refresh pass exists to
prevent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_steward import webclient
from code_steward.db import all_hard_relationships, connect
from code_steward.maintenance import rebuild_index, update_index_files

pytestmark = pytest.mark.skipif(not webclient.available(), reason="tree-sitter not installed")

ROUTES = """\
from fastapi import APIRouter

router = APIRouter()


@router.get("/api/items")
async def list_items():
    \"\"\"List every item.\"\"\"
    return []
"""

MAIN = """\
from fastapi import FastAPI

from app.routes import router

app = FastAPI()
app.include_router(router)
"""

CLIENT = """\
async function loadItems() {
  const response = await fetch('/api/items');
  return response.json();
}
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "routes.py").write_text(ROUTES, encoding="utf-8")
    (tmp_path / "app" / "main.py").write_text(MAIN, encoding="utf-8")
    (tmp_path / "app" / "static").mkdir()
    (tmp_path / "app" / "static" / "items.js").write_text(CLIENT, encoding="utf-8")
    return tmp_path


def _fetched_by(database: Path, unit_id: str) -> list[str]:
    conn = connect(database)
    try:
        edges = all_hard_relationships(conn)
    finally:
        conn.close()
    return sorted(
        edge.target_ref
        for edge in edges
        if edge.relation == webclient.FETCHED_BY and edge.source_unit_id == unit_id
    )


def test_building_an_index_records_the_frontend_caller(tmp_path: Path) -> None:
    root = _project(tmp_path)
    database = root / "index.db"
    rebuild_index(root, database)

    assert _fetched_by(database, "app.routes::list_items") == ["app/static/items.js:2"]


def test_deleting_the_caller_removes_the_edge(tmp_path: Path) -> None:
    root = _project(tmp_path)
    database = root / "index.db"
    rebuild_index(root, database)
    (root / "app" / "static" / "items.js").write_text("// gone\n", encoding="utf-8")

    with connect(database) as conn:
        update_index_files(conn, root, [root / "app" / "static" / "items.js"])

    assert _fetched_by(database, "app.routes::list_items") == []


def test_the_bundle_names_the_browser_callers(tmp_path: Path) -> None:
    from code_steward.db import all_hard_relationships
    from code_steward.trace import build_slice, render_markdown
    from code_steward.webclient import client_callers

    root = _project(tmp_path)
    database = root / "index.db"
    rebuild_index(root, database)

    conn = connect(database)
    try:
        from code_steward.db import all_units

        units = all_units(conn)
        relationships = all_hard_relationships(conn)
    finally:
        conn.close()

    sliced = build_slice("app.routes::list_items", units, relationships)
    rendered = render_markdown(
        root,
        sliced,
        client_calls=client_callers(relationships, "app.routes::list_items"),
    )

    assert "## browser callers" in rendered
    assert "app/static/items.js:2 — GET /api/items" in rendered


def test_a_handler_with_no_browser_caller_says_so(tmp_path: Path) -> None:
    """Silence here is ambiguous, so the bundle must not stay silent."""
    from code_steward.db import all_hard_relationships, all_units
    from code_steward.trace import build_slice, render_markdown

    root = _project(tmp_path)
    (root / "app" / "static" / "items.js").unlink()
    database = root / "index.db"
    rebuild_index(root, database)

    conn = connect(database)
    try:
        units = all_units(conn)
        relationships = all_hard_relationships(conn)
    finally:
        conn.close()

    sliced = build_slice("app.routes::list_items", units, relationships)
    rendered = render_markdown(root, sliced, client_calls=[])

    assert "## browser callers" not in rendered


def test_update_accepts_a_javascript_path(tmp_path: Path, capsys) -> None:
    """Editing a client file must be able to move the edges it owns."""
    from code_steward.cli import db_path, main

    root = _project(tmp_path)
    rebuild_index(root, db_path(root))
    (root / "app" / "static" / "items.js").write_text(
        "\n\nasync function loadItems() {\n  return fetch('/api/items');\n}\n",
        encoding="utf-8",
    )

    exit_code = main(["--root", str(root), "update", str(root / "app" / "static" / "items.js")])
    capsys.readouterr()

    assert exit_code == 0
    assert _fetched_by(db_path(root), "app.routes::list_items") == [
        "app/static/items.js:4"
    ]


def test_unbound_lists_the_call_sites_that_matched_no_route(tmp_path: Path, capsys) -> None:
    """The map must show its own edges, not just its interior."""
    from code_steward.cli import db_path, main

    root = _project(tmp_path)
    (root / "app" / "static" / "extra.js").write_text(
        "const url = base + '/items';\nfetch(url);\nfetch('/api/nope');\n",
        encoding="utf-8",
    )
    rebuild_index(root, db_path(root))

    exit_code = main(["--root", str(root), "endpoints", "--unbound"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "app/static/extra.js:2" in out
    assert "app/static/extra.js:3" in out
    assert "app/static/items.js" not in out


def test_unbound_reports_coverage_rather_than_only_successes(tmp_path: Path, capsys) -> None:
    from code_steward.cli import db_path, main

    root = _project(tmp_path)
    (root / "app" / "static" / "extra.js").write_text("fetch('/api/nope');\n", encoding="utf-8")
    rebuild_index(root, db_path(root))

    main(["--root", str(root), "endpoints", "--unbound"])
    out = capsys.readouterr().out

    assert "1 of 2" in out
