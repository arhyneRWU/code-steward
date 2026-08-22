# code-steward: unit taxonomy.resolve
@staticmethod
def normalize(name: str) -> str:
    """Normalize a supplied name."""
    # code-steward: begin taxonomy.resolve.cleaning
    cleaned = name.strip()
    # code-steward: end taxonomy.resolve.cleaning
    return cleaned


# code-steward: begin taxonomy.checks


def validate_name(name: str) -> bool:
    return bool(name.strip())


# code-steward: end taxonomy.checks
