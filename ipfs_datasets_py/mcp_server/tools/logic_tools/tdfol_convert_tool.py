"""
TDFOL format conversion tools for MCP / CLI.

Function
--------
tdfol_convert
    Convert a formula between logic representations
    (TDFOL ↔ DCEC, TDFOL → FOL, TDFOL → TPTP, TDFOL → SMT-LIB).
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


async def tdfol_convert(
    formula: str,
    source_format: str = "tdfol",
    target_format: str = "fol",
) -> Dict[str, Any]:
    """
    Convert a formula between logic representations.

    Args:
        formula: Formula string to convert.
        source_format: Source logic — tdfol | dcec | fol.
        target_format: Target logic — fol | tptp | smt2 | dcec | json.

    Returns:
        Dict with ``converted`` (str), ``source_format``, ``target_format``.
    """
    if not _AVAILABLE:
        return _unavailable("tdfol_convert")
    if not formula:
        return {"success": False, "error": "'formula' is required."}
    return await _PROCESSOR.convert_formula(
        formula=formula, source_format=source_format, target_format=target_format
    )


__all__ = ["tdfol_convert"]
