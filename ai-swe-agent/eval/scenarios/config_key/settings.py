from config import DEFAULTS


def get_timeout(overrides: dict = None) -> int:
    """Return the configured timeout, applying any overrides."""
    cfg = {**DEFAULTS, **(overrides or {})}
    return cfg["timeout"]  # BUG: the actual key is 'timeout_seconds', defined in config.py
