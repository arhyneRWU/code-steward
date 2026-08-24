"""Find where the browser calls this project's HTTP API.

On a full-stack repository half the call graph lives on the other side
of an HTTP boundary. `trace` on a route handler could show every
Python caller and still not name the one screen that actually uses it.

What this extracts is deliberately small: `fetch` and `axios` call
sites whose URL is written as a literal, and the file and line of the
ones whose URL is computed. It does not follow a variable back to its
definition. Chasing `fetch(url)` upstream is inference, and inference
about names is the thing this project has already measured and
rejected once.

Parsing is tree-sitter rather than a regular expression, and the cost
of the dependency buys exactly two things: a commented-out call and a
URL quoted inside another string are both invisible to a parser and
both look like call sites to a regex. Either one would put an edge in
the graph that does not exist.

The dependency is optional. Without it this reports nothing and says
so, rather than reporting an empty result that reads like "no
frontend calls this".
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .db import all_endpoints, all_units, replace_hard_relationships_for_provenance
from .indexer import iter_javascript_files, iter_python_files
from .models import CodeUnit, Endpoint, HardRelationship
from .routing import RouterPrefix, full_routes, scan_prefixes

if TYPE_CHECKING:  # pragma: no cover - typing only
    from tree_sitter import Language

try:  # pragma: no cover - exercised by the availability branch
    import tree_sitter_javascript
    from tree_sitter import Language as _RuntimeLanguage
    from tree_sitter import Parser

    _LANGUAGE: Language | None = _RuntimeLanguage(tree_sitter_javascript.language())
except Exception:  # pragma: no cover - the dependency is optional
    _LANGUAGE = None

# `axios.delete` and friends name the verb in the call itself; a bare
# `axios(...)` carries it in the options object like `fetch` does.
_AXIOS_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
_DEFAULT_METHOD = "GET"


@dataclass(slots=True, frozen=True)
class ClientCall:
    """One browser-side call site into the API.

    ``url`` is empty when the URL is computed rather than written out.
    Such a call site is still reported: it is a real edge this cannot
    resolve, and saying where it is beats pretending it is not there.
    """

    path: str
    line: int
    url: str
    method: str


def available() -> bool:
    """Whether the optional JavaScript parser is installed."""
    return _LANGUAGE is not None


def route_pattern(url: str) -> str:
    """Reduce a URL to the shape a route declaration would match.

    A client writes `/api/items/${id}` and a server declares
    `/api/items/{item_id}`. Both name the same route, so both collapse
    to `/api/items/{}`. A query string names no part of the route and
    is dropped.
    """
    path = url.split("?", 1)[0].split("#", 1)[0]
    out: list[str] = []
    index = 0
    while index < len(path):
        char = path[index]
        if char == "$" and path.startswith("${", index):
            end = path.find("}", index)
            if end == -1:
                break
            out.append("{}")
            index = end + 1
            continue
        if char == "{":
            end = path.find("}", index)
            if end == -1:
                break
            out.append("{}")
            index = end + 1
            continue
        out.append(char)
        index += 1
    pattern = "".join(out)
    if len(pattern) > 1:
        pattern = pattern.rstrip("/")
    return pattern


def _text(node: object) -> str:
    return bytes(node.text).decode("utf-8", "replace")  # type: ignore[attr-defined]


def _literal_url(node: object) -> str | None:
    """Return the URL an argument names, or None if not a literal."""
    kind = node.type  # type: ignore[attr-defined]
    if kind == "string":
        return _text(node)[1:-1]
    if kind == "template_string":
        return _text(node)[1:-1]
    return None


def _options_method(node: object) -> str:
    """Read `{ method: 'POST' }` from a call's options argument."""
    if node.type != "object":  # type: ignore[attr-defined]
        return ""
    for child in node.named_children:  # type: ignore[attr-defined]
        if child.type != "pair":
            continue
        key = child.child_by_field_name("key")
        value = child.child_by_field_name("value")
        if key is None or value is None:
            continue
        name = _text(key).strip("'\"")
        if name != "method":
            continue
        if value.type in {"string", "template_string"}:
            return _text(value)[1:-1].upper()
    return ""


def _callee_method(function_node: object) -> str | None:
    """Classify the callee, returning its HTTP verb or None.

    An empty string means "this is an API client call whose verb is
    not named here" -- `fetch(...)` and bare `axios(...)`.
    """
    kind = function_node.type  # type: ignore[attr-defined]
    if kind == "identifier":
        name = _text(function_node)
        if name in {"fetch", "axios"}:
            return ""
        return None
    if kind == "member_expression":
        prop = function_node.child_by_field_name("property")  # type: ignore[attr-defined]
        obj = function_node.child_by_field_name("object")  # type: ignore[attr-defined]
        if prop is None or obj is None:
            return None
        verb = _text(prop).lower()
        base = _text(obj)
        if base.endswith("axios") and verb in _AXIOS_METHODS:
            return verb.upper()
        # `window.fetch(...)` and `this.fetch(...)` are still fetch.
        if verb == "fetch":
            return ""
        return None
    return None


def _is_internal(url: str) -> bool:
    """Whether a URL addresses this project rather than another host."""
    return url.startswith("/") and not url.startswith("//")


