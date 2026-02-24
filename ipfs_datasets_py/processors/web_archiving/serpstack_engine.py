"""SerpStack Search API engine — canonical business-logic location.

This module contains the ``SerpStackSearchAPI`` class (queue/config/install
management).  It was previously embedded inside the MCP tool wrapper at
``ipfs_datasets_py/mcp_server/tools/web_archive_tools/serpstack_search.py``.

Keeping it here means the same class can be used from:
- ``ipfs_datasets_py.web_archiving.serpstack_engine`` (package import)
- ``ipfs_datasets_py-cli search serpstack ...``          (CLI)
- The MCP server tool (thin wrapper in tools/web_archive_tools/)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SerpStackSearchAPI:
    """SerpStack Search API class with install, config, and queue methods."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: str = "http://api.serpstack.com",
    ) -> None:
        """Initialise SerpStack API.

        Args:
            api_key: SerpStack API key (required; falls back to SERPSTACK_API_KEY env var).
            api_url: Base API URL.
        """
        self.api_key = api_key or os.environ.get("SERPSTACK_API_KEY")
        self.api_url = api_url
        self.queue: List[Dict[str, Any]] = []
        self.config: Dict[str, Any] = {
            "api_url": api_url,
            "timeout": 30,
            "max_results": 100,
            "default_engine": "google",
        }

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def _install(self) -> Dict[str, Any]:
        """Verify SerpStack API dependencies and environment.

        Returns:
            Dict containing installation status and instructions.
        """
        try:
            import aiohttp  # noqa: F401
            aiohttp_installed = True
        except ImportError:
            aiohttp_installed = False

        return {
            "status": "success" if (aiohttp_installed and self.api_key) else "incomplete",
            "dependencies": {
                "aiohttp": {
                    "installed": aiohttp_installed,
                    "required": True,
                    "install_command": "pip install aiohttp",
                }
            },
            "environment_variables": {
                "SERPSTACK_API_KEY": {
                    "set": bool(self.api_key),
                    "required": True,
                    "description": "SerpStack API key (required for all searches)",
                }
            },
            "instructions": {
                "1": "Install aiohttp: pip install aiohttp"
                if not aiohttp_installed
                else "✓ Dependencies installed",
                "2": "Set SERPSTACK_API_KEY environment variable"
                if not self.api_key
                else "✓ API key configured",
                "3": "Get API key from: https://serpstack.com/signup/free",
            },
            "ready": aiohttp_installed and bool(self.api_key),
        }

    def _config(self, **kwargs: Any) -> Dict[str, Any]:
        """Configure SerpStack API settings.

        Args:
            **kwargs: One or more of ``api_url``, ``timeout``, ``max_results``,
                ``default_engine``, or ``api_key``.

        Returns:
            Dict containing current configuration.
        """
        valid_config_keys = ["api_url", "timeout", "max_results", "default_engine"]
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
            "supported_engines": ["google", "bing", "yandex", "yahoo", "baidu"],
            "example": {
                "api_url": "http://api.serpstack.com",
                "timeout": 30,
                "max_results": 100,
                "default_engine": "google",
            },
        }

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def _queue(self, operation: str, **params: Any) -> Dict[str, Any]:
        """Queue a search operation for batch processing.

        Args:
            operation: Operation type (``'search'``, ``'search_images'``, …).
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


__all__ = ["SerpStackSearchAPI"]


# ---------------------------------------------------------------------------
# Standalone async search functions — canonical business-logic location
# ---------------------------------------------------------------------------

import os as _os
from datetime import datetime as _datetime


async def search_serpstack(
    query: str,
    api_key: Optional[str] = None,
    engine: str = "google",
    num: int = 10,
    page: int = 1,
    location: Optional[str] = None,
    device: Optional[str] = None,
    lang: Optional[str] = None,
) -> Dict[str, Any]:
    """Search using SerpStack API.

    Args:
        query: Search query string.
        api_key: SerpStack API key (falls back to SERPSTACK_API_KEY env var).
        engine: Search engine to use (google, bing, yandex, yahoo, baidu).
        num: Number of results to return (1-100).
        page: Page number (>=1).
        location: Optional location string for localised results.
        device: Optional device type (desktop, mobile, tablet).
        lang: Optional language code (e.g. "en", "es").

    Returns:
        Dict with ``status``, ``results``, ``query``, ``total_results``, etc.
    """
    if not query or not isinstance(query, str):
        return {"status": "error", "error": "Query must be a non-empty string"}
    valid_engines = ["google", "bing", "yandex", "yahoo", "baidu"]
    if engine not in valid_engines:
        return {"status": "error", "error": f"Invalid engine: {engine}. Valid: {valid_engines}"}
    if not (1 <= num <= 100):
        return {"status": "error", "error": "num must be between 1 and 100"}
    if page < 1:
        return {"status": "error", "error": "page must be >= 1"}
    api_key = api_key or _os.environ.get("SERPSTACK_API_KEY")
    if not api_key:
        return {"status": "error", "error": "SerpStack API key required. Set SERPSTACK_API_KEY."}
    try:
        import aiohttp
    except ImportError:
        return {"status": "error", "error": "aiohttp required: pip install aiohttp"}
    url = "http://api.serpstack.com/search"
    params: Dict[str, Any] = {"access_key": api_key, "query": query, "engine": engine,
                               "num": min(num, 100), "page": page}
    if location:
        params["location"] = location
    if device:
        params["device"] = device
    if lang:
        params["lang"] = lang
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "error" in data:
                        return {"status": "error", "error": data["error"].get("info", "API error")}
                    results = [
                        {"title": r.get("title", ""), "url": r.get("url", ""),
                         "description": r.get("description", ""), "position": r.get("position", 0)}
                        for r in data.get("organic_results", [])
                    ]
                    info = data.get("search_information", {})
                    return {"status": "success", "results": results, "query": query, "engine": engine,
                            "total_results": info.get("total_results", "N/A"),
                            "time_taken": info.get("time_taken", 0), "page": page,
                            "search_timestamp": _datetime.now().isoformat()}
                elif resp.status == 401:
                    return {"status": "error", "error": "Invalid SerpStack API key"}
                elif resp.status == 429:
                    return {"status": "error", "error": "Rate limit exceeded"}
                else:
                    return {"status": "error", "error": f"HTTP {resp.status}"}
    except Exception as e:
        logger.error(f"SerpStack search failed: {e}")
        return {"status": "error", "error": str(e)}


async def search_serpstack_images(
    query: str,
    api_key: Optional[str] = None,
    engine: str = "google",
    num: int = 10,
    location: Optional[str] = None,
) -> Dict[str, Any]:
    """Search for images using SerpStack API."""
    if not query or not isinstance(query, str):
        return {"status": "error", "error": "Query must be a non-empty string"}
    api_key = api_key or _os.environ.get("SERPSTACK_API_KEY")
    if not api_key:
        return {"status": "error", "error": "SerpStack API key required. Set SERPSTACK_API_KEY."}
    try:
        import aiohttp
    except ImportError:
        return {"status": "error", "error": "aiohttp required: pip install aiohttp"}
    url = "http://api.serpstack.com/search"
    params: Dict[str, Any] = {"access_key": api_key, "query": query, "engine": engine,
                               "type": "images", "num": min(num, 100)}
    if location:
        params["location"] = location
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "error" in data:
                        return {"status": "error", "error": data["error"].get("info", "API error")}
                    results = [
                        {"title": r.get("title", ""), "url": r.get("url", ""),
                         "image_url": r.get("image_url", ""), "thumbnail": r.get("thumbnail", ""),
                         "source": r.get("source", ""), "width": r.get("width"), "height": r.get("height")}
                        for r in data.get("image_results", [])
                    ]
                    return {"status": "success", "results": results, "query": query,
                            "total_results": len(results), "search_timestamp": _datetime.now().isoformat()}
                else:
                    return {"status": "error", "error": f"HTTP {resp.status}"}
    except Exception as e:
        logger.error(f"SerpStack image search failed: {e}")
        return {"status": "error", "error": str(e)}


async def batch_search_serpstack(
    queries: List[str],
    api_key: Optional[str] = None,
    engine: str = "google",
    num: int = 10,
    delay_seconds: float = 1.0,
) -> Dict[str, Any]:
    """Batch search multiple queries using SerpStack API."""
    if not queries or not isinstance(queries, list):
        return {"status": "error", "error": "queries must be a non-empty list"}
    if not all(isinstance(q, str) for q in queries):
        return {"status": "error", "error": "All queries must be strings"}
    import anyio
    results: Dict[str, Any] = {}
    success_count = 0
    error_count = 0
    for q in queries:
        r = await search_serpstack(query=q, api_key=api_key, engine=engine, num=num)
        results[q] = r
        if r["status"] == "success":
            success_count += 1
        else:
            error_count += 1
        if q != queries[-1]:
            await anyio.sleep(delay_seconds)
    return {"status": "success", "results": results, "engine": engine,
            "total_queries": len(queries), "success_count": success_count,
            "error_count": error_count, "batch_completed_at": _datetime.now().isoformat()}


__all__ = [
    "SerpStackSearchAPI",
    "search_serpstack",
    "search_serpstack_images",
    "batch_search_serpstack",
]
