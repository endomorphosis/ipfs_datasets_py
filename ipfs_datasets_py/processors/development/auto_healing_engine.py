"""
Auto-Healing Coordination Engine — canonical package module.

Business logic extracted from mcp_server/tools/software_engineering_tools/auto_healing_coordinator.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_HEALING_STRATEGIES: List[Dict[str, Any]] = [
    {"pattern": "connection_timeout", "action": "retry_with_backoff", "auto_healable": True, "max_retries": 3},
    {"pattern": "out_of_memory", "action": "restart_service", "auto_healable": True, "escalate_if_failed": True},
    {"pattern": "permission_denied", "action": "fix_permissions", "auto_healable": True, "requires_sudo": True},
    {"pattern": "api_rate_limit", "action": "throttle_requests", "auto_healable": True, "backoff_seconds": 60},
    {"pattern": "disk_full", "action": "cleanup_temp_files", "auto_healable": True, "min_space_gb": 10},
]


def coordinate_auto_healing(
    error_report: Dict[str, Any],
    healing_strategies: Optional[List[Dict[str, Any]]] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Coordinate auto-healing workflows based on detected errors."""
    try:
        if not error_report.get("success"):
            return {"success": False, "error": "Invalid error report provided"}

        strategies = healing_strategies if healing_strategies is not None else _DEFAULT_HEALING_STRATEGIES

        result: Dict[str, Any] = {
            "success": True,
            "healing_actions": [],
            "executed": not dry_run,
            "results": [],
            "recommendations": [],
            "coordinated_at": datetime.now(timezone.utc).isoformat(),
        }

        for pattern_info in error_report.get("patterns", []):
            pattern_name = pattern_info.get("pattern")
            occurrences = pattern_info.get("occurrences", 0)

            strategy = next(
                (s for s in strategies if s["pattern"] == pattern_name), None
            )

            if strategy and strategy.get("auto_healable"):
                action: Dict[str, Any] = {
                    "pattern": pattern_name,
                    "action_type": strategy["action"],
                    "occurrences": occurrences,
                    "priority": "high" if occurrences > 10 else "medium",
                    "parameters": {
                        k: v for k, v in strategy.items()
                        if k not in ("pattern", "action", "auto_healable")
                    },
                }
                result["healing_actions"].append(action)

                if dry_run:
                    result["results"].append({
                        "action": strategy["action"],
                        "status": "simulated",
                        "message": f"Would execute {strategy['action']} for {pattern_name}",
                    })
                else:
                    result["results"].append(_execute_healing_action(action))
            else:
                result["recommendations"].append({
                    "pattern": pattern_name,
                    "severity": "high" if occurrences > 10 else "medium",
                    "message": f"Manual intervention required for {pattern_name}",
                    "occurrences": occurrences,
                })

        if not result["healing_actions"]:
            result["recommendations"].append({
                "message": "No auto-healable patterns detected",
                "action": "Manual investigation recommended",
            })

        return result

    except Exception as e:
        logger.error("Error coordinating auto-healing: %s", e)
        return {"success": False, "error": str(e)}


def monitor_healing_effectiveness(healing_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Monitor the effectiveness of auto-healing actions."""
    try:
        if not healing_history:
            return {"success": False, "error": "No healing history provided"}

        total = len(healing_history)
        successful = sum(1 for h in healing_history if h.get("status") == "success")
        success_rate = (successful / total * 100) if total else 0

        action_stats: Dict[str, Dict[str, Any]] = {}
        for h in healing_history:
            at = h.get("action", "unknown")
            stats = action_stats.setdefault(at, {"total": 0, "success": 0})
            stats["total"] += 1
            if h.get("status") == "success":
                stats["success"] += 1

        for stats in action_stats.values():
            stats["success_rate"] = (
                stats["success"] / stats["total"] * 100 if stats["total"] else 0
            )

        recommendations = [
            {
                "action": at,
                "issue": f"Low success rate ({stats['success_rate']:.1f}%)",
                "recommendation": "Review and improve healing strategy",
            }
            for at, stats in action_stats.items()
            if stats["success_rate"] < 70
        ]

        return {
            "success": True,
            "overall_success_rate": round(success_rate, 2),
            "total_healing_actions": total,
            "successful_actions": successful,
            "action_statistics": action_stats,
            "recommendations": recommendations,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error("Error monitoring healing effectiveness: %s", e)
        return {"success": False, "error": str(e)}


def _execute_healing_action(action: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a specific healing action (stub — replace with real implementation)."""
    return {
        "action": action.get("action_type"),
        "status": "success",
        "message": f"Executed {action.get('action_type')}",
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }
