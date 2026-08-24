"""Router prefixes: an endpoint's route is not what its decorator says.

`@router.get("/sku-pins")` in a module mounted with
`include_router(admin_router, prefix="/api/admin")` serves
`/api/admin/sku-pins`. Storing the decorator literal alone was a
silent lie: on NIS-DocIntell 130 of 234 route decorators are mounted
under a prefix, so `--endpoints` reported paths no client could call.

The join is cross-file, so it cannot happen in the per-file indexer.
"""

from __future__ import annotations

from pathlib import Path

from code_steward.routing import RouterPrefix, join_route, router_var, scan_prefixes


def test_router_var_comes_from_the_decorator_text() -> None:
    assert router_var(["admin_router.get('/x')"]) == "admin_router"


def test_router_var_ignores_decorators_that_are_not_routes() -> None:
    assert router_var(["staticmethod", "cache(maxsize=1)"]) == ""


def test_join_route_prepends_the_prefix() -> None:
    assert join_route("/api/admin", "/sku-pins") == "/api/admin/sku-pins"


def test_join_route_does_not_double_a_slash() -> None:
    assert join_route("/api/admin/", "/sku-pins") == "/api/admin/sku-pins"


def test_join_route_keeps_a_bare_prefix_route() -> None:
    """A router mounted at a prefix may serve the prefix itself."""
    assert join_route("/api/admin", "/") == "/api/admin"


def test_join_route_without_a_prefix_is_the_route() -> None:
    assert join_route("", "/sku-pins") == "/sku-pins"


def test_scan_finds_an_include_router_prefix_across_files(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "admin.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n",
        encoding="utf-8",
    )
    (tmp_path / "app" / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "from app.admin import router as admin_router\n"
        "app = FastAPI()\n"
        "app.include_router(admin_router, prefix='/api/admin')\n",
        encoding="utf-8",
    )

    found = scan_prefixes(tmp_path, [Path("app/admin.py"), Path("app/main.py")])

    assert found == [RouterPrefix(module="app.admin", router_var="router", prefix="/api/admin")]


def test_scan_finds_a_prefix_declared_on_the_apirouter_itself(tmp_path: Path) -> None:
    (tmp_path / "admin.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter(prefix='/api/admin')\n",
        encoding="utf-8",
    )

    found = scan_prefixes(tmp_path, [Path("admin.py")])

    assert found == [RouterPrefix(module="admin", router_var="router", prefix="/api/admin")]


def test_scan_ignores_include_router_without_a_prefix(tmp_path: Path) -> None:
    (tmp_path / "admin.py").write_text("router = APIRouter()\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from admin import router\napp.include_router(router)\n",
        encoding="utf-8",
    )

    assert scan_prefixes(tmp_path, [Path("admin.py"), Path("main.py")]) == []


def test_full_routes_apply_the_prefix_to_the_matching_module(tmp_path: Path) -> None:
    from code_steward.models import CodeUnit, Endpoint
    from code_steward.routing import full_routes

    unit = CodeUnit(
        unit_id="app.admin:list_pins",
        path="app/admin.py",
        kind="function",
        name="list_pins",
        qualname="list_pins",
        start_line=1,
        end_line=2,
        decorators=["router.get('/sku-pins')"],
    )
    endpoint = Endpoint(unit_id=unit.unit_id, path="app/admin.py", method="GET", route="/sku-pins")
    prefixes = [RouterPrefix(module="app.admin", router_var="router", prefix="/api/admin")]

    assert full_routes([endpoint], [unit], prefixes) == {
        ("app.admin:list_pins", "GET", "/sku-pins"): "/api/admin/sku-pins"
    }


def test_full_routes_leave_an_unmounted_route_alone() -> None:
    from code_steward.models import CodeUnit, Endpoint
    from code_steward.routing import full_routes

    unit = CodeUnit(
        unit_id="app.pub:health",
        path="app/pub.py",
        kind="function",
        name="health",
        qualname="health",
        start_line=1,
        end_line=2,
        decorators=["router.get('/health')"],
    )
    endpoint = Endpoint(unit_id=unit.unit_id, path="app/pub.py", method="GET", route="/health")

    assert full_routes([endpoint], [unit], []) == {("app.pub:health", "GET", "/health"): "/health"}


def test_full_routes_do_not_borrow_a_prefix_from_another_router() -> None:
    """Two routers in one module must not share a mount point."""
    from code_steward.models import CodeUnit, Endpoint
    from code_steward.routing import full_routes

    unit = CodeUnit(
        unit_id="app.admin:public_ping",
        path="app/admin.py",
        kind="function",
        name="public_ping",
        qualname="public_ping",
        start_line=1,
        end_line=2,
        decorators=["public_router.get('/ping')"],
    )
    endpoint = Endpoint(unit_id=unit.unit_id, path="app/admin.py", method="GET", route="/ping")
    prefixes = [RouterPrefix(module="app.admin", router_var="router", prefix="/api/admin")]

    assert full_routes([endpoint], [unit], prefixes) == {
        ("app.admin:public_ping", "GET", "/ping"): "/ping"
    }


def test_endpoints_prints_the_mounted_path_not_the_decorator(tmp_path: Path, capsys) -> None:
    """The decorator literal is not an address a client can call."""
    from code_steward.cli import db_path, main
    from code_steward.maintenance import rebuild_index

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "admin.py").write_text(
        'from fastapi import APIRouter\n'
        'router = APIRouter()\n'
        '@router.get("/sku-pins")\n'
        'async def list_pins():\n'
        '    return []\n',
        encoding="utf-8",
    )
    (tmp_path / "app" / "main.py").write_text(
        "from app.admin import router\n"
        "app.include_router(router, prefix='/api/admin')\n",
        encoding="utf-8",
    )
    rebuild_index(tmp_path, db_path(tmp_path))

    main(["--root", str(tmp_path), "endpoints"])

    assert "/api/admin/sku-pins" in capsys.readouterr().out
