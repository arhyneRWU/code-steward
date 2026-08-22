from taxonomy import normalize_taxon_name


# code-steward: unit api.resolve-species
def resolve_api_species(label: str) -> str:
    """Resolve an API species label with shared taxonomy."""
    return normalize_taxon_name(label)


# code-steward: unit cli.resolve-species
def resolve_cli_species(label: str) -> str:
    """Resolve a command-line species label with shared taxonomy."""
    return normalize_taxon_name(label)
