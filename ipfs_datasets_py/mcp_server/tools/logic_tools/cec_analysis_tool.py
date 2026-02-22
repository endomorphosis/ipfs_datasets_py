"""
CEC / DCEC formula analysis tools for MCP / CLI.

Functions
---------
cec_analyze_formula
    Structural analysis — depth, size, operators.
cec_formula_complexity
    Quick low / medium / high complexity classification.
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


async def cec_analyze_formula(formula: str) -> Dict[str, Any]:
    """
    Perform structural analysis on a DCEC/CEC formula.

    Args:
        formula: Formula string to analyse.

    Returns:
        Dict with ``depth`` (int), ``size`` (int), ``operators`` (list[str]),
        ``parsed_ok`` (bool), ``elapsed_ms``.
    """
    if not _AVAILABLE:
        return _unavailable("cec_analyze_formula")
    if not formula:
        return {"success": False, "error": "'formula' is required."}
    return await _PROCESSOR.analyze_formula(formula_str=formula)


async def cec_formula_complexity(formula: str) -> Dict[str, Any]:
    """
    Classify the complexity of a DCEC/CEC formula.

    Args:
        formula: Formula string.

    Returns:
        Dict with ``complexity`` (low | medium | high), ``depth``, ``size``.
    """
    if not _AVAILABLE:
        return _unavailable("cec_formula_complexity")
    if not formula:
        return {"success": False, "error": "'formula' is required."}
    return await _PROCESSOR.get_formula_complexity(formula_str=formula)


__all__ = ["cec_analyze_formula", "cec_formula_complexity",
           "analyze_formula", "visualize_proof", "profile_operation",
           "get_formula_complexity", "TOOLS"]


def analyze_formula(formula: str) -> Dict[str, Any]:
    """Sync pure analysis around a formula (no event loop)."""
    if not formula:
        return {"success": False, "error": "'formula' is required."}
    # Security guard
    DISALLOWED = ["__import__", "eval(", "exec(", "os.system", "subprocess"]
    if any(d in formula for d in DISALLOWED):
        return {"success": False, "error": "Disallowed pattern in formula."}
    # Compute nesting depth via parentheses
    max_depth, cur_depth = 0, 0
    for ch in formula:
        if ch == '(':
            cur_depth += 1
            max_depth = max(max_depth, cur_depth)
        elif ch == ')':
            cur_depth = max(0, cur_depth - 1)
    # Extract operators
    operators = []
    for op in ('->', '→', '&', '∧', '|', '∨', '¬', '~', '↔', '<->'):
        if op in formula:
            operators.append(op)
    # Count tokens (words/symbols)
    import re
    tokens = re.findall(r'[A-Za-z_]\w*|[-><&|∧∨¬~→←↔◻◊□◇KBO@]', formula)
    size = max(1, len(tokens))
    # Complexity
    modal_ops = ('□', '◇', '◻', '◊')
    modal_depth = sum(formula.count(op) for op in modal_ops)
    connective_count = len(operators)
    score = modal_depth * 3 + connective_count * 2 + len(formula) // 20
    if score < 3:
        complexity = "low"
    elif score < 8:
        complexity = "medium"
    else:
        complexity = "high"
    return {
        "success": True,
        "formula": formula,
        "depth": max_depth,
        "size": size,
        "operators": operators,
        "complexity": complexity,
        "overall_complexity": complexity,
    }


def visualize_proof(formula: str, format: str = "text") -> Dict[str, Any]:
    """Return a simple visualization of a formula proof."""
    if not formula:
        return {"success": False, "error": "'formula' is required."}
    result: Dict[str, Any] = {"success": True, "formula": formula, "format": format}
    if format == "json":
        result["nodes"] = [{"id": 0, "label": formula, "type": "root"}]
        result["edges"] = []
    else:
        result["text"] = f"  ─── {formula}"
    return result


def get_formula_complexity(formula: str) -> Dict[str, Any]:
    """Sync wrapper around cec_formula_complexity."""
    # Duplicate core logic to avoid nested event loop issues
    if not formula:
        return {"success": False, "error": "'formula' is required."}
    modal_ops = ('□', '◇', '◻', '◊')
    modal_depth = sum(formula.count(op) for op in modal_ops)
    connective_ops = ('->', '→', '&', '∧', '|', '∨', '¬', '~', '↔', '<->')
    connective_count = sum(formula.count(op) for op in connective_ops)
    formula_length = len(formula)
    score = modal_depth * 3 + connective_count * 2 + formula_length // 20
    if score < 3:
        complexity = "low"
    elif score < 8:
        complexity = "medium"
    else:
        complexity = "high"
    result = {
        "success": True,
        "formula": formula,
        "modal_depth": modal_depth,
        "connective_count": connective_count,
        "formula_length": formula_length,
        "complexity": complexity,
        "overall_complexity": complexity,
    }
    return result


def profile_operation(operation: str, formula: str, iterations: int = 10) -> Dict[str, Any]:
    """Profile an operation (parse/prove/analyze) over multiple iterations."""
    import time
    if not formula:
        return {"success": False, "error": "'formula' is required."}
    times: list = []
    for _ in range(max(1, iterations)):
        start = time.monotonic()
        analyze_formula(formula=formula)
        times.append(time.monotonic() - start)
    avg = sum(times) / len(times)
    return {
        "success": True,
        "operation": operation,
        "formula": formula,
        "iterations": iterations,
        "avg_time": avg,
        "total_time": sum(times),
        "min_time": min(times),
        "max_time": max(times),
    }


TOOLS: Dict[str, Any] = {
    "cec_analyze_formula": cec_analyze_formula,
    "analyze_formula": analyze_formula,
    "cec_formula_complexity": cec_formula_complexity,
    "get_formula_complexity": get_formula_complexity,
    "visualize_proof": visualize_proof,
    "profile_operation": profile_operation,
}


# ---------------------------------------------------------------------------
# OOP wrapper classes expected by test_mcp_cec_prove_parse_analysis.py
# ---------------------------------------------------------------------------

import time as _time


class _BaseCECTool:
    name: str = ""
    category: str = "logic_tools"
    tags: List[str] = []
    input_schema: Dict[str, Any] = {}

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class CECAnalyzeFormulaTool(_BaseCECTool):
    name = "cec_analyze_formula"
    category = "logic_tools"
    tags = ["cec", "analysis", "formula"]
    input_schema = {"formula": {"type": "string"}, "include_complexity": {"type": "boolean"}}

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        t0 = _time.monotonic()
        formula = params.get("formula")
        if not formula:
            return {"success": False, "error": "'formula' is required.", "elapsed_ms": 0}
        include_complexity = params.get("include_complexity", True)
        result = dict(analyze_formula(formula=formula))
        if not include_complexity:
            result.pop("complexity", None)
        result.setdefault("elapsed_ms", int((_time.monotonic() - t0) * 1000))
        result.setdefault("tool_version", "1.0.0")
        return result


class CECFormulaComplexityTool(_BaseCECTool):
    name = "cec_formula_complexity"
    category = "logic_tools"
    tags = ["cec", "complexity", "formula"]
    input_schema = {"formula": {"type": "string"}}

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        t0 = _time.monotonic()
        formula = params.get("formula")
        if not formula:
            return {"success": False, "error": "'formula' is required.", "elapsed_ms": 0}
        result = dict(get_formula_complexity(formula=formula))
        result.setdefault("elapsed_ms", int((_time.monotonic() - t0) * 1000))
        result.setdefault("tool_version", "1.0.0")
        return result
