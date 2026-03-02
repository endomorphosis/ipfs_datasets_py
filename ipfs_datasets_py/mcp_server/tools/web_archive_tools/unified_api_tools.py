"""Unified web archiving MCP tools.

These tools expose a single API surface for search and scraping with
throughput-aware provider orchestration and fallback behavior.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional


def _get_api():
    from ipfs_datasets_py.processors.web_archiving.unified_api import UnifiedWebArchivingAPI

    return UnifiedWebArchivingAPI()


async def unified_search(
    query: str,
    max_results: int = 20,
    mode: str = "max_throughput",
    provider_allowlist: Optional[List[str]] = None,
    provider_denylist: Optional[List[str]] = None,
    offset: int = 0,
) -> Dict[str, Any]:
    """Run unified search across configured providers.

    Args:
        query: Query string to search.
        max_results: Maximum number of results.
        mode: Orchestration mode (max_throughput, balanced, max_quality, low_cost).
        provider_allowlist: Optional provider inclusion list.
        provider_denylist: Optional provider exclusion list.
        offset: Result offset.
    """
    try:
        from ipfs_datasets_py.processors.web_archiving.contracts import OperationMode, UnifiedSearchRequest

        api = _get_api()
        request = UnifiedSearchRequest(
            query=query,
            max_results=max_results,
            mode=OperationMode(mode),
            provider_allowlist=provider_allowlist,
            provider_denylist=provider_denylist,
            offset=offset,
        )
        response = await asyncio.to_thread(api.search, request)
        return {
            "status": "success" if response.success else "error",
            "data": response.to_dict(),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def unified_fetch(
    url: str,
    mode: str = "balanced",
) -> Dict[str, Any]:
    """Fetch content for a URL using unified scraper fallback."""
    try:
        from ipfs_datasets_py.processors.web_archiving.contracts import OperationMode, UnifiedFetchRequest

        api = _get_api()
        request = UnifiedFetchRequest(url=url, mode=OperationMode(mode))
        response = await asyncio.to_thread(api.fetch, request)
        return {
            "status": "success" if response.success else "error",
            "data": response.to_dict(),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def unified_search_and_fetch(
    query: str,
    max_results: int = 20,
    max_documents: int = 5,
    mode: str = "max_throughput",
    provider_allowlist: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run unified search then fetch top document URLs."""
    try:
        from ipfs_datasets_py.processors.web_archiving.contracts import OperationMode, UnifiedSearchRequest

        api = _get_api()
        request = UnifiedSearchRequest(
            query=query,
            max_results=max_results,
            mode=OperationMode(mode),
            provider_allowlist=provider_allowlist,
        )
        result = await asyncio.to_thread(api.search_and_fetch, request, max_documents=max_documents)
        return result
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def unified_health() -> Dict[str, Any]:
    """Return unified API health status and metrics snapshot."""
    try:
        api = _get_api()
        result = await asyncio.to_thread(api.health)
        return {"status": "success", "data": result}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


__all__ = [
    "unified_search",
    "unified_fetch",
    "unified_search_and_fetch",
    "unified_health",
]
