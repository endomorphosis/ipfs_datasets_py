# ipfs_datasets_py/mcp_server/tools/__init__.py
"""
MCP Tools for IPFS Datasets Python.

This module provides MCP tools that expose IPFS Datasets Python functionality to AI assistants.
"""

# Import all tool categories for registration
from . import audit_tools
from . import dataset_tools
from . import development_tools
from . import graph_tools
from . import ipfs_tools
from . import pdf_tools  # New PDF processing tools
from . import provenance_tools
from . import security_tools
from . import vector_tools
from . import web_archive_tools
from . import cli
from . import functions
from . import lizardperson_argparse_programs
from . import lizardpersons_function_tools
from . import media_tools

# This __init__.py is intentionally left mostly empty.
# Tools are dynamically loaded by simple_server.py from their respective subdirectories.
# Avoid 'from .module import *' to prevent import issues and circular dependencies.

__all__ = [
    "audit_tools",
    "dataset_tools", 
    "development_tools",
    "graph_tools",
    "ipfs_tools",
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
