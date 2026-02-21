"""
Logic Module REST API — DEPRECATED.

This module previously provided a FastAPI-based HTTP interface for the logic
module.  It has been superseded by native MCP tools in the MCP server at:

    ipfs_datasets_py/mcp_server/tools/logic_tools/

Migration guide
---------------
Instead of running this as an HTTP server, use the MCP tools directly:

+----------------------------+-------------------------------------+
| Former REST endpoint       | MCP tool equivalent                 |
+============================+=====================================+
| GET  /health               | ``logic_health``                    |
| GET  /capabilities         | ``logic_capabilities``              |
| POST /prove                | ``tdfol_prove``                     |
| POST /convert/fol          | ``tdfol_convert``                   |
| POST /convert/dcec         | ``tdfol_convert``                   |
| POST /parse                | ``tdfol_parse``                     |
+----------------------------+-------------------------------------+

Usage (MCP tools)::

    from ipfs_datasets_py.mcp_server.tools.logic_tools import (
        CEC_INFERENCE_TOOLS, LOGIC_CAPABILITIES_TOOLS, ALL_LOGIC_TOOLS,
    )

    # Programmatic (async)
    import anyio
    from ipfs_datasets_py.mcp_server.tools.logic_tools.logic_capabilities_tool import (
        LogicHealthTool, LogicCapabilitiesTool,
    )
    result = anyio.run(lambda: LogicHealthTool().execute({}))
    print(result["status"])   # "healthy" | "degraded" | "unavailable"
"""

from __future__ import annotations

import warnings
import logging

logger = logging.getLogger(__name__)

_DEPRECATION_MSG = (
    "logic.api_server is deprecated and will be removed in a future version. "
    "Use ipfs_datasets_py.mcp_server.tools.logic_tools instead. "
    "See ipfs_datasets_py/logic/api_server.py for the migration guide."
)


def create_app():
    """
    Create the FastAPI application (DEPRECATED).

    .. deprecated::
        Use the MCP tools in ``mcp_server/tools/logic_tools/`` instead.

    Raises:
        DeprecationWarning: Always.
        ImportError: If FastAPI is not installed.
    """
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)

    try:
        import fastapi  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "FastAPI is not installed. This endpoint is deprecated — "
            "use the MCP tools in mcp_server/tools/logic_tools/ instead."
        ) from exc

    from fastapi import FastAPI
    app = FastAPI(
        title="Logic Module API (DEPRECATED)",
        description="DEPRECATED: use MCP tools in mcp_server/tools/logic_tools/ instead.",
        version="2.0.0-deprecated",
    )

    @app.get("/health")
    async def health():
        """Deprecated health endpoint — use MCP tool 'logic_health'."""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.logic_capabilities_tool import (
            LogicHealthTool,
        )
        return await LogicHealthTool().execute({})

    @app.get("/capabilities")
    async def capabilities():
        """Deprecated capabilities endpoint — use MCP tool 'logic_capabilities'."""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.logic_capabilities_tool import (
            LogicCapabilitiesTool,
        )
        return await LogicCapabilitiesTool().execute({})

    return app


def main() -> None:
    """Start the server (DEPRECATED — use MCP tools instead)."""
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    print("WARNING: logic.api_server is deprecated.")
    print("Use the MCP tools in mcp_server/tools/logic_tools/ instead.")
    print("See ipfs_datasets_py/logic/api_server.py for the migration guide.")


# Module-level app is no longer created eagerly.
app = None  # type: ignore[assignment]

if __name__ == "__main__":
    main()
