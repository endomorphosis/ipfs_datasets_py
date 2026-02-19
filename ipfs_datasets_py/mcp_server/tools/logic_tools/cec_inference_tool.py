"""
CEC Inference Rule tools for MCP / CLI.

Exposes four async functions that are auto-discovered by the CLI
(``ipfs_datasets_cli.py``) and callable via the MCP server.  All
business logic lives in :class:`~ipfs_datasets_py.core_operations.LogicProcessor`.

Functions
---------
cec_list_rules
    List available CEC inference rules (optionally filtered by category).
cec_apply_rule
    Apply a named rule to formula strings and return derived conclusions.
cec_check_rule
    Check applicability of a rule without applying it.
cec_rule_info
    Return full documentation for a named rule.
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


async def cec_list_rules(
    category: str = "",
    include_description: bool = True,
) -> Dict[str, Any]:
    """
    List available CEC (Cognitive Event Calculus) inference rules.

    Args:
        category: Optional filter — one of propositional, temporal, deontic,
            cognitive, modal, resolution, specialized.
        include_description: Include one-line rule docstrings in output.

    Returns:
        Dict with ``rules`` (list), ``total`` (int), ``success`` (bool).
    """
    if not _AVAILABLE:
        return _unavailable("cec_list_rules")
    return await _PROCESSOR.list_cec_rules(category=category, include_description=include_description)


async def cec_apply_rule(
    rule: str,
    formulas: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Apply a named CEC inference rule to a list of formula strings.

    Args:
        rule: Name of the rule (e.g. ``ModusPonens``).
        formulas: Input formula strings (max 20).

    Returns:
        Dict with ``applicable`` (bool), ``conclusions`` (list[str]).
    """
    if not _AVAILABLE:
        return _unavailable("cec_apply_rule")
    if not rule:
        return {"success": False, "error": "'rule' is required."}
    return await _PROCESSOR.apply_cec_rule(rule_name=rule, formulas=formulas or [])


async def cec_check_rule(
    rule: str,
    formulas: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Check whether a CEC inference rule can be applied (no derivation).

    Args:
        rule: Rule name.
        formulas: Input formula strings.

    Returns:
        Dict with ``applicable`` (bool).
    """
    if not _AVAILABLE:
        return _unavailable("cec_check_rule")
    if not rule:
        return {"success": False, "error": "'rule' is required."}
    return await _PROCESSOR.check_cec_rule(rule_name=rule, formulas=formulas or [])


async def cec_rule_info(rule: str) -> Dict[str, Any]:
    """
    Return documentation and metadata for a named CEC inference rule.

    Args:
        rule: Rule name (e.g. ``NecessityElimination``).

    Returns:
        Dict with ``name``, ``category``, ``module``, ``docstring``, ``methods``.
    """
    if not _AVAILABLE:
        return _unavailable("cec_rule_info")
    if not rule:
        return {"success": False, "error": "'rule' is required."}
    return await _PROCESSOR.get_cec_rule_info(rule_name=rule)


__all__ = ["cec_list_rules", "cec_apply_rule", "cec_check_rule", "cec_rule_info"]
