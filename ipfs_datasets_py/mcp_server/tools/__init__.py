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
    "audit_tools",
    "dataset_tools",
    "development_tools",
    "graph_tools",
    "ipfs_tools",
    "monitoring_tools",
    "pdf_tools",
    "provenance_tools",
    "security_tools",
    "vector_tools",
    "web_archive_tools",
    "cli",
    "functions",
    "lizardperson_argparse_programs",
    "lizardpersons_function_tools",
    "media_tools",
}

__all__ = [
    "audit_tools",
    "dataset_tools", 
    "development_tools",
    "graph_tools",
    "ipfs_tools",
    "monitoring_tools",  # Added missing monitoring tools
    "pdf_tools",  # New PDF processing tools
    "provenance_tools",
    "security_tools",
    "vector_tools",
    "web_archive_tools",
    "cli",
    "functions",
    "lizardperson_argparse_programs",
    "lizardpersons_function_tools",
    "media_tools"
]


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
