"""SerpStack search tools — thin MCP re-export shim.

All business logic lives in ipfs_datasets_py.web_archiving.serpstack_engine.
"""
from __future__ import annotations

from ipfs_datasets_py.web_archiving.serpstack_engine import (  # noqa: F401
    SerpStackSearchAPI,
    search_serpstack,
    search_serpstack_images,
    batch_search_serpstack,
)

__all__ = ["SerpStackSearchAPI", "search_serpstack", "search_serpstack_images", "batch_search_serpstack"]
