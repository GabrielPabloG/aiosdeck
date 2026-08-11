"""Shared storage error hierarchy.

Every domain store defines its own error type (backward-compatible public
API), but they all inherit from :class:`StoreError` so callers can catch a
single base type regardless of which store raised the exception.
"""


class StoreError(Exception):
    """Base class for all storage-layer errors."""
