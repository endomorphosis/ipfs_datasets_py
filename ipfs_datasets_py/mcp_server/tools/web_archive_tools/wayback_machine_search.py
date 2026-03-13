"""Wayback Machine search and retrieval for web content retrieval and analysis.

Business logic has been extracted to the canonical package module:
    ipfs_datasets_py/web_archiving/wayback_machine_engine.py

This file is now a thin re-export shim so existing imports continue to work.
"""
from typing import Any, Dict

try:
    from ipfs_datasets_py.web_archiving.wayback_machine_engine import (  # noqa: F401
        search_wayback_machine,
        get_wayback_content,
        archive_to_wayback,
        _search_wayback_direct_api,
        _get_wayback_content_direct,
        _archive_to_wayback_direct,
    )
except (ImportError, ModuleNotFoundError):
    async def search_wayback_machine(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"error": "Wayback engine unavailable", "results": []}

    async def get_wayback_content(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"error": "Wayback engine unavailable", "content": None}

    async def archive_to_wayback(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"error": "Wayback engine unavailable", "archived": False}

    async def _search_wayback_direct_api(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"error": "Wayback engine unavailable", "results": []}

    async def _get_wayback_content_direct(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"error": "Wayback engine unavailable", "content": None}

    async def _archive_to_wayback_direct(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"error": "Wayback engine unavailable", "archived": False}
