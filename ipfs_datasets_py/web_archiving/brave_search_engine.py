"""
Brave Search Engine.

Core BraveSearchAPI class extracted from brave_search.py to allow independent
use and testing of the search engine outside the MCP tool wrapper layer.

Standalone tool functions (search_brave, search_brave_news, etc.) live in
brave_search.py, which imports BraveSearchAPI from here.
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
import os

logger = logging.getLogger(__name__)

# Import the improved Brave Search client
try:
    from ipfs_datasets_py.processors.web_archiving.brave_search_client import (
        BraveSearchClient,
        brave_search_cache_stats,
        clear_brave_search_cache,
    )

    HAVE_BRAVE_CLIENT = True
except ImportError:
    HAVE_BRAVE_CLIENT = False
    BraveSearchClient = None  # type: ignore[assignment,misc]


class BraveSearchAPI:
    """Brave Search API class with install, config, and queue methods.

    This class provides a backward-compatible interface while using the
    improved BraveSearchClient under the hood when available.
    """

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Brave Search API.

        Args:
            api_key: Brave Search API key (can use BRAVE_API_KEY env var)
        """
        self.api_key = (
            api_key
            or os.environ.get("BRAVE_API_KEY")
            or os.environ.get("BRAVE_SEARCH_API_KEY")
        )
        self.queue: List[Dict[str, Any]] = []
        self.config: Dict[str, Any] = {
            "timeout": 30,
            "max_count": 20,
            "default_lang": "en",
            "default_country": "US",
        }

        # Use improved client if available
        if HAVE_BRAVE_CLIENT and self.api_key:
            self.client = BraveSearchClient(api_key=self.api_key)
        else:
            self.client = None

    def _install(self) -> Dict[str, Any]:
        """Install and verify Brave Search API dependencies.

        Returns:
            Dict containing installation status and instructions
        """
        try:
            import aiohttp  # noqa: F401

            aiohttp_installed = True
        except ImportError:
            aiohttp_installed = False

        try:
            import requests  # noqa: F401

            requests_installed = True
        except ImportError:
            requests_installed = False

        return {
            "status": (
                "success"
                if ((aiohttp_installed or requests_installed) and self.api_key)
                else "incomplete"
            ),
            "dependencies": {
                "aiohttp": {
                    "installed": aiohttp_installed,
                    "required": False,
                    "install_command": "pip install aiohttp",
                    "note": "Required for async functions",
                },
                "requests": {
                    "installed": requests_installed,
                    "required": True,
                    "install_command": "pip install requests",
                    "note": "Required for sync functions and caching",
                },
            },
            "environment_variables": {
                "BRAVE_API_KEY": {
                    "set": bool(self.api_key),
                    "required": True,
                    "description": "Brave Search API key (required)",
                }
            },
            "instructions": {
                "1": (
                    "Install requests: pip install requests"
                    if not requests_installed
                    else "✓ Dependencies installed"
                ),
                "2": (
                    "Set BRAVE_API_KEY or BRAVE_SEARCH_API_KEY environment variable"
                    if not self.api_key
                    else "✓ API key configured"
                ),
                "3": "Get API key from: https://brave.com/search/api/",
            },
            "ready": (aiohttp_installed or requests_installed) and bool(self.api_key),
            "caching_available": HAVE_BRAVE_CLIENT,
        }

    def _config(self, **kwargs) -> Dict[str, Any]:
        """Configure Brave Search API settings.

        Args:
            **kwargs: Configuration options (timeout, max_count, default_lang,
                      default_country, api_key)

        Returns:
            Dict containing current configuration
        """
        valid_config_keys = ["timeout", "max_count", "default_lang", "default_country"]

        for key, value in kwargs.items():
            if key in valid_config_keys:
                self.config[key] = value
            elif key == "api_key":
                self.api_key = value
                # Update client if using improved version
                if HAVE_BRAVE_CLIENT:
                    self.client = BraveSearchClient(api_key=self.api_key)

        return {
            "status": "success",
            "configuration": self.config,
            "api_key_set": bool(self.api_key),
            "valid_config_keys": valid_config_keys,
            "example": {
                "timeout": 30,
                "max_count": 20,
                "default_lang": "en",
                "default_country": "US",
            },
            "caching_available": HAVE_BRAVE_CLIENT,
        }

    def _queue(self, operation: str, **params) -> Dict[str, Any]:
        """Queue a search operation for batch processing.

        Args:
            operation: Operation type ('search', 'search_news', 'search_images')
            **params: Operation parameters

        Returns:
            Dict containing queue status
        """
        queue_item = {
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
        """Get current queue status."""
        return {
            "queue_length": len(self.queue),
            "queued_operations": self.queue,
            "operations_pending": len(
                [item for item in self.queue if item["status"] == "queued"]
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

    def cache_stats(self) -> Dict[str, Any]:
        """Get Brave Search cache statistics.

        Returns:
            Dict containing cache stats if caching is available
        """
        if HAVE_BRAVE_CLIENT:
            return brave_search_cache_stats()
        else:
            return {
                "status": "unavailable",
                "message": "Caching requires brave_search_client module",
            }

    def clear_cache(self) -> Dict[str, Any]:
        """Clear the Brave Search cache.

        Returns:
            Dict containing cache clearing result
        """
        if HAVE_BRAVE_CLIENT:
            return clear_brave_search_cache()
        else:
            return {
                "status": "unavailable",
                "message": "Caching requires brave_search_client module",
            }


__all__ = ["BraveSearchAPI", "HAVE_BRAVE_CLIENT"]
