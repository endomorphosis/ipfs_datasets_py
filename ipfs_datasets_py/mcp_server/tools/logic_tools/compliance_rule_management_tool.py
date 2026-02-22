"""Compliance rule management MCP tools (Phase J — session 57).

Exposes :class:`~compliance_checker.ComplianceChecker` rule management as
callable MCP tools so operators can add, list, and remove custom compliance
rules at runtime without restarting the server.

Built-in rules (``tool_name_convention``, ``intent_has_actor``, etc.) are
always present in the global checker.  This module lets you add lightweight
*stub* rules (always COMPLIANT) or run ad-hoc compliance checks from an MCP
client.

For non-trivial rule logic, operators should implement the rule function
directly in Python and call ``ComplianceChecker.add_rule()`` programmatically;
the MCP tools here are intended for inspection and lightweight extension.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

__all__ = [
    "compliance_add_rule",
    "compliance_list_rules",
    "compliance_remove_rule",
    "compliance_check_intent",
]


# ---------------------------------------------------------------------------
# Global checker singleton
# ---------------------------------------------------------------------------

_GLOBAL_CHECKER: Any = None


def _get_checker() -> Any:
    """Return the process-global :class:`ComplianceChecker` (lazy-init)."""
    global _GLOBAL_CHECKER
    if _GLOBAL_CHECKER is None:
        try:
            from ipfs_datasets_py.mcp_server.compliance_checker import (  # noqa: PLC0415
                make_default_compliance_checker,
            )
            _GLOBAL_CHECKER = make_default_compliance_checker()
        except Exception:
            from ipfs_datasets_py.mcp_server.compliance_checker import (  # noqa: PLC0415
                ComplianceChecker,
            )
            _GLOBAL_CHECKER = ComplianceChecker()
    return _GLOBAL_CHECKER


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

async def compliance_add_rule(
    rule_id: str,
    description: str = "",
    severity: str = "warning",
) -> Dict[str, Any]:
    """Register a stub compliance rule that always returns COMPLIANT.

    Operators wanting non-trivial rule logic should implement the callable
    directly and use :meth:`ComplianceChecker.add_rule` programmatically.
    This MCP tool is useful for reserving a rule ID slot or for testing the
    compliance reporting pipeline.

    Args:
        rule_id: Unique identifier for the new rule (must not be empty).
        description: Human-readable description stored in the rule metadata.
        severity: Severity hint (``"warning"`` / ``"error"`` / ``"info"``).
            Stored in violation messages if the stub is ever overridden.

    Returns:
        ``{"status": "added", "rule_id": rule_id, "description": description}``

    Raises:
        ValueError: If *rule_id* is empty.
    """
    if not rule_id or not rule_id.strip():
        raise ValueError("rule_id must be a non-empty string")

    checker = _get_checker()
    from ipfs_datasets_py.mcp_server.compliance_checker import (  # noqa: PLC0415
        ComplianceResult,
        ComplianceStatus,
    )

    def _stub_rule(intent: Any) -> "ComplianceResult":
        return ComplianceResult(
            rule_id=rule_id,
            status=ComplianceStatus.COMPLIANT,
            violations=[],
            checked_at=None,
        )

    checker.add_rule(rule_id, _stub_rule)
    return {
        "status": "added",
        "rule_id": rule_id,
        "description": description,
        "severity": severity,
    }


async def compliance_list_rules() -> Dict[str, Any]:
    """List all currently registered compliance rule IDs.

    Returns:
        ``{"rules": [...rule_ids...]}``
    """
    checker = _get_checker()
    return {"rules": checker.list_rules()}


async def compliance_remove_rule(rule_id: str) -> Dict[str, Any]:
    """Remove a compliance rule by ID.

    Built-in rules can be removed the same way as custom ones.

    Args:
        rule_id: Rule ID to remove.

    Returns:
        ``{"status": "removed"|"not_found", "rule_id": rule_id}``
    """
    checker = _get_checker()
    removed = checker.remove_rule(rule_id)
    return {
        "status": "removed" if removed else "not_found",
        "rule_id": rule_id,
    }


async def compliance_check_intent(
    tool_name: str,
    actor: str = "",
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Check a synthetic intent against the global compliance checker.

    Args:
        tool_name: Tool name to validate.
        actor: Actor identifier (empty string = anonymous).
        params: Optional parameter dict for the ``params_are_serializable``
            rule check.

    Returns:
        A :meth:`~ComplianceReport.to_dict` compatible dict containing
        the per-rule results and overall summary.
    """
    checker = _get_checker()
    intent = {
        "tool_name": tool_name,
        "actor": actor,
        "params": params if params is not None else {},
    }
    report = checker.check_compliance(intent)
    return report.to_dict()
