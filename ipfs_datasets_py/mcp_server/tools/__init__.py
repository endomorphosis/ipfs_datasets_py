# ipfs_datasets_py/mcp_server/tools/__init__.py
"""
MCP Tools for IPFS Datasets Python.

This module provides MCP tools that expose IPFS Datasets Python functionality to AI assistants.
"""
from __future__ import annotations

import importlib
from types import ModuleType
from typing import Final

# NOTE:
# Do not eagerly import tool subpackages here.
# Many tool categories have optional dependencies (HF datasets, torch, etc.).
# Eager imports cause unrelated tests to fail at import time.

_TOOL_SUBMODULES: Final[set[str]] = {
    # Core
    "dataset_tools",
    "ipfs_tools",
    "graph_tools",
    "embedding_tools",
    "logic_tools",
    "media_tools",
    "pdf_tools",
    "web_archive_tools",
    "development_tools",
    # Infrastructure
    "audit_tools",
    "auth_tools",
    "background_task_tools",
    "cache_tools",
    "monitoring_tools",
    "provenance_tools",
    "rate_limiting_tools",
    "search_tools",
    "security_tools",
    "session_tools",
    "storage_tools",
    "vector_store_tools",
    "vector_tools",
    "workflow_tools",
    # Specialised
    "admin_tools",
    "alert_tools",
    "analysis_tools",
    "cli",
    "dashboard_tools",
    "data_processing_tools",
    "discord_tools",
    "email_tools",
    "file_converter_tools",
    "file_detection_tools",
    "functions",
    "geospatial_tools",
    "index_management_tools",
    "investigation_tools",
    "ipfs_cluster_tools",
    "mcplusplus",
    "medical_research_scrapers",
    "p2p_tools",
    "p2p_workflow_tools",
    "sparse_embedding_tools",
    "web_scraping_tools",
    # Legacy / special
    "bespoke_tools",
    "finance_data_tools",
    "legacy_mcp_tools",
    "legal_dataset_tools",
    "lizardperson_argparse_programs",
    "lizardpersons_function_tools",
    "software_engineering_tools",
}

__all__ = sorted(_TOOL_SUBMODULES)


def __getattr__(name: str) -> ModuleType:
    """Lazy-load tool subpackages.

    This keeps package import cheap and avoids hard failures when optional
    dependencies for some tool categories are not installed.
    """

    if name in _TOOL_SUBMODULES:
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | _TOOL_SUBMODULES)
