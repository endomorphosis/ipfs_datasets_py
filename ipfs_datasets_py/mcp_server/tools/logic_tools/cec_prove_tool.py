"""
CEC / DCEC proving tools for MCP / CLI.

Functions
---------
cec_prove
    Prove a DCEC theorem given a goal and optional axioms.
cec_check_theorem
    Quickly check whether a DCEC formula is a tautology.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

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


async def cec_prove(
    goal: str,
    axioms: Optional[List[str]] = None,
    strategy: str = "auto",
    timeout: int = 30,
) -> Dict[str, Any]:
    """
    Prove a DCEC (Deontic Cognitive Event Calculus) theorem.

    Args:
        goal: Goal formula to prove (DCEC notation).
        axioms: Optional axiom formulas (max 50).
        strategy: Prover strategy — auto | z3 | vampire | e_prover.
        timeout: Timeout in seconds (1–300).

    Returns:
        Dict with ``proved`` (bool), ``prover_used``, ``proof_steps``,
        ``execution_time``, ``elapsed_ms``.
    """
    if not _AVAILABLE:
        return _unavailable("cec_prove")
    if not goal:
        return {"success": False, "error": "'goal' is required.", "proved": False}
    return await _PROCESSOR.prove_dcec(
        goal=goal, axioms=axioms, strategy=strategy, timeout=timeout
    )


async def cec_check_theorem(
    formula: str,
    axioms: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Check whether a DCEC formula is a tautology.

    Args:
        formula: Formula to check.
        axioms: Optional axioms to assume (max 50).

    Returns:
        Dict with ``is_theorem`` (bool).
    """
    if not _AVAILABLE:
        return _unavailable("cec_check_theorem")
    if not formula:
        return {"success": False, "error": "'formula' is required.", "is_theorem": False}
    return await _PROCESSOR.check_dcec_theorem(formula=formula, axioms=axioms)


__all__ = ["cec_prove", "cec_check_theorem",
           "prove_dcec", "check_theorem", "get_proof_tree", "TOOLS"]


def prove_dcec(formula: str = "", goal: str = "",
               strategy: str = "auto",
               axioms: Optional[List[str]] = None,
               timeout: int = 30,
               timeout_ms: int = 0) -> Dict[str, Any]:
    """Sync wrapper around cec_prove for backward compatibility.
    Accepts both 'formula' (positional) and 'goal' keyword."""
    import asyncio
    actual_goal = goal or formula
    actual_timeout = timeout if not timeout_ms else max(1, timeout_ms // 1000)
    result = asyncio.get_event_loop().run_until_complete(
        cec_prove(goal=actual_goal, axioms=axioms, strategy=strategy, timeout=actual_timeout)
    )
    result.setdefault("execution_time", result.get("elapsed_ms", 0) / 1000)
    return result


def check_theorem(formula: str) -> Dict[str, Any]:
    """Sync wrapper around cec_check_theorem for backward compatibility."""
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(cec_check_theorem(formula=formula))
    result.setdefault("is_theorem", result.get("proved", False))
    return result


def get_proof_tree(formula: str) -> Dict[str, Any]:
    """Return a simple proof tree structure for a formula."""
    if not formula:
        return {"success": False, "error": "'formula' is required."}
    # Count nesting depth
    max_depth, cur_depth = 0, 0
    for ch in formula:
        if ch == '(':
            cur_depth += 1
            max_depth = max(max_depth, cur_depth)
        elif ch == ')':
            cur_depth = max(0, cur_depth - 1)
    return {
        "success": True,
        "formula": formula,
        "depth": max_depth,
        "tree": {
            "root": formula,
            "depth": max_depth,
            "steps": [{"step": 1, "formula": formula, "rule": "hypothesis"}],
        },
    }


TOOLS: Dict[str, Any] = {
    "cec_prove": cec_prove,
    "prove_dcec": prove_dcec,
    "cec_check_theorem": cec_check_theorem,
    "check_theorem": check_theorem,
    "get_proof_tree": get_proof_tree,
}


# ---------------------------------------------------------------------------
# OOP wrapper classes expected by test_mcp_cec_prove_parse_analysis.py
# ---------------------------------------------------------------------------

import asyncio as _asyncio
import time as _time


class _BaseCECTool:
    """Base class for CEC MCP tools."""
    name: str = ""
    category: str = "logic_tools"
    tags: List[str] = []
    input_schema: Dict[str, Any] = {}

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class CECProveTool(_BaseCECTool):
    name = "cec_prove"
    category = "logic_tools"
    tags = ["cec", "prove", "dcec"]
    input_schema = {"goal": {"type": "string"}, "axioms": {"type": "array"}}

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        t0 = _time.monotonic()
        goal = params.get("goal") or params.get("formula")
        if not goal:
            return {"success": False, "error": "'goal' is required.", "elapsed_ms": 0}
        result = await cec_prove(goal=goal, axioms=params.get("axioms"))
        result.setdefault("elapsed_ms", int((_time.monotonic() - t0) * 1000))
        result.setdefault("tool_version", "1.0.0")
        return result


class CECCheckTheoremTool(_BaseCECTool):
    name = "cec_check_theorem"
    category = "logic_tools"
    tags = ["cec", "check", "tautology"]
    input_schema = {"formula": {"type": "string"}}

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        t0 = _time.monotonic()
        formula = params.get("formula")
        if not formula:
            return {"success": False, "error": "'formula' is required.", "elapsed_ms": 0}
        result = await cec_check_theorem(formula=formula)
        result.setdefault("counterexample", None)
        result.setdefault("is_theorem", result.get("proved", False))
        result.setdefault("elapsed_ms", int((_time.monotonic() - t0) * 1000))
        result.setdefault("tool_version", "1.0.0")
        return result
