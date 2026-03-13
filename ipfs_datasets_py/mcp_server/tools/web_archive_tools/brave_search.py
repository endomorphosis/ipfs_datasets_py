"""Brave Search API integration for web search and data discovery.

Business logic has been extracted to the canonical package module:
    ipfs_datasets_py/web_archiving/brave_search_engine.py

This file is now a thin re-export shim so existing imports continue to work.
"""
from typing import Any, Dict

try:
    from ipfs_datasets_py.web_archiving.brave_search_engine import (  # noqa: F401
        BraveSearchAPI,
        HAVE_BRAVE_CLIENT,
        search_brave,
        search_brave_news,
        search_brave_images,
        batch_search_brave,
        get_brave_cache_stats,
        clear_brave_cache,
    )
except (ImportError, ModuleNotFoundError):
    HAVE_BRAVE_CLIENT = False

    class BraveSearchAPI:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    async def search_brave(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"error": "Brave search engine unavailable", "results": []}

    async def search_brave_news(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"error": "Brave search engine unavailable", "results": []}

    async def search_brave_images(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"error": "Brave search engine unavailable", "results": []}

    async def batch_search_brave(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"error": "Brave search engine unavailable", "results": []}

    async def get_brave_cache_stats(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"error": "Brave search engine unavailable", "stats": {}}

    async def clear_brave_cache(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"error": "Brave search engine unavailable", "cleared": False}
