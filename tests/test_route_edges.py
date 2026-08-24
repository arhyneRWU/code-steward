"""Joining a browser call site to the route handler it hits.

The edge hangs off the Python unit, so it needs no new table: the
handler is the source, the JavaScript line is the target, and
`hard_relationships` already stores a free-text target kind.

The join is string equality after one normalisation, on purpose. Both
sides are reduced to a route pattern -- `${id}` and `{item_id}` both
become `{}` -- and nothing else is inferred. A call site that matches
no route is returned as unmatched rather than attached to the nearest
thing, because a wrong edge costs more than a missing one.
"""

from __future__ import annotations

from code_steward.models import CodeUnit, Endpoint
from code_steward.routing import RouterPrefix
from code_steward.webclient import FETCHED_BY, WEB_CLIENT_PROVENANCE, ClientCall, route_edges


def _handler(unit_id: str, decorator: str) -> CodeUnit:
    return CodeUnit(
        unit_id=unit_id,
        path="app/admin.py",
        kind="function",
        name=unit_id.split(":")[-1],
        qualname=unit_id.split(":")[-1],
        start_line=1,
        end_line=2,
        decorators=[decorator],
    )


def test_a_literal_url_binds_to_its_handler() -> None:
    unit = _handler("app.admin:list_pins", "router.get('/api/admin/sku-pins')")
    endpoint = Endpoint(unit.unit_id, "app/admin.py", "GET", "/api/admin/sku-pins")
    call = ClientCall("app/static/js/pins.js", 12, "/api/admin/sku-pins", "GET")

    edges, unmatched = route_edges([endpoint], [unit], [], [call])

    assert unmatched == []
    (edge,) = edges
    assert edge.source_unit_id == "app.admin:list_pins"
    assert edge.relation == FETCHED_BY
    assert edge.target_kind == "client_call"
    assert edge.target_ref == "app/static/js/pins.js:12"
    assert edge.provenance == WEB_CLIENT_PROVENANCE


def test_a_prefixed_handler_binds_to_the_full_client_url() -> None:
    """The client writes the mounted path, not the decorator literal."""
    unit = _handler("app.admin:list_pins", "router.get('/sku-pins')")
    endpoint = Endpoint(unit.unit_id, "app/admin.py", "GET", "/sku-pins")
    prefixes = [RouterPrefix("app.admin", "router", "/api/admin")]
    call = ClientCall("app/static/js/pins.js", 12, "/api/admin/sku-pins", "GET")

    edges, unmatched = route_edges([endpoint], [unit], prefixes, [call])

    assert unmatched == []
    assert edges[0].source_unit_id == "app.admin:list_pins"


def test_a_placeholder_matches_a_path_parameter() -> None:
    unit = _handler("app.admin:get_pin", "router.get('/api/admin/pins/{pin_id}')")
    endpoint = Endpoint(unit.unit_id, "app/admin.py", "GET", "/api/admin/pins/{pin_id}")
    call = ClientCall("app/static/js/pins.js", 30, "/api/admin/pins/${id}", "GET")

    edges, unmatched = route_edges([endpoint], [unit], [], [call])

    assert unmatched == []
    assert edges[0].evidence["url"] == "/api/admin/pins/${id}"


def test_the_method_is_part_of_the_match() -> None:
    unit = _handler("app.admin:create_pin", "router.post('/api/admin/sku-pins')")
    endpoint = Endpoint(unit.unit_id, "app/admin.py", "POST", "/api/admin/sku-pins")
    call = ClientCall("app/static/js/pins.js", 12, "/api/admin/sku-pins", "GET")

    edges, unmatched = route_edges([endpoint], [unit], [], [call])

    assert edges == []
    assert unmatched == [call]


def test_a_computed_url_is_unmatched_not_guessed() -> None:
    unit = _handler("app.admin:list_pins", "router.get('/api/admin/sku-pins')")
    endpoint = Endpoint(unit.unit_id, "app/admin.py", "GET", "/api/admin/sku-pins")
    call = ClientCall("app/static/js/pins.js", 12, "", "GET")

    edges, unmatched = route_edges([endpoint], [unit], [], [call])

    assert edges == []
    assert unmatched == [call]


def test_one_url_hitting_two_handlers_binds_to_neither() -> None:
    """An ambiguous route is a resolution failure, not a coin toss."""
    first = _handler("app.admin:a", "router.get('/api/x')")
    second = CodeUnit(
        unit_id="app.other:b",
        path="app/other.py",
        kind="function",
        name="b",
        qualname="b",
        start_line=1,
        end_line=2,
        decorators=["router.get('/api/x')"],
    )
    endpoints = [
        Endpoint(first.unit_id, "app/admin.py", "GET", "/api/x"),
        Endpoint(second.unit_id, "app/other.py", "GET", "/api/x"),
    ]
    call = ClientCall("app/static/js/x.js", 3, "/api/x", "GET")

    edges, unmatched = route_edges(endpoints, [first, second], [], [call])

    assert edges == []
    assert unmatched == [call]


def test_client_callers_reads_the_edges_back_for_one_handler() -> None:
    from code_steward.webclient import client_callers

    unit = _handler("app.admin:list_pins", "router.get('/api/admin/sku-pins')")
    endpoint = Endpoint(unit.unit_id, "app/admin.py", "GET", "/api/admin/sku-pins")
    calls = [
        ClientCall("app/static/js/pins.js", 12, "/api/admin/sku-pins", "GET"),
        ClientCall("app/static/js/other.js", 4, "/api/admin/sku-pins", "GET"),
    ]
    edges, _ = route_edges([endpoint], [unit], [], calls)

    assert client_callers(edges, "app.admin:list_pins") == [
        "app/static/js/other.js:4 — GET /api/admin/sku-pins",
        "app/static/js/pins.js:12 — GET /api/admin/sku-pins",
    ]


def test_client_callers_of_an_unrelated_unit_is_empty() -> None:
    from code_steward.webclient import client_callers

    unit = _handler("app.admin:list_pins", "router.get('/api/admin/sku-pins')")
    endpoint = Endpoint(unit.unit_id, "app/admin.py", "GET", "/api/admin/sku-pins")
    call = ClientCall("app/static/js/pins.js", 12, "/api/admin/sku-pins", "GET")
    edges, _ = route_edges([endpoint], [unit], [], [call])

    assert client_callers(edges, "app.admin:other") == []
