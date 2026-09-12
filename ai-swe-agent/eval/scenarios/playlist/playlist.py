def get_last_n(items: list, n: int) -> list:
    """Return the last n items from the list, in original order."""
    return items[:n]  # BUG: this returns the FIRST n items, not the last n
