from code_steward.models import CodeUnit
from code_steward.search import search_units


def test_search_prefers_taxonomy_intent():
    units = [
        CodeUnit(
            "a",
            "a.py",
            "function",
            "normalize_taxon_name",
            "normalize_taxon_name",
            1,
            2,
            signature="normalize_taxon_name(name: str) -> Taxon",
            purpose="Normalize species names and resolve aliases",
            concepts=["taxonomy", "species", "aliases"],
            returns="Taxon",
        ),
        CodeUnit(
            "b",
            "b.py",
            "function",
            "calculate_total",
            "calculate_total",
            1,
            2,
            signature="calculate_total(price: float) -> float",
            purpose="Calculate invoice total",
            concepts=["invoice", "price"],
            returns="float",
        ),
    ]

    results = search_units(
        units,
        "resolve species scientific name taxonomy",
        return_type="Taxon",
    )

    assert results[0].unit.unit_id == "a"
    assert results[0].evidence["type_bonus"] > 0


def test_body_terms_lift_a_unit_whose_metadata_says_nothing():
    """The signal the control arm found, now scored.

    Neither unit is documented, so purpose falls back to the
    identifier and no metadata field distinguishes them. Only the body
    knows which one mentions the query's terms.
    """
    from code_steward.lexical import body_terms

    matching = CodeUnit(
        unit_id="m",
        path="a.py",
        kind="function",
        name="handler",
        qualname="a.handler",
        start_line=1,
        end_line=9,
        body_terms=body_terms("def handler(self):\n    return rebuild_proxies(self.env)"),
    )
    other = CodeUnit(
        unit_id="o",
        path="b.py",
        kind="function",
        name="handler",
        qualname="b.handler",
        start_line=1,
        end_line=9,
        body_terms=body_terms("def handler(self):\n    return render_template(self.env)"),
    )
    ranked = search_units([other, matching], "rebuild proxies", limit=2)
    assert ranked[0].unit.unit_id == "m"
    assert ranked[0].evidence["body"] > ranked[1].evidence["body"]


def test_a_unit_with_no_indexed_body_still_scores_on_metadata():
    """Older indexes have no body_terms; they must not crash or zero."""
    unit = CodeUnit(
        unit_id="u",
        path="a.py",
        kind="function",
        name="select_proxy",
        qualname="a.select_proxy",
        start_line=1,
        end_line=9,
        purpose="Select the proxy for a URL.",
    )
    ranked = search_units([unit], "select proxy", limit=1)
    assert ranked[0].evidence["body"] == 0.0
    assert ranked[0].score > 0.0
