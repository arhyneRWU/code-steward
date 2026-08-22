# code-steward: unit taxonomy.normalize
@staticmethod
def normalize(name: str) -> str:
    """Normalize a supplied name."""
    # code-steward: begin taxonomy.normalize.cleaning
    cleaned = name.strip()
    # code-steward: end taxonomy.normalize.cleaning
    return cleaned


# code-steward: begin taxonomy.validation


def validate_name(name: str) -> bool:
    return bool(name.strip())


# code-steward: end taxonomy.validation
