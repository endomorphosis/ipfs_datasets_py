"""
CEC Analysis Tool — Analyze DCEC formulas for complexity and properties via MCP.

Exposes two MCP tools:

    - ``cec_analyze_formula``   — Structural analysis (depth, size, operators).
    - ``cec_formula_complexity`` — Quick complexity classification (low / medium / high).

These replace the former ``analyze_formula``, ``visualize_proof``,
``get_formula_complexity``, and ``profile_operation`` plain-function helpers
(originally registered through the legacy ``TOOLS`` dict) with proper
``ClaudeMCPTool`` subclasses that integrate directly with the ToolRegistry.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool

logger = logging.getLogger(__name__)

TOOL_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _structural_analysis(formula_str: str) -> Dict[str, Any]:
    """
    Compute structural metrics for *formula_str*.

    Returns depth, size (subformula count), and operator list.
    Falls back to text-level metrics when CEC native is unavailable.
    """
    try:
        from ipfs_datasets_py.logic.CEC.native import parse_dcec_string

        formula_obj = parse_dcec_string(formula_str)

        def _depth(f: Any) -> int:
            children = getattr(f, "subformulas", []) or []
            return 1 + max((_depth(c) for c in children), default=0)

        def _size(f: Any) -> int:
            children = getattr(f, "subformulas", []) or []
            return 1 + sum(_size(c) for c in children)

        def _operators(f: Any) -> List[str]:
            ops: List[str] = []
            if hasattr(f, "operator"):
                ops.append(str(f.operator))
            for c in getattr(f, "subformulas", []) or []:
                ops.extend(_operators(c))
            return ops

        depth = _depth(formula_obj)
        size = _size(formula_obj)
        operators = sorted(set(_operators(formula_obj)))

        return {
            "depth": depth,
            "size": size,
            "operators": operators,
            "source": "cec_native",
        }
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("CEC structural analysis failed: %s", exc)

    # Text-level fallback
    depth = formula_str.count("(")
    size = max(1, formula_str.count(",") + 1)
    ops_hint = [t for t in ("->", "<->", "&", "|", "~", "O(", "K(", "B(") if t in formula_str]
    return {
        "depth": depth,
        "size": size,
        "operators": ops_hint,
        "source": "text_heuristic",
        "note": "CEC native parser unavailable; heuristic values only.",
    }


def _classify_complexity(depth: int, size: int, formula_len: int) -> str:
    """Return 'low' | 'medium' | 'high' based on metrics."""
    score = depth + size // 5 + formula_len // 50
    if score <= 4:
        return "low"
    if score <= 12:
        return "medium"
    return "high"


# ---------------------------------------------------------------------------
# Tool: cec_analyze_formula
# ---------------------------------------------------------------------------

class CECAnalyzeFormulaTool(ClaudeMCPTool):
    """
    MCP Tool: structural analysis of a DCEC formula.

    Computes depth (nesting), size (subformula count), and the set of
    logical operators used. Useful for understanding formula complexity
    before attempting expensive proof operations.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "cec_analyze_formula"
        self.description = (
            "Analyze a DCEC formula for structural properties: nesting depth, "
            "subformula count, and logical operators used."
        )
        self.category = "logic_tools"
        self.tags = ["logic", "cec", "dcec", "analysis", "complexity", "structure"]
        self.version = TOOL_VERSION

        self.input_schema = {
            "type": "object",
            "properties": {
                "formula": {
                    "type": "string",
                    "description": "DCEC formula string to analyse.",
                    "maxLength": 10000,
                },
                "include_complexity": {
                    "type": "boolean",
                    "description": "Include overall complexity classification.",
                    "default": True,
                },
            },
            "required": ["formula"],
        }

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyse a DCEC formula.

        Args:
            parameters: ``formula`` (str), optional ``include_complexity`` bool.

        Returns:
            Dict with ``depth``, ``size``, ``operators`` (list[str]),
            optional ``complexity`` ('low'|'medium'|'high'), and timing.

        Example:
            >>> result = await tool.execute({"formula": "O(P(x)) & K(agent, Q(y))"})
            >>> isinstance(result["depth"], int)
            True
        """
        from ipfs_datasets_py.logic.common.validators import validate_formula_string
        start = time.monotonic()

        formula: str = parameters.get("formula", "")
        include_complexity: bool = parameters.get("include_complexity", True)

        if not formula:
            return {"success": False, "error": "'formula' must be non-empty."}

        try:
            validate_formula_string(formula)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

        analysis = _structural_analysis(formula)

        result: Dict[str, Any] = {
            "success": True,
            "depth": analysis["depth"],
            "size": analysis["size"],
            "operators": analysis["operators"],
            "formula_length": len(formula),
            "elapsed_ms": (time.monotonic() - start) * 1000,
            "tool_version": TOOL_VERSION,
        }
        if analysis.get("source") == "text_heuristic":
            result["note"] = analysis.get("note", "")

        if include_complexity:
            result["complexity"] = _classify_complexity(
                analysis["depth"], analysis["size"], len(formula)
            )

        return result


# ---------------------------------------------------------------------------
# Tool: cec_formula_complexity
# ---------------------------------------------------------------------------

class CECFormulaComplexityTool(ClaudeMCPTool):
    """
    MCP Tool: quick complexity classification for a DCEC formula.

    Returns a single complexity label (low / medium / high) along with
    scalar metrics (modal depth, connective count, overall score).
    Use this when you only need a quick verdict rather than full structural
    analysis from ``cec_analyze_formula``.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "cec_formula_complexity"
        self.description = (
            "Return a quick complexity classification (low / medium / high) "
            "for a DCEC formula, with scalar metrics."
        )
        self.category = "logic_tools"
        self.tags = ["logic", "cec", "dcec", "complexity", "metrics", "classification"]
        self.version = TOOL_VERSION

        self.input_schema = {
            "type": "object",
            "properties": {
                "formula": {
                    "type": "string",
                    "description": "DCEC formula to classify.",
                    "maxLength": 10000,
                },
            },
            "required": ["formula"],
        }

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Classify formula complexity.

        Args:
            parameters: ``formula`` (str).

        Returns:
            Dict with ``overall_complexity`` ('low'|'medium'|'high'),
            ``modal_depth``, ``connective_count``, ``formula_length``, and timing.

        Example:
            >>> result = await tool.execute({"formula": "O(P(x)) -> K(agent, Q(y))"})
            >>> result["overall_complexity"] in ("low", "medium", "high")
            True
        """
        from ipfs_datasets_py.logic.common.validators import validate_formula_string
        start = time.monotonic()

        formula: str = parameters.get("formula", "")
        if not formula:
            return {"success": False, "error": "'formula' must be non-empty."}

        try:
            validate_formula_string(formula)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

        analysis = _structural_analysis(formula)

        # Modal operators heuristic: count O(, K(, B(, []( etc.
        modal_indicators = ("O(", "K(", "B(", "D(", "[](", "<>(", "T(", "H(")
        modal_depth = sum(formula.count(m) for m in modal_indicators)

        # Connective count
        connective_indicators = ("->", "<->", " & ", " | ", " ~ ", "~", " ∧ ", " ∨ ")
        connective_count = sum(formula.count(c) for c in connective_indicators)

        overall = _classify_complexity(analysis["depth"], analysis["size"], len(formula))

        return {
            "success": True,
            "overall_complexity": overall,
            "modal_depth": modal_depth,
            "connective_count": connective_count,
            "formula_length": len(formula),
            "depth": analysis["depth"],
            "size": analysis["size"],
            "elapsed_ms": (time.monotonic() - start) * 1000,
            "tool_version": TOOL_VERSION,
        }


# ---------------------------------------------------------------------------
# Tool instances (registered in __init__.py)
# ---------------------------------------------------------------------------

CEC_ANALYSIS_TOOLS = [
    CECAnalyzeFormulaTool(),
    CECFormulaComplexityTool(),
]

__all__ = [
    "TOOL_VERSION",
    "CECAnalyzeFormulaTool",
    "CECFormulaComplexityTool",
    "CEC_ANALYSIS_TOOLS",
]
