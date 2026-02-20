"""Software Engineering Theorems engine — canonical business-logic location.

Contains the ``SOFTWARE_THEOREMS`` registry dict and helper functions
(``list_software_theorems``, ``validate_against_theorem``, ``_evaluate_condition``,
``apply_theorem_actions``) for temporal deontic logic reasoning over software
engineering operations.

Previously embedded inside the MCP tool wrapper at
``ipfs_datasets_py/mcp_server/tools/software_engineering_tools/software_theorems.py``.

Keeping them here means the same logic can be used from:
- ``ipfs_datasets_py.processors.development.software_theorems_engine`` (package import)
- ``ipfs_datasets_py-cli software theorems ...``                         (CLI)
- The MCP server tool (thin wrapper in tools/software_engineering_tools/)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Theorem registry
# ---------------------------------------------------------------------------

SOFTWARE_THEOREMS: Dict[str, Dict[str, Any]] = {
    "ci_failure_notification": {
        "name": "CI Failure Notification Rule",
        "formula": "∀t,p: (CI_Failed(p, t, 3) → Obligatory(Notify_Team(p, t)))",
        "description": "If CI fails 3 times for a project, it is obligatory to notify the team",
        "domain": "devops",
        "severity": "high",
        "variables": {
            "p": "project identifier",
            "t": "timestamp",
            "3": "failure threshold",
        },
        "conditions": ["ci_failed_count >= 3", "notification_not_sent"],
        "actions": ["send_team_notification", "create_incident"],
    },
    "deployment_rollback": {
        "name": "Automatic Deployment Rollback Rule",
        "formula": "∀d,t: (Error_Rate(d, t) > 0.05 ∧ Duration(t) > 300 → Obligatory(Rollback(d, t)))",
        "description": (
            "If error rate exceeds 5% for more than 5 minutes after deployment, "
            "rollback is obligatory"
        ),
        "domain": "devops",
        "severity": "critical",
        "variables": {
            "d": "deployment identifier",
            "t": "timestamp",
            "0.05": "error rate threshold (5%)",
            "300": "duration threshold in seconds",
        },
        "conditions": ["error_rate > 0.05", "duration > 300"],
        "actions": ["trigger_rollback", "alert_operations_team"],
    },
    "code_review_requirement": {
        "name": "Code Review Requirement Rule",
        "formula": "∀pr,l: (Changed_Lines(pr) > l → Obligatory(Min_Reviews(pr, 2)))",
        "description": (
            "Pull requests with more than threshold changed lines require at least 2 reviews"
        ),
        "domain": "development",
        "severity": "medium",
        "variables": {
            "pr": "pull request identifier",
            "l": "line count threshold (default: 500)",
            "2": "minimum required reviews",
        },
        "conditions": ["changed_lines > threshold", "review_count < 2"],
        "actions": ["request_additional_review", "block_merge"],
    },
    "resource_scaling": {
        "name": "Automatic Resource Scaling Rule",
        "formula": "∀s,t: (CPU_Usage(s, t) > 80 ∧ Duration(t) > 300 → Obligatory(Scale_Up(s)))",
        "description": (
            "If CPU usage exceeds 80% for more than 5 minutes, scaling up is obligatory"
        ),
        "domain": "infrastructure",
        "severity": "high",
        "variables": {
            "s": "service identifier",
            "t": "timestamp",
            "80": "CPU usage threshold (%)",
            "300": "duration threshold in seconds",
        },
        "conditions": ["cpu_usage > 80", "duration > 300"],
        "actions": ["scale_up_service", "alert_infrastructure_team"],
    },
    "security_scan_requirement": {
        "name": "Security Scan Before Deploy Rule",
        "formula": "∀d: (Ready_To_Deploy(d) → Obligatory(Security_Scan_Passed(d)))",
        "description": "All deployments must pass security scanning before being deployed",
        "domain": "security",
        "severity": "critical",
        "variables": {"d": "deployment identifier"},
        "conditions": ["deployment_ready", "security_scan_not_passed"],
        "actions": ["block_deployment", "trigger_security_scan"],
    },
    "dependency_update": {
        "name": "Critical Dependency Update Rule",
        "formula": "∀p,d: (Vulnerability(d, 'critical') → Obligatory(Update_Dependency(p, d)))",
        "description": "Critical vulnerabilities in dependencies must be updated immediately",
        "domain": "security",
        "severity": "critical",
        "variables": {
            "p": "project identifier",
            "d": "dependency identifier",
        },
        "conditions": ["vulnerability_severity == 'critical'", "dependency_not_updated"],
        "actions": ["create_update_pr", "alert_security_team"],
    },
    "test_coverage": {
        "name": "Minimum Test Coverage Rule",
        "formula": "∀pr: (Test_Coverage(pr) < 70 → Forbidden(Merge(pr)))",
        "description": (
            "Pull requests with less than 70% test coverage are forbidden from merging"
        ),
        "domain": "quality",
        "severity": "medium",
        "variables": {
            "pr": "pull request identifier",
            "70": "minimum coverage percentage",
        },
        "conditions": ["test_coverage < 70"],
        "actions": ["block_merge", "request_additional_tests"],
    },
    "log_retention": {
        "name": "Log Retention Policy Rule",
        "formula": "∀l,t: (Age(l, t) > 90_days → Permitted(Archive(l)))",
        "description": "Logs older than 90 days may be archived",
        "domain": "operations",
        "severity": "low",
        "variables": {
            "l": "log identifier",
            "t": "current timestamp",
            "90_days": "retention period",
        },
        "conditions": ["log_age > 90_days"],
        "actions": ["archive_logs", "update_index"],
    },
    "incident_escalation": {
        "name": "Incident Escalation Rule",
        "formula": "∀i,t: (Unresolved(i, t) ∧ Duration(t) > 3600 → Obligatory(Escalate(i)))",
        "description": "Unresolved incidents lasting more than 1 hour must be escalated",
        "domain": "operations",
        "severity": "high",
        "variables": {
            "i": "incident identifier",
            "t": "timestamp",
            "3600": "duration threshold (1 hour)",
        },
        "conditions": ["incident_unresolved", "duration > 3600"],
        "actions": ["escalate_incident", "notify_management"],
    },
    "gpu_provisioning": {
        "name": "GPU Provisioning Rule",
        "formula": (
            "∀w,g: (Predicted_GPU_Need(w) > Available_GPUs(g) → "
            "Obligatory(Provision_GPU(g)))"
        ),
        "description": (
            "If predicted GPU needs exceed available resources, provisioning is obligatory"
        ),
        "domain": "mlops",
        "severity": "high",
        "variables": {
            "w": "workflow identifier",
            "g": "gpu resource pool",
        },
        "conditions": ["predicted_gpu_need > available_gpus"],
        "actions": ["provision_additional_gpus", "alert_infrastructure"],
    },
}


# ---------------------------------------------------------------------------
# Business-logic helpers
# ---------------------------------------------------------------------------

def _evaluate_condition(condition: str, context: Dict[str, Any]) -> bool:
    """Evaluate a single condition string against a context dict.

    Supports ``>=``, ``>``, ``<``, ``==`` operators and bare boolean keys.
    """
    try:
        if ">=" in condition:
            var, value = condition.split(">=")
            return context.get(var.strip(), 0) >= int(value.strip())
        elif ">" in condition:
            var, value = condition.split(">")
            return context.get(var.strip(), 0) > float(value.strip())
        elif "<" in condition:
            var, value = condition.split("<")
            return context.get(var.strip(), 100) < float(value.strip())
        elif "==" in condition:
            var, value = condition.split("==")
            return str(context.get(var.strip(), "")) == value.strip().strip("'\"")
        else:
            return bool(context.get(condition.strip(), False))
    except (KeyError, ValueError, AttributeError, TypeError):
        return False


def list_software_theorems(
    domain_filter: Optional[str] = None,
    severity_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """List available software engineering theorems.

    Args:
        domain_filter:   Optional domain to filter (``devops``, ``security``, …).
        severity_filter: Optional severity to filter (``critical``, ``high``, …).

    Returns:
        Dict with ``success``, ``theorems``, ``total_count``, ``domains``,
        ``severities``.
    """
    try:
        filtered: Dict[str, Any] = {
            tid: theorem
            for tid, theorem in SOFTWARE_THEOREMS.items()
            if (domain_filter is None or theorem.get("domain") == domain_filter)
            and (severity_filter is None or theorem.get("severity") == severity_filter)
        }
        return {
            "success": True,
            "theorems": filtered,
            "total_count": len(filtered),
            "domains": list({t["domain"] for t in filtered.values()}),
            "severities": list({t["severity"] for t in filtered.values()}),
        }
    except Exception as exc:
        logger.error("Error listing software theorems: %s", exc)
        return {"success": False, "error": str(exc)}


def validate_against_theorem(
    theorem_id: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate a situation against a specific software engineering theorem.

    Args:
        theorem_id: ID of the theorem to validate against.
        context:    Dict containing contextual data for validation.

    Returns:
        Dict with ``success``, ``theorem_id``, ``theorem_applies``,
        ``conditions_met``, ``conditions_failed``, ``severity``,
        ``validated_at``, and optionally ``recommended_actions``.
    """
    try:
        if theorem_id not in SOFTWARE_THEOREMS:
            return {"success": False, "error": f"Unknown theorem ID: {theorem_id}"}

        theorem = SOFTWARE_THEOREMS[theorem_id]
        conditions_met: List[str] = []
        conditions_failed: List[str] = []

        for condition in theorem.get("conditions", []):
            (conditions_met if _evaluate_condition(condition, context) else conditions_failed).append(
                condition
            )

        theorem_applies = len(conditions_failed) == 0 and bool(conditions_met)
        result: Dict[str, Any] = {
            "success": True,
            "theorem_id": theorem_id,
            "theorem_name": theorem.get("name"),
            "formula": theorem.get("formula"),
            "theorem_applies": theorem_applies,
            "conditions_met": conditions_met,
            "conditions_failed": conditions_failed,
            "severity": theorem.get("severity"),
            "validated_at": datetime.utcnow().isoformat(),
        }
        if theorem_applies:
            result["recommended_actions"] = theorem.get("actions", [])
            result["message"] = f"Theorem '{theorem['name']}' applies — actions recommended"
        else:
            result["message"] = f"Theorem '{theorem['name']}' does not apply"

        return result
    except Exception as exc:
        logger.error("Error validating theorem: %s", exc)
        return {"success": False, "error": str(exc)}


