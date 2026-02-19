"""
CEC Parse Tool — Parse natural language to DCEC formulas via MCP.

Exposes two MCP tools:

    - ``cec_parse``            — Parse natural language text into a DCEC formula string.
    - ``cec_validate_formula`` — Validate a DCEC formula for syntactic correctness.

These replace the former ``parse_dcec``, ``translate_dcec``, and
``validate_formula`` plain-function helpers (originally registered through the
legacy ``TOOLS`` dict) with proper ``ClaudeMCPTool`` subclasses that integrate
directly with the ToolRegistry.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool

logger = logging.getLogger(__name__)

TOOL_VERSION = "1.0.0"

# Supported natural-language input languages (ISO 639-1 codes)
_SUPPORTED_LANGUAGES = ["en", "es", "fr", "de", "auto"]

# Supported target formats for formula translation
_SUPPORTED_FORMATS = ["tptp", "json", "dcec"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nl_to_dcec(text: str, language: str) -> Dict[str, Any]:
    """
    Attempt to convert *text* to a DCEC formula string.

    Tries the CEC NL module first, falls back to a stub ``NL(...)``
    representation so the tool never raises an exception.
    """
    try:
        from ipfs_datasets_py.logic.CEC.native.dcec_nlp import DCECNLConverter
        converter = DCECNLConverter()
        result = converter.convert(text, language=language)
        return {
            "formula": str(result.formula),
            "confidence": getattr(result, "confidence", 0.75),
            "language_used": language,
        }
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("DCECNLConverter failed: %s", exc)

    # Fallback: opaque NL wrapper
    safe = text.replace('"', "'").strip()
    return {
        "formula": f'NL("{safe}")',
        "confidence": 0.3,
        "language_used": language,
        "note": "NL module not available; formula is a placeholder.",
    }


# ---------------------------------------------------------------------------
# Tool: cec_parse
# ---------------------------------------------------------------------------

class CECParseTool(ClaudeMCPTool):
    """
    MCP Tool: parse natural language text into a DCEC formula.

    Converts English (or other supported language) sentences describing
    obligations, beliefs, temporal constraints, etc. into DCEC notation.
    Returns a formula string together with a confidence score.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "cec_parse"
        self.description = (
            "Parse natural language text into a DCEC (Deontic Cognitive Event Calculus) "
            "formula. Supports English and other languages. Returns the formula string "
            "and a confidence score."
        )
        self.category = "logic_tools"
        self.tags = ["logic", "cec", "dcec", "parse", "nl", "natural-language"]
        self.version = TOOL_VERSION

        self.input_schema = {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Natural language text to parse into a DCEC formula.",
                    "maxLength": 4096,
                },
                "language": {
                    "type": "string",
                    "description": "Language of the input text.",
                    "enum": _SUPPORTED_LANGUAGES,
                    "default": "en",
                },
                "domain": {
                    "type": "string",
                    "description": "Optional domain hint (legal, medical, technical).",
                    "enum": ["legal", "medical", "technical", "general"],
                    "default": "general",
                },
            },
            "required": ["text"],
        }

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse NL text to DCEC.

        Args:
            parameters: ``text``, optional ``language`` and ``domain``.

        Returns:
            Dict with ``formula`` (str), ``confidence`` (float 0-1),
            ``language_used``, and timing.

        Example:
            >>> result = await tool.execute({
            ...     "text": "The agent must comply with the regulation",
            ...     "language": "en",
            ... })
            >>> isinstance(result["formula"], str)
            True
        """
        from ipfs_datasets_py.logic.common.validators import validate_formula_string
        start = time.monotonic()

        text: str = parameters.get("text", "").strip()
        language: str = parameters.get("language", "en")

        if not text:
            return {"success": False, "error": "'text' must be a non-empty string.", "formula": None}
        if len(text) > 4096:
            return {"success": False, "error": "'text' exceeds 4096-character limit.", "formula": None}
        if language not in _SUPPORTED_LANGUAGES:
            return {"success": False, "error": f"Unsupported language '{language}'.", "formula": None}

        parse_result = _nl_to_dcec(text, language if language != "auto" else "en")
        parse_result["success"] = True
        parse_result["elapsed_ms"] = (time.monotonic() - start) * 1000
        parse_result["tool_version"] = TOOL_VERSION
        return parse_result


# ---------------------------------------------------------------------------
# Tool: cec_validate_formula
# ---------------------------------------------------------------------------

class CECValidateFormulaTool(ClaudeMCPTool):
    """
    MCP Tool: validate a DCEC formula for syntactic correctness.

    Checks that the formula string is well-formed according to the DCEC
    grammar. Returns a list of errors/warnings so callers can give
    actionable feedback to users.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "cec_validate_formula"
        self.description = (
            "Validate a DCEC formula for syntactic correctness. "
            "Returns a list of errors and warnings."
        )
        self.category = "logic_tools"
        self.tags = ["logic", "cec", "dcec", "validate", "syntax", "formula"]
        self.version = TOOL_VERSION

        self.input_schema = {
            "type": "object",
            "properties": {
                "formula": {
                    "type": "string",
                    "description": "DCEC formula string to validate.",
                    "maxLength": 10000,
                },
            },
            "required": ["formula"],
        }

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate a DCEC formula.

        Args:
            parameters: ``formula`` (str).

        Returns:
            Dict with ``valid`` bool, ``errors`` list, ``warnings`` list,
            and timing.

        Example:
            >>> result = await tool.execute({"formula": "O(pay_taxes(agent))"})
            >>> isinstance(result["valid"], bool)
            True
        """
        from ipfs_datasets_py.logic.common.validators import validate_formula_string
        start = time.monotonic()

        formula: str = parameters.get("formula", "")
        if not formula:
            return {
                "success": False,
                "error": "'formula' must be a non-empty string.",
                "valid": False,
                "errors": [],
                "warnings": [],
            }

        # Generic size/injection check first
        try:
            validate_formula_string(formula)
        except Exception as exc:
            return {
                "success": True,
                "valid": False,
                "errors": [str(exc)],
                "warnings": [],
                "elapsed_ms": (time.monotonic() - start) * 1000,
                "tool_version": TOOL_VERSION,
            }

        errors: List[str] = []
        warnings: List[str] = []

        # Try the CEC native validator if available
        try:
            from ipfs_datasets_py.logic.CEC.native import validate_formula as _cec_validate
            is_valid, errs = _cec_validate(formula)
            if errs:
                errors.extend(errs if isinstance(errs, list) else [str(errs)])
        except ImportError:
            warnings.append("CEC native validator not available; basic size/injection check only.")
            is_valid = True  # Cannot confirm invalid without validator
        except Exception as exc:
            errors.append(f"Validation error: {exc}")
            is_valid = False

        return {
            "success": True,
            "valid": is_valid and not errors,
            "errors": errors,
            "warnings": warnings,
            "elapsed_ms": (time.monotonic() - start) * 1000,
            "tool_version": TOOL_VERSION,
        }


# ---------------------------------------------------------------------------
# Tool instances (registered in __init__.py)
# ---------------------------------------------------------------------------

CEC_PARSE_TOOLS = [
    CECParseTool(),
    CECValidateFormulaTool(),
]

__all__ = [
    "TOOL_VERSION",
    "CECParseTool",
    "CECValidateFormulaTool",
    "CEC_PARSE_TOOLS",
]
