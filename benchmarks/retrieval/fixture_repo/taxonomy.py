ALIASES = {
    "blue tang": "Paracanthurus hepatus",
    "regal tang": "Paracanthurus hepatus",
}


# code-steward: unit taxonomy.normalize
def normalize_taxon_name(name: str) -> str:
    """Resolve a supplied species name to its canonical taxon name."""
    cleaned = " ".join(name.split())
    return ALIASES.get(cleaned.lower(), cleaned)


# code-steward: unit taxonomy.lookup-label
def taxon_from_supplier_label(label: str) -> str:
    cleaned = label.strip().replace("_", " ")
    return ALIASES.get(cleaned.lower(), cleaned)


# code-steward: unit billing.normalize-price
def normalize_price(value: str) -> str:
    """Normalize a currency value for invoice display."""
    return value.replace("$", "").replace(",", "").strip()
