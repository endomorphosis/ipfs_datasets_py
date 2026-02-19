"""
TDFOL knowledge base management tools for MCP / CLI.

Functions
---------
tdfol_kb_add_axiom
    Add an axiom to the TDFOL knowledge base.
tdfol_kb_add_theorem
    Add a theorem (with proof) to the knowledge base.
tdfol_kb_query
    Query the knowledge base for statistics and contents.
tdfol_kb_export
    Export the knowledge base to JSON or other formats.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

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


async def tdfol_kb_add_axiom(formula: str) -> Dict[str, Any]:
    """
    Add an axiom to the TDFOL knowledge base.

    Args:
        formula: Axiom formula in TDFOL notation.

    Returns:
        Dict with ``success`` (bool) and ``formula``.
    """
    if not _AVAILABLE:
        return _unavailable("tdfol_kb_add_axiom")
    if not formula:
        return {"success": False, "error": "'formula' is required."}
    return await _PROCESSOR.manage_kb(operation="add_axiom", formula=formula)


async def tdfol_kb_add_theorem(formula: str) -> Dict[str, Any]:
    """
    Add a theorem to the TDFOL knowledge base.

    Args:
        formula: Theorem formula in TDFOL notation.

    Returns:
        Dict with ``success`` (bool) and ``formula``.
    """
    if not _AVAILABLE:
        return _unavailable("tdfol_kb_add_theorem")
    if not formula:
        return {"success": False, "error": "'formula' is required."}
    return await _PROCESSOR.manage_kb(operation="add_theorem", formula=formula)


async def tdfol_kb_query() -> Dict[str, Any]:
    """
    Query the TDFOL knowledge base for statistics and contents.

    Returns:
        Dict with ``stats`` (dict).
    """
    if not _AVAILABLE:
        return _unavailable("tdfol_kb_query")
    return await _PROCESSOR.manage_kb(operation="query")


async def tdfol_kb_export(export_format: str = "json") -> Dict[str, Any]:
    """
    Export the TDFOL knowledge base.

    Args:
        export_format: Output format — json | tptp | smt2.

    Returns:
        Dict with ``data`` and ``format``.
    """
    if not _AVAILABLE:
        return _unavailable("tdfol_kb_export")
    return await _PROCESSOR.manage_kb(operation="export", export_format=export_format)


__all__ = [
    "tdfol_kb_add_axiom",
    "tdfol_kb_add_theorem",
    "tdfol_kb_query",
    "tdfol_kb_export",
]