def apply_theorem_actions(
    validation_result: Dict[str, Any],
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Apply actions recommended by theorem validation.

    Args:
        validation_result: Result from :func:`validate_against_theorem`.
        dry_run:           If ``True``, simulate actions without executing.

    Returns:
        Dict with ``success``, ``theorem_id``, ``dry_run``,
        ``actions_executed``, ``total_actions``.
    """
    try:
        if not validation_result.get("success"):
            return {"success": False, "error": "Invalid validation result"}
        if not validation_result.get("theorem_applies"):
            return {"success": True, "message": "No actions needed — theorem does not apply"}

        actions = validation_result.get("recommended_actions", [])
        results: List[Dict[str, Any]] = []
        for action in actions:
            if dry_run:
                results.append({
                    "action": action,
                    "status": "simulated",
                    "message": f"Would execute action: {action}",
                })
            else:
                results.append({
                    "action": action,
                    "status": "executed",
                    "message": f"Executed action: {action}",
                    "executed_at": datetime.utcnow().isoformat(),
                })

        return {
            "success": True,
            "theorem_id": validation_result.get("theorem_id"),
            "dry_run": dry_run,
            "actions_executed": results,
            "total_actions": len(results),
        }
    except Exception as exc:
        logger.error("Error applying theorem actions: %s", exc)
        return {"success": False, "error": str(exc)}


__all__ = [
    "SOFTWARE_THEOREMS",
    "list_software_theorems",
    "validate_against_theorem",
    "_evaluate_condition",
    "apply_theorem_actions",
]
