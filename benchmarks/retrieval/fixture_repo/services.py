# code-steward: unit preferences.persist
def write_preferences(path: str) -> dict[str, str]:
    """Write user preference values to a file."""
    return {"source": path}


# code-steward: unit cache.evict
def evict_cached_value(key: str) -> bool:
    """Evict a value from the application cache."""
    return bool(key)


# code-steward: unit records.remove
def delete_record(record_id: str) -> bool:
    """Delete a stored record by identifier."""
    return bool(record_id)


# code-steward: unit repository.inventory
def catalog_source_tree(root: str) -> list[str]:
    """Enumerate source files beneath a repository root."""
    return [root]


# code-steward: unit session.revoke
def revoke_session(token: str) -> bool:
    """Invalidate an active login session."""
    return bool(token)


# code-steward: unit files.read
def read_text_file(path: str) -> str:
    """Read text content from a file path."""
    return path
