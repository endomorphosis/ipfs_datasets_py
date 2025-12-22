# ipfs_datasets_py/mcp_server/tools/__init__.py
"""
MCP Tools for IPFS Datasets Python.

This module provides MCP tools that expose IPFS Datasets Python functionality to AI assistants.
"""

from __future__ import annotations

from importlib import import_module


def _safe_import(name: str):
    """Best-effort import for optional tool categories.

    Some tool categories depend on optional third-party dependencies (e.g. pydantic).
    Keep this package importable even when those deps are missing.
    """

    try:
        return import_module(name, package=__name__)
    except Exception:
        return None


# Import all tool categories for registration (best-effort)
audit_tools = _safe_import(".audit_tools")
dataset_tools = _safe_import(".dataset_tools")
development_tools = _safe_import(".development_tools")
graph_tools = _safe_import(".graph_tools")
ipfs_tools = _safe_import(".ipfs_tools")
monitoring_tools = _safe_import(".monitoring_tools")  # Added missing monitoring tools
pdf_tools = _safe_import(".pdf_tools")  # New PDF processing tools
provenance_tools = _safe_import(".provenance_tools")
security_tools = _safe_import(".security_tools")
vector_tools = _safe_import(".vector_tools")
web_archive_tools = _safe_import(".web_archive_tools")
cli = _safe_import(".cli")
functions = _safe_import(".functions")
lizardperson_argparse_programs = _safe_import(".lizardperson_argparse_programs")
lizardpersons_function_tools = _safe_import(".lizardpersons_function_tools")
media_tools = _safe_import(".media_tools")

# This __init__.py is intentionally left mostly empty.
# Tools are dynamically loaded by simple_server.py from their respective subdirectories.
# Avoid 'from .module import *' to prevent import issues and circular dependencies.

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
