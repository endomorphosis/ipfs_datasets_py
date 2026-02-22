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

import asyncio
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


__all__ = ["cec_analyze_formula", "cec_formula_complexity", "analyze_formula", "formula_complexity"]


def _run_async(coro):
    """Run a coroutine synchronously, handling already-running event loops."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _analyze_formula_sync(formula: str) -> Dict[str, Any]:
    """Sync wrapper for analyze_formula (backward-compat for tests calling without await)."""
    if not _AVAILABLE:
        return _unavailable("analyze_formula")
    if not formula:
        return {"success": False, "error": "'formula' is required."}
    return _run_async(cec_analyze_formula(formula))


def _formula_complexity_sync(formula: str) -> Dict[str, Any]:
    """Sync wrapper for formula_complexity (backward-compat for tests calling without await)."""
    if not _AVAILABLE:
        return _unavailable("formula_complexity")
    if not formula:
        return {"success": False, "error": "'formula' is required."}
    return _run_async(cec_formula_complexity(formula))


# Backward-compat aliases — sync wrappers
analyze_formula = _analyze_formula_sync
formula_complexity = _formula_complexity_sync
