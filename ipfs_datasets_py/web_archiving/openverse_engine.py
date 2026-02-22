"""OpenVerse Search API engine — canonical business-logic location.

This module contains the ``OpenVerseSearchAPI`` class (queue/config/install
management for the Creative Commons media search service).  It was previously
embedded inside the MCP tool wrapper at
``ipfs_datasets_py/mcp_server/tools/web_archive_tools/openverse_search.py``.

Keeping it here means the same class can be used from:
- ``ipfs_datasets_py.web_archiving.openverse_engine`` (package import)
- ``ipfs_datasets_py-cli search openverse ...``          (CLI)
- The MCP server tool (thin wrapper in tools/web_archive_tools/)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class OpenVerseSearchAPI:
    """OpenVerse Search API class with install, config, and queue methods."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: str = "https://api.openverse.org/v1",
    ) -> None:
        """Initialise OpenVerse API.

        Args:
            api_key: OpenVerse API key (optional; falls back to OPENVERSE_API_KEY env var).
            api_url: Base API URL.
        """
        self.api_key = api_key or os.environ.get("OPENVERSE_API_KEY")
        self.api_url = api_url
        self.queue: List[Dict[str, Any]] = []
        self.config: Dict[str, Any] = {
            "api_url": api_url,
            "timeout": 30,
            "max_results": 100,
            "default_license_type": "all",
        }

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def _install(self) -> Dict[str, Any]:
        """Verify OpenVerse API dependencies and environment.

        Returns:
            Dict containing installation status and instructions.
        """
        try:
            import aiohttp  # noqa: F401
            aiohttp_installed = True
        except ImportError:
            aiohttp_installed = False

        return {
            "status": "success" if aiohttp_installed else "incomplete",
            "dependencies": {
                "aiohttp": {
                    "installed": aiohttp_installed,
                    "required": True,
                    "install_command": "pip install aiohttp",
                }
            },
            "environment_variables": {
                "OPENVERSE_API_KEY": {
                    "set": bool(self.api_key),
                    "required": False,
                    "description": "OpenVerse API key (optional, increases rate limits)",
                }
            },
            "instructions": {
                "1": "Install aiohttp: pip install aiohttp"
                if not aiohttp_installed
                else "✓ Dependencies installed",
                "2": "Set OPENVERSE_API_KEY environment variable (optional)"
                if not self.api_key
                else "✓ API key configured",
                "3": "Get API key from: https://wordpress.org/openverse/register/",
            },
        }

    def _config(self, **kwargs: Any) -> Dict[str, Any]:
        """Configure OpenVerse API settings.

        Args:
            **kwargs: One or more of ``api_url``, ``timeout``, ``max_results``,
                ``default_license_type``, or ``api_key``.

        Returns:
            Dict containing current configuration.
        """
        valid_config_keys = ["api_url", "timeout", "max_results", "default_license_type"]
        for key, value in kwargs.items():
            if key in valid_config_keys:
                self.config[key] = value
            elif key == "api_key":
                self.api_key = value

        return {
            "status": "success",
            "configuration": self.config,
            "api_key_set": bool(self.api_key),
            "valid_config_keys": valid_config_keys,
            "example": {
                "api_url": "https://api.openverse.org/v1",
                "timeout": 30,
                "max_results": 100,
                "default_license_type": "all",
            },
        }

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def _queue(self, operation: str, **params: Any) -> Dict[str, Any]:
        """Queue a search operation for batch processing.

        Args:
            operation: Operation type (``'search_images'``, ``'search_audio'``, …).
            **params: Operation parameters forwarded verbatim.

        Returns:
            Dict containing queue status.
        """
        queue_item: Dict[str, Any] = {
            "id": len(self.queue) + 1,
            "operation": operation,
            "params": params,
            "queued_at": datetime.now().isoformat(),
            "status": "queued",
        }
        self.queue.append(queue_item)
        return {
            "status": "success",
            "queue_item": queue_item,
            "queue_length": len(self.queue),
            "message": f"Operation '{operation}' queued successfully",
        }

    def get_queue_status(self) -> Dict[str, Any]:
        """Return current queue status."""
        return {
            "queue_length": len(self.queue),
            "queued_operations": self.queue,
            "operations_pending": sum(
                1 for item in self.queue if item["status"] == "queued"
            ),
        }

    def clear_queue(self) -> Dict[str, Any]:
        """Clear all queued operations."""
        cleared_count = len(self.queue)
        self.queue = []
        return {
            "status": "success",
            "cleared_count": cleared_count,
            "message": f"Cleared {cleared_count} queued operations",
        }


__all__ = ["OpenVerseSearchAPI"]


# ---------------------------------------------------------------------------
# Standalone async search functions — canonical business-logic location
# ---------------------------------------------------------------------------

import os as _os
from datetime import datetime as _datetime


