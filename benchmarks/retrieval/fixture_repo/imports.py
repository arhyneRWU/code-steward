from taxonomy import normalize_taxon_name


# code-steward: unit imports.resolve-species
def resolve_supplier_species(label: str) -> str:
    """Resolve a supplier label with shared taxonomy normalization."""
    return normalize_taxon_name(label)


# code-steward: unit legacy.canonicalize-species
def canonicalize_legacy_species(name: str) -> str:
    """Canonicalize species text stored by a legacy importer."""
    return " ".join(part.capitalize() for part in name.split())
