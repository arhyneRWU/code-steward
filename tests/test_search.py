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
