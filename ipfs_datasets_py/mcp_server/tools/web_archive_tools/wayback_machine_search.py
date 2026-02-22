"""Wayback Machine search and retrieval for web content retrieval and analysis.

Business logic has been extracted to the canonical package module:
    ipfs_datasets_py/web_archiving/wayback_machine_engine.py

This file is now a thin re-export shim so existing imports continue to work.
"""
from ipfs_datasets_py.web_archiving.wayback_machine_engine import (  # noqa: F401
    search_wayback_machine,
    get_wayback_content,
    archive_to_wayback,
    _search_wayback_direct_api,
    _get_wayback_content_direct,
    _archive_to_wayback_direct,
)
