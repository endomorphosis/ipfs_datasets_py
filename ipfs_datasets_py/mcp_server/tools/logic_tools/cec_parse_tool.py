"""
CEC / DCEC parsing and validation tools for MCP / CLI.

Functions
---------
cec_parse
    Parse natural language text into a DCEC formula string.
cec_validate_formula
    Validate a DCEC formula for syntactic correctness.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

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


async def cec_parse(
    text: str,
    language: str = "en",
    domain: str = "general",
) -> Dict[str, Any]:
    """
    Parse natural language text into a DCEC formula string.

    Args:
        text: Natural language input (max 4096 characters).
        language: Input language — en | es | fr | de | auto.
        domain: Domain hint — legal | medical | technical | general.

    Returns:
        Dict with ``formula`` (str), ``confidence`` (float 0–1),
        ``language_used``, ``elapsed_ms``.
    """
    if not _AVAILABLE:
        return _unavailable("cec_parse")
    if not text:
        return {"success": False, "error": "'text' is required.", "formula": None}
    return await _PROCESSOR.parse_dcec(text=text, language=language)


async def cec_validate_formula(formula: str) -> Dict[str, Any]:
    """
    Validate a DCEC formula for syntactic correctness.

    Args:
        formula: DCEC formula string to validate (max 10 000 characters).

    Returns:
        Dict with ``valid`` (bool), ``errors`` (list), ``warnings`` (list).
    """
    if not _AVAILABLE:
        return _unavailable("cec_validate_formula")
    if not formula:
        return {"success": False, "valid": False, "errors": ["'formula' is required."], "warnings": []}
    return await _PROCESSOR.validate_formula(formula_str=formula, logic_system="dcec")


def _parse_dcec_sync(text: str, language: str = "en", domain: str = "general") -> Dict[str, Any]:
    """Sync wrapper for parse_dcec (backward-compat for tests calling without await)."""
    if not _AVAILABLE:
        return _unavailable("parse_dcec")
    if not text:
        return {"success": False, "error": "'text' is required.", "formula": None}
    return _run_async(cec_parse(text, language=language, domain=domain))


def _validate_dcec_formula_sync(formula: str) -> Dict[str, Any]:
    """Sync wrapper for validate_dcec_formula (backward-compat for tests calling without await)."""
    if not _AVAILABLE:
        return _unavailable("validate_dcec_formula")
    if not formula:
        return {"success": False, "valid": False, "errors": ["'formula' is required."], "warnings": []}
    return _run_async(cec_validate_formula(formula))


__all__ = ["cec_parse", "cec_validate_formula", "parse_dcec", "validate_dcec_formula"]

# Backward-compat aliases — sync wrappers for code that calls without await
parse_dcec = _parse_dcec_sync
validate_dcec_formula = _validate_dcec_formula_sync
