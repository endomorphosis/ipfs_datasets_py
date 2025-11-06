"""
Auto-Healing Coordinator for Software Engineering Dashboard.

This module provides coordination for auto-healing workflows based on detected errors.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def coordinate_auto_healing(
    error_report: Dict[str, Any],
    healing_strategies: Optional[List[Dict[str, Any]]] = None,
    dry_run: bool = True
) -> Dict[str, Any]:
    """
    Coordinate auto-healing workflows based on detected errors.
    
    Analyzes error reports and coordinates appropriate auto-healing actions,
    such as service restarts, resource scaling, or configuration updates.
    
    Args:
        error_report: Error report from error_pattern_detector
        healing_strategies: List of available healing strategies
        dry_run: If True, only simulate actions without executing
        
    Returns:
        Dictionary containing healing plan with keys:
        - healing_actions: List of planned healing actions
        - executed: Whether actions were executed or simulated
        - results: Results of healing attempts
        - recommendations: Manual intervention recommendations
        
    Example:
        >>> error_report = detect_error_patterns(logs)
        >>> healing = coordinate_auto_healing(error_report)
        >>> print(f"Planned {len(healing['healing_actions'])} healing actions")
    """
    try:
        result = {
            "success": True,
            "healing_actions": [],
            "executed": not dry_run,
            "results": [],
            "recommendations": [],
            "coordinated_at": datetime.utcnow().isoformat()
        }
        
        if not error_report.get("success"):
            return {
                "success": False,
                "error": "Invalid error report provided"
            }
        
        # Default healing strategies
        if healing_strategies is None:
            healing_strategies = [
                {
                    "pattern": "connection_timeout",
                    "action": "retry_with_backoff",
                    "auto_healable": True,
                    "max_retries": 3
                },
                {
                    "pattern": "out_of_memory",
                    "action": "restart_service",
                    "auto_healable": True,
                    "escalate_if_failed": True
                },
                {
                    "pattern": "permission_denied",
                    "action": "fix_permissions",
                    "auto_healable": True,
                    "requires_sudo": True
                },
                {
                    "pattern": "api_rate_limit",
                    "action": "throttle_requests",
                    "auto_healable": True,
                    "backoff_seconds": 60
                },
                {
                    "pattern": "disk_full",
                    "action": "cleanup_temp_files",
                    "auto_healable": True,
                    "min_space_gb": 10
                }
            ]
        
        # Match detected patterns with healing strategies
        detected_patterns = error_report.get("patterns", [])
        
        for pattern_info in detected_patterns:
            pattern_name = pattern_info.get("pattern")
            occurrences = pattern_info.get("occurrences", 0)
            
            # Find matching strategy
            strategy = next(
                (s for s in healing_strategies if s["pattern"] == pattern_name),
                None
            )
            
            if strategy and strategy.get("auto_healable"):
                action = {
                    "pattern": pattern_name,
                    "action_type": strategy["action"],
                    "occurrences": occurrences,
                    "priority": "high" if occurrences > 10 else "medium",
                    "parameters": {k: v for k, v in strategy.items() if k not in ["pattern", "action", "auto_healable"]}
                }
                
                result["healing_actions"].append(action)
                
                # Simulate or execute action
                if dry_run:
                    result["results"].append({
                        "action": strategy["action"],
                        "status": "simulated",
                        "message": f"Would execute {strategy['action']} for {pattern_name}"
                    })
                else:
                    # In real implementation, would execute the actual healing action
                    execution_result = _execute_healing_action(action)
                    result["results"].append(execution_result)
            else:
                # Pattern requires manual intervention
                result["recommendations"].append({
                    "pattern": pattern_name,
                    "severity": "high" if occurrences > 10 else "medium",
                    "message": f"Manual intervention required for {pattern_name}",
                    "occurrences": occurrences
                })
        
        if not result["healing_actions"]:
            result["recommendations"].append({
                "message": "No auto-healable patterns detected",
                "action": "Manual investigation recommended"
            })
        
        return result
        
    except Exception as e:
        logger.error(f"Error coordinating auto-healing: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def _execute_healing_action(action: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a specific healing action."""
    action_type = action.get("action_type")
    
    # In a real implementation, this would execute actual healing actions
    # For now, we return a simulated result
    return {
        "action": action_type,
        "status": "success",
        "message": f"Executed {action_type}",
        "executed_at": datetime.utcnow().isoformat()
    }


def monitor_healing_effectiveness(
    healing_history: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Monitor the effectiveness of auto-healing actions.
    
    Analyzes the history of healing actions to determine their effectiveness
    and suggest improvements to healing strategies.
    
    Args:
        healing_history: List of past healing action results
        
    Returns:
        Dictionary containing effectiveness analysis
        
    Example:
        >>> history = [{"action": "restart_service", "status": "success"}, ...]
        >>> effectiveness = monitor_healing_effectiveness(history)
        >>> print(f"Success rate: {effectiveness['success_rate']}%")
    """
    try:
        if not healing_history:
            return {
                "success": False,
                "error": "No healing history provided"
            }
        
        total_actions = len(healing_history)
        successful_actions = len([h for h in healing_history if h.get("status") == "success"])
        
        success_rate = (successful_actions / total_actions * 100) if total_actions > 0 else 0
        
        # Analyze by action type
        action_stats = {}
        for action in healing_history:
            action_type = action.get("action")
            if action_type not in action_stats:
                action_stats[action_type] = {"total": 0, "success": 0}
            
            action_stats[action_type]["total"] += 1
            if action.get("status") == "success":
                action_stats[action_type]["success"] += 1
        
        # Calculate success rates per action
        for action_type, stats in action_stats.items():
            stats["success_rate"] = (stats["success"] / stats["total"] * 100) if stats["total"] > 0 else 0
        
        recommendations = []
        for action_type, stats in action_stats.items():
            if stats["success_rate"] < 70:
                recommendations.append({
                    "action": action_type,
                    "issue": f"Low success rate ({stats['success_rate']:.1f}%)",
                    "recommendation": "Review and improve healing strategy"
                })
        
        return {
            "success": True,
            "overall_success_rate": round(success_rate, 2),
            "total_healing_actions": total_actions,
            "successful_actions": successful_actions,
            "action_statistics": action_stats,
            "recommendations": recommendations,
            "analyzed_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error monitoring healing effectiveness: {e}")
        return {
            "success": False,
            "error": str(e)
        }
