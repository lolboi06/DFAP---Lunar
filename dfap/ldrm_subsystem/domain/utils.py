"""
Utility functions for LDRM.
"""
from datetime import datetime, timezone

def utc_now() -> datetime:
    """Returns current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)
