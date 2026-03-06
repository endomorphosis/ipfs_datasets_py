"""Compatibility shim for legacy top-level ``google_search`` imports."""

from ipfs_datasets_py.processors.web_archiving.google_search_engine import (
    batch_search_google,
    search_google,
    search_google_images,
)

__all__ = [
    "search_google",
    "search_google_images",
    "batch_search_google",
]