def _calls_in_tree(root: object, rel_path: str) -> list[ClientCall]:
    found: list[ClientCall] = []
    stack = [root]
    while stack:
        node = stack.pop()
        stack.extend(node.named_children)  # type: ignore[attr-defined]
        if node.type != "call_expression":  # type: ignore[attr-defined]
            continue
        function_node = node.child_by_field_name("function")  # type: ignore[attr-defined]
        arguments = node.child_by_field_name("arguments")  # type: ignore[attr-defined]
        if function_node is None or arguments is None:
            continue
        verb = _callee_method(function_node)
        if verb is None:
            continue
        args = [child for child in arguments.named_children if child.type != "comment"]
        if not args:
            continue
        url = _literal_url(args[0])
        if url is not None and not _is_internal(url):
            continue
        method = verb or (_options_method(args[1]) if len(args) > 1 else "")
        found.append(
            ClientCall(
                path=rel_path,
                line=node.start_point[0] + 1,  # type: ignore[attr-defined]
                url=url or "",
                method=method or _DEFAULT_METHOD,
            )
        )
    return found


def scan_calls(project_root: Path, paths: list[Path]) -> list[ClientCall]:
    """Collect every browser-side API call site across ``paths``.

    Returns an empty list when the parser is unavailable. Callers that
    need to distinguish that from "no call sites" must ask
    :func:`available` -- reporting silence as a result is how a
    missing dependency turns into a wrong answer.
    """
    if _LANGUAGE is None:
        return []
    parser = Parser(_LANGUAGE)
    found: list[ClientCall] = []
    for rel_path in paths:
        try:
            source = (project_root / rel_path).read_bytes()
        except OSError:
            continue
        tree = parser.parse(source)
        found.extend(_calls_in_tree(tree.root_node, rel_path.as_posix()))
    return sorted(found, key=lambda call: (call.path, call.line, call.url))


FETCHED_BY = "FETCHED_BY"
WEB_CLIENT_PROVENANCE = "web-client"


def route_edges(
    endpoints: list[Endpoint],
    units: list[CodeUnit],
    prefixes: list[RouterPrefix],
    calls: list[ClientCall],
) -> tuple[list[HardRelationship], list[ClientCall]]:
    """Bind client call sites to the handlers they hit.

    Returns the edges and the call sites that bound to nothing. Both
    halves matter: the second is the honest edge of the map, and a
    caller that reports only the first is claiming a coverage it does
    not have.

    A pattern served by two handlers binds to neither. That is a
    resolution failure, and this project's measured position is that
    an unresolved edge is cheaper than a guessed one.
    """
    resolved = full_routes(endpoints, units, prefixes)
    by_pattern: dict[tuple[str, str], list[str]] = {}
    for endpoint in endpoints:
        key = (endpoint.unit_id, endpoint.method, endpoint.route)
        pattern = route_pattern(resolved[key])
        by_pattern.setdefault((endpoint.method, pattern), []).append(endpoint.unit_id)

    edges: list[HardRelationship] = []
    unmatched: list[ClientCall] = []
    for call in calls:
        owners = by_pattern.get((call.method, route_pattern(call.url))) if call.url else None
        if not owners or len(set(owners)) != 1:
            unmatched.append(call)
            continue
        edges.append(
            HardRelationship(
                source_unit_id=owners[0],
                relation=FETCHED_BY,
                target_kind="client_call",
                target_ref=f"{call.path}:{call.line}",
                provenance=WEB_CLIENT_PROVENANCE,
                evidence={"url": call.url, "method": call.method},
            )
        )
    return edges, unmatched


def refresh_web_client_relationships(
    conn: sqlite3.Connection,
    project_root: Path,
    excludes: Iterable[str] = (),
) -> tuple[int, int]:
    """Re-derive every frontend-to-route edge in the index.

    Returns the number of edges written and the number of call sites
    that matched no route. Edges are replaced for *every* endpoint
    unit, not only the ones that gained a caller: a handler whose last
    caller was deleted must end up with no edges, and a pass that only
    writes what it found would leave the old one behind.

    Without the optional parser this writes nothing at all and reports
    zero of both, rather than clearing the edges an earlier run with
    the parser installed had recorded.
    """
    if _LANGUAGE is None:
        return 0, 0

    units = all_units(conn)
    endpoints = all_endpoints(conn)
    prefixes = scan_prefixes(
        project_root,
        [path.relative_to(project_root) for path in iter_python_files(project_root, excludes)],
    )
    calls = scan_calls(
        project_root,
        [path.relative_to(project_root) for path in iter_javascript_files(project_root, excludes)],
    )
    edges, unmatched = route_edges(endpoints, units, prefixes, calls)

    by_source: dict[str, list[HardRelationship]] = {endpoint.unit_id: [] for endpoint in endpoints}
    for edge in edges:
        by_source.setdefault(edge.source_unit_id, []).append(edge)
    for source_unit_id, source_edges in by_source.items():
        replace_hard_relationships_for_provenance(
            conn,
            source_unit_id,
            WEB_CLIENT_PROVENANCE,
            source_edges,
        )
    return len(edges), len(unmatched)


def client_callers(relationships: list[HardRelationship], unit_id: str) -> list[str]:
    """Describe the browser call sites recorded against one handler."""
    lines = [
        f"{edge.target_ref} — {edge.evidence.get('method', '')} {edge.evidence.get('url', '')}"
        for edge in relationships
        if edge.relation == FETCHED_BY and edge.source_unit_id == unit_id
    ]
    return sorted(lines)
