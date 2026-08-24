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


def _callee_method(function_node: object, wrappers: frozenset[str]) -> str | None:
    """Classify the callee, returning its HTTP verb or None.

    An empty string means "this is an API client call whose verb is
    not named here" -- `fetch(...)` and bare `axios(...)`.
    """
    kind = function_node.type  # type: ignore[attr-defined]
    if kind == "identifier":
        name = _text(function_node)
        if name in {"fetch", "axios"} or name in wrappers:
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
        # `window.fetch(...)` and `this.fetch(...)` are still fetch,
        # and so is `api.apiFetchJson(...)` for a detected wrapper.
        if verb == "fetch" or verb in wrappers:
            return ""
        return None
    return None


def _is_internal(url: str) -> bool:
    """Whether a URL addresses this project rather than another host."""
    return url.startswith("/") and not url.startswith("//")


_FUNCTION_NODES = {"function_declaration", "function_expression", "arrow_function"}


def _first_parameter(node: object) -> str:
    """Name the function's first parameter, or "" if it has none."""
    params = node.child_by_field_name("parameters")  # type: ignore[attr-defined]
    if params is None:
        # `url => fetch(url)` has a bare identifier, no list.
        single = node.child_by_field_name("parameter")  # type: ignore[attr-defined]
        return _text(single) if single is not None and single.type == "identifier" else ""
    for child in params.named_children:
        if child.type == "identifier":
            return _text(child)
        if child.type in {"required_parameter", "optional_parameter", "assignment_pattern"}:
            inner = child.child_by_field_name("pattern") or child.child_by_field_name("left")
            if inner is not None and inner.type == "identifier":
                return _text(inner)
        return ""
    return ""


def _passes_parameter_to_fetch(node: object, parameter: str) -> bool:
    """Whether this function hands ``parameter`` to `fetch` as the URL.

    The check is deliberately local and syntactic: the parameter must
    appear in `fetch`'s first argument slot inside this function's own
    body. A function that merely mentions `fetch` somewhere, or that
    fetches a fixed path while taking an unrelated first argument, is
    not a client wrapper -- treating it as one would attach call sites
    to routes they never touch.
    """
    if not parameter:
        return False
    stack = [node]
    while stack:
        current = stack.pop()
        stack.extend(current.named_children)  # type: ignore[attr-defined]
        if current.type != "call_expression":  # type: ignore[attr-defined]
            continue
        function_node = current.child_by_field_name("function")  # type: ignore[attr-defined]
        arguments = current.child_by_field_name("arguments")  # type: ignore[attr-defined]
        if function_node is None or arguments is None:
            continue
        name = (
            _text(function_node.child_by_field_name("property"))
            if function_node.type == "member_expression"
            and function_node.child_by_field_name("property") is not None
            else _text(function_node)
        )
        if name != "fetch":
            continue
        args = arguments.named_children
        if args and args[0].type == "identifier" and _text(args[0]) == parameter:
            return True
    return False


def _wrapper_names(root: object) -> set[str]:
    """Find functions in this file that are thin wrappers over `fetch`.

    Most codebases do not call `fetch` at the call site; they call
    their own client. Hardcoding `fetch` made this blind to 83 of one
    repository's call sites, which is the same hardcoding the
    repo-specific script it was meant to improve on already had.
    """
    found: set[str] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        stack.extend(node.named_children)  # type: ignore[attr-defined]
        kind = node.type  # type: ignore[attr-defined]
        if kind == "function_declaration":
            name_node = node.child_by_field_name("name")  # type: ignore[attr-defined]
            if name_node is not None and _passes_parameter_to_fetch(node, _first_parameter(node)):
                found.add(_text(name_node))
        elif kind == "variable_declarator":
            value = node.child_by_field_name("value")  # type: ignore[attr-defined]
            name_node = node.child_by_field_name("name")  # type: ignore[attr-defined]
            if (
                value is not None
                and name_node is not None
                and value.type in _FUNCTION_NODES
                and _passes_parameter_to_fetch(value, _first_parameter(value))
            ):
                found.add(_text(name_node))
    return found


def _calls_in_tree(root: object, rel_path: str, wrappers: frozenset[str]) -> list[ClientCall]:
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
        verb = _callee_method(function_node, wrappers)
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

    # Two passes. A client wrapper is usually defined in a shared
    # module and called from everywhere else, so the whole tree has to
    # be read before any call site can be classified -- a single pass
    # would recognise only the wrappers that happen to be declared
    # before their callers in walk order.
    trees = []
    wrappers: set[str] = set()
    for rel_path in paths:
        try:
            source = (project_root / rel_path).read_bytes()
        except OSError:
            continue
        tree = parser.parse(source)
        trees.append((rel_path.as_posix(), tree))
        wrappers |= _wrapper_names(tree.root_node)

    frozen = frozenset(wrappers)
    found: list[ClientCall] = []
    for rel_posix, tree in trees:
        found.extend(_calls_in_tree(tree.root_node, rel_posix, frozen))
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


def unbound_reason(call: ClientCall) -> str:
    """Say why a call site bound to nothing, without overclaiming.

    Three outcomes, and the distinction between the last two is the
    point. "No route" invites deleting the endpoint, so it is reserved
    for a URL this could actually have matched: fully literal, no
    interpolation. A URL carrying `${...}` was never resolvable -- a
    whole path segment may be a variable -- and reporting that as dead
    is a guess in a result's clothing. On one repository 18 of 34
    such verdicts were interpolated.
    """
    if not call.url:
        return "computed URL"
    if "${" in call.url:
        return f"unresolved interpolation in {call.method} {call.url}"
    return f"no route for {call.method} {call.url}"
