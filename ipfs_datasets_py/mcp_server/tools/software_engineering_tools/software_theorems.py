"""
Software Engineering Theorems for Temporal Deontic Logic.

This module defines software engineering theorems and rules using temporal deontic logic
for reasoning about software systems, development practices, and operational patterns.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Software Engineering Theorems using Temporal Deontic Logic
SOFTWARE_THEOREMS = {
    "ci_failure_notification": {
        "name": "CI Failure Notification Rule",
        "formula": "∀t,p: (CI_Failed(p, t, 3) → Obligatory(Notify_Team(p, t)))",
        "description": "If CI fails 3 times for a project, it is obligatory to notify the team",
        "domain": "devops",
        "severity": "high",
        "variables": {
            "p": "project identifier",
            "t": "timestamp",
            "3": "failure threshold"
        },
        "conditions": [
            "ci_failed_count >= 3",
            "notification_not_sent"
        ],
        "actions": [
            "send_team_notification",
            "create_incident"
        ]
    },
    
    "deployment_rollback": {
        "name": "Automatic Deployment Rollback Rule",
        "formula": "∀d,t: (Error_Rate(d, t) > 0.05 ∧ Duration(t) > 300 → Obligatory(Rollback(d, t)))",
        "description": "If error rate exceeds 5% for more than 5 minutes after deployment, rollback is obligatory",
        "domain": "devops",
        "severity": "critical",
        "variables": {
            "d": "deployment identifier",
            "t": "timestamp",
            "0.05": "error rate threshold (5%)",
            "300": "duration threshold in seconds"
        },
        "conditions": [
            "error_rate > 0.05",
            "duration > 300"
        ],
        "actions": [
            "trigger_rollback",
            "alert_operations_team"
        ]
    },
    
    "code_review_requirement": {
        "name": "Code Review Requirement Rule",
        "formula": "∀pr,l: (Changed_Lines(pr) > l → Obligatory(Min_Reviews(pr, 2)))",
        "description": "Pull requests with more than threshold changed lines require at least 2 reviews",
        "domain": "development",
        "severity": "medium",
        "variables": {
            "pr": "pull request identifier",
            "l": "line count threshold (default: 500)",
            "2": "minimum required reviews"
        },
        "conditions": [
            "changed_lines > threshold",
            "review_count < 2"
        ],
        "actions": [
            "request_additional_review",
            "block_merge"
        ]
    },
    
    "resource_scaling": {
        "name": "Automatic Resource Scaling Rule",
        "formula": "∀s,t: (CPU_Usage(s, t) > 80 ∧ Duration(t) > 300 → Obligatory(Scale_Up(s)))",
        "description": "If CPU usage exceeds 80% for more than 5 minutes, scaling up is obligatory",
        "domain": "infrastructure",
        "severity": "high",
        "variables": {
            "s": "service identifier",
            "t": "timestamp",
            "80": "CPU usage threshold (%)",
            "300": "duration threshold in seconds"
        },
        "conditions": [
            "cpu_usage > 80",
            "duration > 300"
        ],
        "actions": [
            "scale_up_service",
            "alert_infrastructure_team"
        ]
    },
    
    "security_scan_requirement": {
        "name": "Security Scan Before Deploy Rule",
        "formula": "∀d: (Ready_To_Deploy(d) → Obligatory(Security_Scan_Passed(d)))",
        "description": "All deployments must pass security scanning before being deployed",
        "domain": "security",
        "severity": "critical",
        "variables": {
            "d": "deployment identifier"
        },
        "conditions": [
            "deployment_ready",
            "security_scan_not_passed"
        ],
        "actions": [
            "block_deployment",
            "trigger_security_scan"
        ]
    },
    
    "dependency_update": {
        "name": "Critical Dependency Update Rule",
        "formula": "∀p,d: (Vulnerability(d, 'critical') → Obligatory(Update_Dependency(p, d)))",
        "description": "Critical vulnerabilities in dependencies must be updated immediately",
        "domain": "security",
        "severity": "critical",
        "variables": {
            "p": "project identifier",
            "d": "dependency identifier"
        },
        "conditions": [
            "vulnerability_severity == 'critical'",
            "dependency_not_updated"
        ],
        "actions": [
            "create_update_pr",
            "alert_security_team"
        ]
    },
    
    "test_coverage": {
        "name": "Minimum Test Coverage Rule",
        "formula": "∀pr: (Test_Coverage(pr) < 70 → Forbidden(Merge(pr)))",
        "description": "Pull requests with less than 70% test coverage are forbidden from merging",
        "domain": "quality",
        "severity": "medium",
        "variables": {
            "pr": "pull request identifier",
            "70": "minimum coverage percentage"
        },
        "conditions": [
            "test_coverage < 70"
        ],
        "actions": [
            "block_merge",
            "request_additional_tests"
        ]
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
            "90_days": "retention period"
        },
        "conditions": [
            "log_age > 90_days"
        ],
        "actions": [
            "archive_logs",
            "update_index"
        ]
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
            "3600": "duration threshold (1 hour)"
        },
        "conditions": [
            "incident_unresolved",
            "duration > 3600"
        ],
        "actions": [
            "escalate_incident",
            "notify_management"
        ]
    },
    
    "gpu_provisioning": {
        "name": "GPU Provisioning Rule",
        "formula": "∀w,g: (Predicted_GPU_Need(w) > Available_GPUs(g) → Obligatory(Provision_GPU(g)))",
        "description": "If predicted GPU needs exceed available resources, provisioning is obligatory",
        "domain": "mlops",
        "severity": "high",
        "variables": {
            "w": "workflow identifier",
            "g": "gpu resource pool"
        },
        "conditions": [
            "predicted_gpu_need > available_gpus"
        ],
        "actions": [
            "provision_additional_gpus",
            "alert_infrastructure"
        ]
    }
}


def list_software_theorems(
    domain_filter: Optional[str] = None,
    severity_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    List available software engineering theorems.
    
    Returns a list of predefined software engineering theorems that can be
    applied to validate software systems and operations.
    
    Args:
        domain_filter: Optional domain to filter theorems (devops, security, quality, etc.)
        severity_filter: Optional severity to filter theorems (critical, high, medium, low)
        
    Returns:
        Dictionary containing list of theorems
        
    Example:
        >>> theorems = list_software_theorems(domain_filter="devops")
        >>> print(f"Found {len(theorems['theorems'])} devops theorems")
    """
    try:
        filtered_theorems = {}
        
        for theorem_id, theorem in SOFTWARE_THEOREMS.items():
            # Apply filters
            if domain_filter and theorem.get("domain") != domain_filter:
                continue
            if severity_filter and theorem.get("severity") != severity_filter:
                continue
            
            filtered_theorems[theorem_id] = theorem
        
        return {
            "success": True,
            "theorems": filtered_theorems,
            "total_count": len(filtered_theorems),
            "domains": list(set(t["domain"] for t in filtered_theorems.values())),
            "severities": list(set(t["severity"] for t in filtered_theorems.values()))
        }
        
    except Exception as e:
        logger.error(f"Error listing software theorems: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def validate_against_theorem(
    theorem_id: str,
    context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Validate a situation against a specific software engineering theorem.
    
    Checks whether the given context satisfies or violates the specified theorem,
    and recommends actions if needed.
    
    Args:
        theorem_id: ID of the theorem to validate against
        context: Dictionary containing contextual data for validation
            
    Returns:
        Dictionary containing validation result
        
    Example:
        >>> context = {"ci_failed_count": 5, "notification_sent": False}
        >>> result = validate_against_theorem("ci_failure_notification", context)
        >>> print(f"Validation: {result['validation_result']}")
    """
    try:
        if theorem_id not in SOFTWARE_THEOREMS:
            return {
                "success": False,
                "error": f"Unknown theorem ID: {theorem_id}"
            }
        
        theorem = SOFTWARE_THEOREMS[theorem_id]
        
        # Check conditions
        conditions_met = []
        conditions_failed = []
        
        for condition in theorem.get("conditions", []):
            # Simple evaluation (in real implementation, would use proper logic engine)
            if _evaluate_condition(condition, context):
                conditions_met.append(condition)
            else:
                conditions_failed.append(condition)
        
        # Determine if theorem applies
        theorem_applies = len(conditions_met) == len(theorem.get("conditions", []))
        
        result = {
            "success": True,
            "theorem_id": theorem_id,
            "theorem_name": theorem.get("name"),
            "formula": theorem.get("formula"),
            "theorem_applies": theorem_applies,
            "conditions_met": conditions_met,
            "conditions_failed": conditions_failed,
            "severity": theorem.get("severity"),
            "validated_at": datetime.utcnow().isoformat()
        }
        
        if theorem_applies:
            result["recommended_actions"] = theorem.get("actions", [])
            result["message"] = f"Theorem '{theorem['name']}' applies - actions recommended"
        else:
            result["message"] = f"Theorem '{theorem['name']}' does not apply"
        
        return result
        
    except Exception as e:
        logger.error(f"Error validating theorem: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def _evaluate_condition(condition: str, context: Dict[str, Any]) -> bool:
    """Evaluate a condition against context (simplified implementation)."""
    try:
        # Simple condition evaluation
        # In real implementation, would use proper expression parser
        
        if ">=" in condition:
            var, value = condition.split(">=")
            var = var.strip()
            value = value.strip()
            return context.get(var, 0) >= int(value)
        elif ">" in condition:
            var, value = condition.split(">")
            var = var.strip()
            value = value.strip()
            return context.get(var, 0) > float(value)
        elif "<" in condition:
            var, value = condition.split("<")
            var = var.strip()
            value = value.strip()
            return context.get(var, 100) < float(value)
        elif "==" in condition:
            var, value = condition.split("==")
            var = var.strip()
            value = value.strip().strip("'\"")
            return str(context.get(var, "")) == value
        else:
            # For simple boolean conditions
            return context.get(condition.strip(), False)
    except:
        return False


def apply_theorem_actions(
    validation_result: Dict[str, Any],
    dry_run: bool = True
) -> Dict[str, Any]:
    """
    Apply actions recommended by theorem validation.
    
    Executes or simulates the actions recommended by a theorem validation.
    
    Args:
        validation_result: Result from validate_against_theorem
        dry_run: If True, simulate actions without executing
        
    Returns:
        Dictionary containing action execution results
        
    Example:
        >>> validation = validate_against_theorem("ci_failure_notification", context)
        >>> if validation["theorem_applies"]:
        ...     result = apply_theorem_actions(validation, dry_run=True)
    """
    try:
        if not validation_result.get("success"):
            return {
                "success": False,
                "error": "Invalid validation result"
            }
        
        if not validation_result.get("theorem_applies"):
            return {
                "success": True,
                "message": "No actions needed - theorem does not apply"
            }
        
        actions = validation_result.get("recommended_actions", [])
        
        results = []
        for action in actions:
            if dry_run:
                results.append({
                    "action": action,
                    "status": "simulated",
                    "message": f"Would execute action: {action}"
                })
            else:
                # In real implementation, would execute actual actions
                results.append({
                    "action": action,
                    "status": "executed",
                    "message": f"Executed action: {action}",
                    "executed_at": datetime.utcnow().isoformat()
                })
        
        return {
            "success": True,
            "theorem_id": validation_result.get("theorem_id"),
            "dry_run": dry_run,
            "actions_executed": results,
            "total_actions": len(results)
        }
        
    except Exception as e:
        logger.error(f"Error applying theorem actions: {e}")
        return {
            "success": False,
            "error": str(e)
        }
