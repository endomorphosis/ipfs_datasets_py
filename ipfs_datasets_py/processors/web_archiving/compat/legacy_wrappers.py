"""Legacy compatibility wrappers for unified web archiving APIs.

These wrappers preserve old call styles while routing behavior to
`UnifiedWebArchivingAPI`.
"""

from __future__ import annotations

import warnings
from typing import Any, Dict, List, Optional

from ..contracts import OperationMode, UnifiedFetchRequest, UnifiedSearchRequest


def _get_api():
    from ..unified_api import UnifiedWebArchivingAPI

    return UnifiedWebArchivingAPI()


def _warn(name: str, replacement: str) -> None:
    warnings.warn(
        f"{name} is deprecated; use {replacement} via UnifiedWebArchivingAPI.",
        DeprecationWarning,
        stacklevel=2,
    )


def legacy_search_web(
    query: str,
    max_results: int = 20,
    mode: str = "balanced",
    provider_allowlist: Optional[List[str]] = None,
    provider_denylist: Optional[List[str]] = None,
    offset: int = 0,
) -> Dict[str, Any]:
    """Legacy wrapper for search-style entrypoints."""
    _warn("legacy_search_web", "UnifiedWebArchivingAPI.search")
    api = _get_api()
    request = UnifiedSearchRequest(
        query=query,
        max_results=max_results,
        mode=OperationMode(mode),
        provider_allowlist=provider_allowlist,
        provider_denylist=provider_denylist,
        offset=offset,
    )
    result = api.search(request)
    return {
        "status": "success" if result.success else "error",
        "data": result.to_dict(),
    }


def legacy_fetch_url(
    url: str,
    mode: str = "balanced",
) -> Dict[str, Any]:
    """Legacy wrapper for URL fetch/scrape entrypoints."""
    _warn("legacy_fetch_url", "UnifiedWebArchivingAPI.fetch")
    api = _get_api()
    request = UnifiedFetchRequest(url=url, mode=OperationMode(mode))
    result = api.fetch(request)
    return {
        "status": "success" if result.success else "error",
        "data": result.to_dict(),
    }


def legacy_search_and_fetch(
    query: str,
    max_results: int = 20,
    max_documents: int = 5,
    mode: str = "max_throughput",
    provider_allowlist: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Legacy wrapper for search+fetch pipeline entrypoints."""
    _warn("legacy_search_and_fetch", "UnifiedWebArchivingAPI.search_and_fetch")
    api = _get_api()
    request = UnifiedSearchRequest(
        query=query,
        max_results=max_results,
        mode=OperationMode(mode),
        provider_allowlist=provider_allowlist,
    )
    return api.search_and_fetch(request, max_documents=max_documents)


__all__ = [
    "legacy_search_web",
    "legacy_fetch_url",
    "legacy_search_and_fetch",
]
