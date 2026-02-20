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
