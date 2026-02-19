"""
TDFOL proof visualization tools for MCP / CLI.

Function
--------
tdfol_visualize
    Visualize a proof tree, countermodel, or formula dependency graph.
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


async def tdfol_visualize(
    proof_data: Optional[Dict[str, Any]] = None,
    output_format: str = "ascii",
    visualization_type: str = "proof_tree",
) -> Dict[str, Any]:
    """
    Visualize a TDFOL proof or formula structure.

    Args:
        proof_data: Proof data dict (from ``tdfol_prove``).
        output_format: Output format — ascii | html | svg | json.
        visualization_type: Visualization kind — proof_tree | countermodel | dependency.

    Returns:
        Dict with ``visualization`` (str), ``format``, ``type``.
    """
    if not _AVAILABLE:
        return _unavailable("tdfol_visualize")
    return await _PROCESSOR.visualize_proof(
        proof_data=proof_data,
        output_format=output_format,
        visualization_type=visualization_type,
    )


__all__ = ["tdfol_visualize"]
