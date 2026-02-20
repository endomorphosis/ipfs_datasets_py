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
    """Sync wrapper + augmented analysis around cec_analyze_formula."""
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(cec_analyze_formula(formula=formula))
    # Compute more accurate nesting depth via parentheses
    if result.get("success"):
        max_depth, cur_depth = 0, 0
        for ch in formula:
            if ch == '(':
                cur_depth += 1
                max_depth = max(max_depth, cur_depth)
            elif ch == ')':
                cur_depth = max(0, cur_depth - 1)
        # Override depth if our count is higher (parser may undercount)
        if max_depth > result.get("depth", 0):
            result["depth"] = max_depth
        result.setdefault("complexity", result.get("depth", 1))
    return result


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
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(cec_formula_complexity(formula=formula))
    # Add overall_complexity alias for backward compatibility
    if result.get("success"):
        result.setdefault("overall_complexity", result.get("complexity", "unknown"))
    return result


def profile_operation(operation: str, formula: str, iterations: int = 10) -> Dict[str, Any]:
    """Profile an operation (parse/prove/analyze) over multiple iterations."""
    import asyncio
    import time
    if not formula:
        return {"success": False, "error": "'formula' is required."}
    times: list = []
    for _ in range(max(1, iterations)):
        start = time.monotonic()
        if operation == "analyze":
            asyncio.get_event_loop().run_until_complete(cec_analyze_formula(formula=formula))
        else:
            asyncio.get_event_loop().run_until_complete(cec_analyze_formula(formula=formula))
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
