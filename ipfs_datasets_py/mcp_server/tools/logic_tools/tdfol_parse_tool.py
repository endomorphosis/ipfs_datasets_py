"""
TDFOL parsing tools for MCP / CLI.

Function
--------
tdfol_parse
    Parse a formula or natural language text into TDFOL notation.
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


async def tdfol_parse(
    text: str,
    format: str = "symbolic",
    language: str = "en",
) -> Dict[str, Any]:
    """
    Parse text into a TDFOL formula.

    Args:
        text: Input to parse.
        format: Input format — symbolic | json | natural_language.
        language: Natural language code (en | es | fr | de); ignored for symbolic.

    Returns:
        Dict with ``formula`` (str), ``format``, ``elapsed_ms``.
    """
    if not _AVAILABLE:
        return _unavailable("tdfol_parse")
    if not text:
        return {"success": False, "error": "'text' is required."}
    return await _PROCESSOR.parse_tdfol(text=text, format=format, language=language)


__all__ = ["tdfol_parse"]
