"""
Compatibility Layer for Dual-Runtime MCP Server

This module provides backward compatibility for existing MCP tools when
transitioning from FastAPI-only to dual-runtime (FastAPI + Trio) architecture.

Key Objectives:
- 100% backward compatibility with existing 370+ tools
- Zero breaking changes to API surface
- Graceful fallback when Trio unavailable
- Configuration migration support
- API versioning for future changes

Components:
- shim.py: Compatibility shim for existing tool wrappers
- detection.py: Runtime detection and tool routing utilities
- config_migration.py: Configuration migration helpers
- version.py: API versioning and deprecation management

Usage:
    from ipfs_datasets_py.mcp_server.compat import CompatibilityShim
    
    # Wrap existing tool to ensure compatibility
    shim = CompatibilityShim()
    wrapped_tool = shim.wrap_tool(my_existing_tool)
    
    # Tool will work with both FastAPI and Trio runtimes
    result = await wrapped_tool(params)
"""

__version__ = "1.0.0"
__all__ = [
    "CompatibilityShim",
    "RuntimeDetector",
    "ConfigMigrator",
    "APIVersionManager"
]

try:
    from .shim import CompatibilityShim
except ImportError:
    CompatibilityShim = None

try:
    from .detection import RuntimeDetector
except ImportError:
    RuntimeDetector = None

try:
    from .config_migration import ConfigMigrator
except ImportError:
    ConfigMigrator = None

try:
    from .version import APIVersionManager
except ImportError:
    APIVersionManager = None
