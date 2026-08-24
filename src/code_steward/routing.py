"""Resolve the path a route decorator actually serves.

`@router.get("/sku-pins")` does not serve `/sku-pins` when its module
is mounted with `include_router(admin_router, prefix="/api/admin")`.
The indexer stores the decorator literal, which is what the source
says and not what the server answers to. On a repository that mounts
most of its routers under a prefix, that difference is the whole
address.

The join is cross-file by nature -- the prefix is declared where the
router is included, not where the handler is written -- so it cannot
happen inside the per-file indexer and lives here as a pass over the
whole tree instead.

Nothing here infers. A prefix is recorded only when it is written as
a string literal at the mount site; a computed prefix produces no
entry rather than a guess.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .indexer import HTTP_METHODS
from .models import CodeUnit, Endpoint
from .relationships import _import_aliases, _module_key


@dataclass(slots=True, frozen=True)
class RouterPrefix:
    """One router variable and the path it is mounted under."""

    module: str
    router_var: str
    prefix: str


def router_var(decorators: list[str]) -> str:
    """Name the router a route decorator hangs off, if it is one.

    Reads the decorator text the indexer already stores, so this needs
    no new column: `router.get('/x')` yields `router`.
    """
    for text in decorators:
        head, _, _rest = text.partition("(")
        base, _, method = head.rpartition(".")
        if base and method.lower() in HTTP_METHODS:
            return base
    return ""


def join_route(prefix: str, route: str) -> str:
    """Join a mount prefix to a decorator route as a server would."""
    joined = f"{prefix.rstrip('/')}/{route.lstrip('/')}"
    if len(joined) > 1:
        joined = joined.rstrip("/")
    return joined or "/"


def _literal(node: ast.AST | None) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _keyword(call: ast.Call, name: str) -> str:
    for keyword in call.keywords:
        if keyword.arg == name:
            return _literal(keyword.value)
    return ""


def _apirouter_prefixes(tree: ast.Module, module: str) -> list[RouterPrefix]:
    """Prefixes declared on the `APIRouter(...)` call itself."""
    found: list[RouterPrefix] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "APIRouter":
            continue
        prefix = _keyword(node.value, "prefix")
        if not prefix:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                found.append(RouterPrefix(module, target.id, prefix))
    return found


def _include_router_prefixes(tree: ast.Module, module: str) -> list[RouterPrefix]:
    """Prefixes declared where a router is mounted onto its parent.

    The router argument is resolved back through this file's imports,
    so the prefix is recorded against the module that *defines* the
    router rather than the one that mounts it. A router passed as an
    attribute (`admin.router`) resolves the same way.
    """
    _, symbol_aliases = _import_aliases(tree, module)
    found: list[RouterPrefix] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "include_router" or not node.args:
            continue
        prefix = _keyword(node, "prefix")
        if not prefix:
            continue
        argument = node.args[0]
        if isinstance(argument, ast.Name):
            origin = symbol_aliases.get(argument.id)
            if origin:
                found.append(RouterPrefix(origin[0], origin[1], prefix))
        elif isinstance(argument, ast.Attribute) and isinstance(argument.value, ast.Name):
            alias = symbol_aliases.get(argument.value.id)
            owner = alias[0] if alias else argument.value.id
            found.append(RouterPrefix(owner, argument.attr, prefix))
    return found


def scan_prefixes(project_root: Path, paths: list[Path]) -> list[RouterPrefix]:
    """Collect every literal router prefix declared across ``paths``."""
    found: list[RouterPrefix] = []
    for rel_path in paths:
        try:
            text = (project_root / rel_path).read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (OSError, SyntaxError, ValueError):
            continue
        module = _module_key(rel_path.as_posix())
        found.extend(_apirouter_prefixes(tree, module))
        found.extend(_include_router_prefixes(tree, module))
    return sorted(set(found), key=lambda item: (item.module, item.router_var, item.prefix))


def full_routes(
    endpoints: list[Endpoint],
    units: list[CodeUnit],
    prefixes: list[RouterPrefix],
) -> dict[tuple[str, str, str], str]:
    """Map each endpoint to the path a client would actually call.

    Keyed by the endpoint's own primary key so a caller can join it
    back without re-deriving anything. An endpoint whose router has no
    recorded prefix maps to its decorator route unchanged -- absence of
    a prefix is reported as no prefix, never as a guessed one.
    """
    by_module_var = {(item.module, item.router_var): item.prefix for item in prefixes}
    decorators = {unit.unit_id: unit.decorators for unit in units}
    resolved: dict[tuple[str, str, str], str] = {}
    for endpoint in endpoints:
        module = _module_key(endpoint.path)
        variable = router_var(decorators.get(endpoint.unit_id, []))
        prefix = by_module_var.get((module, variable), "")
        key = (endpoint.unit_id, endpoint.method, endpoint.route)
        resolved[key] = join_route(prefix, endpoint.route)
    return resolved
