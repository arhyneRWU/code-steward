# code-steward: unit config.load
def load_configuration(path: str) -> dict[str, str]:
    """Load application configuration values from a file path."""
    return {"source": path}


# code-steward: unit records.fetch
def get_record(record_id: str) -> dict[str, str]:
    """Fetch a stored record by identifier."""
    return {"id": record_id}


# code-steward: unit auth.verify
def authenticate_token(token: str) -> bool:
    """Verify that an authentication token is present."""
    return bool(token)
