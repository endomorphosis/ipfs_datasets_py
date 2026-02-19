"""
Logic module capabilities and health tools for MCP / CLI.

Replaces the former FastAPI ``/capabilities`` and ``/health`` REST endpoints.

Functions
---------
logic_capabilities
    List supported logics, rule counts, conversions, and NL languages.
logic_health
    Check availability of all logic sub-modules.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py.core_operations.logic_processor import LogicProcessor
    _PROCESSOR = LogicProcessor()
    _AVAILABLE = True
except Exception as _e:
    logger.warning("LogicProcessor not available: %s", _e)
    _PROCESSOR = None  # type: ignore[assignment]
    _AVAILABLE = False


def _unavailable(tool: str) -> Dict[str, Any]:
    return {"success": False, "error": f"{tool}: LogicProcessor not available."}


async def logic_capabilities() -> Dict[str, Any]:
    """
    Return capabilities of all logic sub-modules.

    Returns:
        Dict with ``logics`` (dict), ``conversions`` (list),
        ``nl_languages`` (list), ``elapsed_ms``.
    """
    if not _AVAILABLE:
        return _unavailable("logic_capabilities")
    return await _PROCESSOR.get_capabilities()


async def logic_health() -> Dict[str, Any]:
    """
    Check health and availability of all logic sub-modules.

    Returns:
        Dict with ``status`` (healthy | degraded | unavailable),
        ``modules`` (dict name→ok/unavailable), ``healthy``, ``total``.
    """
    if not _AVAILABLE:
        return _unavailable("logic_health")
    return await _PROCESSOR.check_health()


__all__ = ["logic_capabilities", "logic_health"]