async def search_openverse_images(
    query: str,
    api_key: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    license_type: Optional[str] = None,
    source: Optional[str] = None,
    creator: Optional[str] = None,
) -> Dict[str, Any]:
    """Search OpenVerse for Creative Commons images."""
    if not query or not isinstance(query, str):
        return {"status": "error", "error": "Query must be a non-empty string"}
    if page < 1 or not (1 <= page_size <= 100):
        return {"status": "error", "error": "page must be >=1; page_size must be 1-100"}
    api_key = api_key or _os.environ.get("OPENVERSE_API_KEY")
    try:
        import aiohttp
    except ImportError:
        return {"status": "error", "error": "aiohttp required: pip install aiohttp"}
    url = "https://api.openverse.org/v1/images/"
    params: Dict[str, Any] = {"q": query, "page": page, "page_size": min(page_size, 100)}
    if license_type:
        params["license_type"] = license_type
    if source:
        params["source"] = source
    if creator:
        params["creator"] = creator
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = [
                        {"id": r.get("id", ""), "title": r.get("title", ""),
                         "url": r.get("url", ""), "thumbnail": r.get("thumbnail", ""),
                         "creator": r.get("creator", ""), "license": r.get("license", ""),
                         "source": r.get("source", "")}
                        for r in data.get("results", [])
                    ]
                    return {"status": "success", "results": results, "query": query,
                            "result_count": data.get("count", len(results)),
                            "page_count": data.get("page_count", 1),
                            "search_timestamp": _datetime.now().isoformat()}
                elif resp.status == 401:
                    return {"status": "error", "error": "Invalid OpenVerse API key"}
                elif resp.status == 429:
                    return {"status": "error", "error": "Rate limit exceeded"}
                else:
                    return {"status": "error", "error": f"HTTP {resp.status}"}
    except Exception as e:
        logger.error(f"OpenVerse image search failed: {e}")
        return {"status": "error", "error": str(e)}


async def search_openverse_audio(
    query: str,
    api_key: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    license_type: Optional[str] = None,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """Search OpenVerse for Creative Commons audio."""
    if not query or not isinstance(query, str):
        return {"status": "error", "error": "Query must be a non-empty string"}
    if page < 1 or not (1 <= page_size <= 100):
        return {"status": "error", "error": "page must be >=1; page_size must be 1-100"}
    api_key = api_key or _os.environ.get("OPENVERSE_API_KEY")
    try:
        import aiohttp
    except ImportError:
        return {"status": "error", "error": "aiohttp required: pip install aiohttp"}
    url = "https://api.openverse.org/v1/audio/"
    params: Dict[str, Any] = {"q": query, "page": page, "page_size": min(page_size, 100)}
    if license_type:
        params["license_type"] = license_type
    if source:
        params["source"] = source
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = [
                        {"id": r.get("id", ""), "title": r.get("title", ""),
                         "url": r.get("url", ""), "creator": r.get("creator", ""),
                         "license": r.get("license", ""), "source": r.get("source", ""),
                         "duration": r.get("duration")}
                        for r in data.get("results", [])
                    ]
                    return {"status": "success", "results": results, "query": query,
                            "result_count": data.get("count", len(results)),
                            "page_count": data.get("page_count", 1),
                            "search_timestamp": _datetime.now().isoformat()}
                elif resp.status == 401:
                    return {"status": "error", "error": "Invalid OpenVerse API key"}
                else:
                    return {"status": "error", "error": f"HTTP {resp.status}"}
    except Exception as e:
        logger.error(f"OpenVerse audio search failed: {e}")
        return {"status": "error", "error": str(e)}


async def batch_search_openverse(
    queries: List[str],
    search_type: str = "images",
    api_key: Optional[str] = None,
    page_size: int = 20,
    delay_seconds: float = 0.5,
) -> Dict[str, Any]:
    """Batch search OpenVerse with multiple queries."""
    if not queries or not isinstance(queries, list):
        return {"status": "error", "error": "queries must be a non-empty list"}
    if not all(isinstance(q, str) for q in queries):
        return {"status": "error", "error": "All queries must be strings"}
    import anyio
    search_func = search_openverse_images if search_type == "images" else search_openverse_audio
    results: Dict[str, Any] = {}
    success_count = 0
    error_count = 0
    for q in queries:
        r = await search_func(query=q, api_key=api_key, page_size=page_size)
        results[q] = r
        if r["status"] == "success":
            success_count += 1
        else:
            error_count += 1
        if q != queries[-1]:
            await anyio.sleep(delay_seconds)
    return {"status": "success", "results": results, "search_type": search_type,
            "total_queries": len(queries), "success_count": success_count,
            "error_count": error_count, "batch_completed_at": _datetime.now().isoformat()}


__all__ = [
    "OpenVerseSearchAPI",
    "search_openverse_images",
    "search_openverse_audio",
    "batch_search_openverse",
]
