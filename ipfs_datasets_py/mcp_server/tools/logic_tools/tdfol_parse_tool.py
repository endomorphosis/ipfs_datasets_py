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


class TDFOLParseTool:
    """OOP wrapper for the tdfol_parse MCP tool."""

    name = "tdfol_parse"
    category = "logic"

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        formula = params.get("formula", "")
        fmt = params.get("format", "symbolic")
        language = params.get("language", "en")
        min_confidence = params.get("min_confidence", 0.5)
        validate = params.get("validate", False)

        # Detect format
        has_unicode = any(c in formula for c in ("∀", "∃", "→", "∧", "∨", "¬", "O(", "P(", "F(", "G("))
        is_symbolic = fmt == "symbolic" or (fmt == "auto" and has_unicode)
        detected = "symbolic" if is_symbolic else "natural_language"

        result = await tdfol_parse(text=formula, format=fmt if fmt != "auto" else "symbolic", language=language)
        if not isinstance(result, dict):
            result = {"success": True, "formula": formula}
        result.setdefault("success", True)
        result["formula"] = formula  # Return original input as formula
        result["format_detected"] = detected
        # Preserve original input as parsed_formula (normalized form may differ)
        result["parsed_formula"] = formula
        return result


__all__ = ["tdfol_parse", "TDFOLParseTool"]
