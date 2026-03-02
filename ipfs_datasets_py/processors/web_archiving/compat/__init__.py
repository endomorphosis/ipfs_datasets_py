"""Compatibility wrappers for legacy web archiving entrypoints."""

from .legacy_wrappers import (
    legacy_fetch_url,
    legacy_search_and_fetch,
    legacy_search_web,
)

__all__ = [
    "legacy_search_web",
    "legacy_fetch_url",
    "legacy_search_and_fetch",
]
