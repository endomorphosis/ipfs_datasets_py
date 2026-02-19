"""
TDFOL proving tools for MCP / CLI.

Functions
---------
tdfol_prove
    Prove a single TDFOL formula.
tdfol_batch_prove
    Prove multiple TDFOL formulas in batch.
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


async def tdfol_prove(
    formula: str,
    axioms: Optional[List[str]] = None,
    strategy: str = "auto",
    timeout_ms: int = 5000,
    max_depth: int = 10,
    include_proof_steps: bool = True,
) -> Dict[str, Any]:
    """
    Prove a TDFOL (Temporal Deontic First-Order Logic) formula.

    Args:
        formula: Formula to prove (TDFOL notation).
        axioms: Axiom formulas to use in the proof.
        strategy: Proving strategy — auto | forward | backward | modal_tableaux | hybrid.
        timeout_ms: Timeout in milliseconds (100–60 000).
        max_depth: Maximum proof search depth (1–100).
        include_proof_steps: Include detailed proof steps in the result.

    Returns:
        Dict with ``proved`` (bool), ``status``, ``method``, ``proof_steps``.
    """
    if not _AVAILABLE:
        return _unavailable("tdfol_prove")
    if not formula:
        return {"success": False, "error": "'formula' is required."}
    return await _PROCESSOR.prove_tdfol(
        formula=formula,
        axioms=axioms,
        strategy=strategy,
        timeout_ms=timeout_ms,
        max_depth=max_depth,
        include_proof_steps=include_proof_steps,
    )


async def tdfol_batch_prove(
    formulas: Optional[List[str]] = None,
    shared_axioms: Optional[List[str]] = None,
    strategy: str = "auto",
    timeout_per_formula_ms: int = 5000,
    stop_on_first_failure: bool = False,
) -> Dict[str, Any]:
    """
    Prove multiple TDFOL formulas in batch.

    Args:
        formulas: List of formulas to prove.
        shared_axioms: Axioms to use for all proofs.
        strategy: Proving strategy.
        timeout_per_formula_ms: Per-formula timeout in milliseconds.
        stop_on_first_failure: Stop after the first proof failure.

    Returns:
        Dict with ``results`` (list), ``total_proved``, ``total_failed``.
    """
    if not _AVAILABLE:
        return _unavailable("tdfol_batch_prove")
    if not formulas:
        return {"success": False, "error": "'formulas' must be a non-empty list."}
    return await _PROCESSOR.batch_prove_tdfol(
        formulas=formulas,
        shared_axioms=shared_axioms,
        strategy=strategy,
        timeout_per_formula_ms=timeout_per_formula_ms,
        stop_on_first_failure=stop_on_first_failure,
    )


__all__ = ["tdfol_prove", "tdfol_batch_prove"]
