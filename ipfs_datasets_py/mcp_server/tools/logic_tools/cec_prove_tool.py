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


__all__ = ["cec_prove", "cec_check_theorem"]
