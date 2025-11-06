"""
Kubernetes Log Analyzer for Software Engineering Dashboard.

This module provides tools to parse and analyze Kubernetes cluster logs.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from collections import Counter

logger = logging.getLogger(__name__)


def parse_kubernetes_logs(
    log_content: str,
    namespace_filter: Optional[str] = None,
    pod_filter: Optional[str] = None,
    severity_filter: Optional[str] = None,
    max_entries: int = 1000
) -> Dict[str, Any]:
    """
    Parse Kubernetes logs and extract structured information.
    
    Analyzes Kubernetes logs to identify pod issues, deployment problems,
    and cluster health indicators.
    
    Args:
        log_content: Raw Kubernetes log content (from kubectl logs output)
        namespace_filter: Optional namespace to filter logs
        pod_filter: Optional pod name pattern to filter logs
        severity_filter: Optional severity level (ERROR, WARN, INFO, DEBUG)
        max_entries: Maximum number of log entries to process
        
    Returns:
        Dictionary containing parsed log information with keys:
        - entries: List of parsed log entries
        - statistics: Log statistics by namespace, pod, and severity
        - errors: Detected error patterns
        - recommendations: Cluster health recommendations
        - analyzed_at: Timestamp of analysis
        
    Example:
        >>> logs = subprocess.check_output(['kubectl', 'logs', '-n', 'default', '--all-containers=true'])
        >>> result = parse_kubernetes_logs(logs.decode(), namespace_filter='default')
        >>> print(f"Found {len(result['entries'])} entries")
    """
    try:
        result = {
            "success": True,
            "entries": [],
            "statistics": {
                "total_entries": 0,
                "by_severity": {},
                "by_namespace": {},
                "by_pod": {},
                "by_container": {}
            },
            "errors": [],
            "recommendations": [],
            "analyzed_at": datetime.utcnow().isoformat()
        }
        
        lines = log_content.split('\n')[:max_entries]
        
        # Common Kubernetes log patterns
        # Format varies but often includes: timestamp level [component] message
        k8s_pattern = r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)\s+(\w+)\s+(?:\[([^\]]+)\])?\s*(.+)'
        simple_pattern = r'(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s+(\w+):\s+(.+)'
        
        for line in lines:
            if not line.strip():
                continue
            
            entry = None
            
            # Try Kubernetes format
            match = re.match(k8s_pattern, line)
            if match:
                timestamp, severity, component, message = match.groups()
                entry = {
                    "timestamp": timestamp,
                    "severity": severity.upper(),
                    "component": component or "unknown",
                    "message": message.strip()
                }
            else:
                # Try simpler format
                match = re.match(simple_pattern, line)
                if match:
                    timestamp, severity, message = match.groups()
                    entry = {
                        "timestamp": timestamp,
                        "severity": severity.upper(),
                        "component": "unknown",
                        "message": message.strip()
                    }
            
            if not entry:
                # Try to extract any severity indicator
                for sev in ['ERROR', 'WARN', 'INFO', 'DEBUG', 'FATAL']:
                    if sev in line.upper():
                        entry = {
                            "timestamp": "unknown",
                            "severity": sev,
                            "component": "unknown",
                            "message": line.strip()
                        }
                        break
            
            if not entry:
                # Default entry for unparsed lines
                entry = {
                    "timestamp": "unknown",
                    "severity": "INFO",
                    "component": "unknown",
                    "message": line.strip()
                }
            
            # Extract namespace and pod from message if available
            namespace = "unknown"
            pod = "unknown"
            
            ns_match = re.search(r'namespace[=:\s]+([a-z0-9-]+)', entry["message"], re.IGNORECASE)
            if ns_match:
                namespace = ns_match.group(1)
            
            pod_match = re.search(r'pod[=:\s]+([a-z0-9-]+)', entry["message"], re.IGNORECASE)
            if pod_match:
                pod = pod_match.group(1)
            
            entry["namespace"] = namespace
            entry["pod"] = pod
            
            # Apply filters
            if namespace_filter and namespace_filter.lower() not in namespace.lower():
                continue
            
            if pod_filter and pod_filter.lower() not in pod.lower():
                continue
            
            if severity_filter and entry["severity"] != severity_filter.upper():
                continue
            
            result["entries"].append(entry)
            result["statistics"]["total_entries"] += 1
            
            # Update statistics
            severity = entry["severity"]
            result["statistics"]["by_severity"][severity] = \
                result["statistics"]["by_severity"].get(severity, 0) + 1
            
            result["statistics"]["by_namespace"][namespace] = \
                result["statistics"]["by_namespace"].get(namespace, 0) + 1
            
            result["statistics"]["by_pod"][pod] = \
                result["statistics"]["by_pod"].get(pod, 0) + 1
            
            # Detect errors
            if severity in ['ERROR', 'FATAL', 'CRITICAL']:
                result["errors"].append({
                    "namespace": namespace,
                    "pod": pod,
                    "severity": severity,
                    "message": entry["message"][:200],
                    "timestamp": entry["timestamp"]
                })
        
        # Generate recommendations
        error_count = result["statistics"]["by_severity"].get("ERROR", 0)
        fatal_count = result["statistics"]["by_severity"].get("FATAL", 0)
        
        if error_count + fatal_count > 50:
            result["recommendations"].append({
                "severity": "high",
                "message": f"High number of error/fatal entries ({error_count + fatal_count}) detected",
                "action": "Investigate pod and deployment issues"
            })
        
        # Check for pod-specific issues
        pod_errors = Counter()
        for error in result["errors"]:
            if error["pod"] != "unknown":
                pod_errors[error["pod"]] += 1
        
        for pod, count in pod_errors.most_common(3):
            if count > 10:
                result["recommendations"].append({
                    "severity": "medium",
                    "message": f"Pod '{pod}' has {count} error entries",
                    "action": f"Check pod '{pod}' status and describe for details"
                })
        
        # Check for common Kubernetes issues
        for entry in result["entries"]:
            msg_lower = entry["message"].lower()
            if "oomkilled" in msg_lower or "out of memory" in msg_lower:
                result["recommendations"].append({
                    "severity": "high",
                    "message": "OOMKilled detected - pods running out of memory",
                    "action": "Increase memory limits or optimize application memory usage"
                })
                break
        
        for entry in result["entries"]:
            msg_lower = entry["message"].lower()
            if "crashloopbackoff" in msg_lower:
                result["recommendations"].append({
                    "severity": "high",
                    "message": "CrashLoopBackOff detected - pods failing to start",
                    "action": "Check pod logs and configuration"
                })
                break
        
        return result
        
    except Exception as e:
        logger.error(f"Error parsing Kubernetes logs: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def analyze_pod_health(log_data: Dict[str, Any], pod_name: str) -> Dict[str, Any]:
    """
    Analyze the health of a specific Kubernetes pod from parsed logs.
    
    Provides detailed health analysis for a specific pod including
    error rates, restart patterns, and resource issues.
    
    Args:
        log_data: Parsed log data from parse_kubernetes_logs
        pod_name: Name of the pod to analyze
        
    Returns:
        Dictionary containing pod health analysis
        
    Example:
        >>> log_data = parse_kubernetes_logs(logs)
        >>> health = analyze_pod_health(log_data, 'my-app-pod-123')
        >>> print(f"Health score: {health['health_score']}")
    """
    try:
        if not log_data.get("success"):
            return {
                "success": False,
                "error": "Invalid log data provided"
            }
        
        pod_entries = [
            entry for entry in log_data.get("entries", [])
            if pod_name.lower() in entry.get("pod", "").lower()
        ]
        
        if not pod_entries:
            return {
                "success": False,
                "error": f"No entries found for pod '{pod_name}'"
            }
        
        # Calculate metrics
        total_entries = len(pod_entries)
        error_entries = len([e for e in pod_entries if e.get("severity") in ['ERROR', 'FATAL', 'CRITICAL']])
        error_rate = (error_entries / total_entries * 100) if total_entries > 0 else 0
        
        # Calculate health score (0-100)
        health_score = 100 - min(error_rate * 2, 100)
        
        # Determine health status
        if health_score >= 90:
            health_status = "healthy"
        elif health_score >= 70:
            health_status = "warning"
        else:
            health_status = "critical"
        
        # Check for specific issues
        issues = []
        for entry in pod_entries:
            msg_lower = entry.get("message", "").lower()
            if "oomkilled" in msg_lower:
                issues.append("OOM (Out of Memory)")
            if "crashloopbackoff" in msg_lower:
                issues.append("CrashLoopBackOff")
            if "imagepullbackoff" in msg_lower:
                issues.append("ImagePullBackOff")
            if "readiness probe failed" in msg_lower:
                issues.append("Readiness probe failed")
        
        return {
            "success": True,
            "pod": pod_name,
            "health_score": round(health_score, 2),
            "health_status": health_status,
            "metrics": {
                "total_entries": total_entries,
                "error_entries": error_entries,
                "error_rate": round(error_rate, 2)
            },
            "issues": list(set(issues)),
            "recent_errors": [
                {
                    "timestamp": e.get("timestamp"),
                    "severity": e.get("severity"),
                    "message": e.get("message", "")[:100]
                }
                for e in pod_entries
                if e.get("severity") in ['ERROR', 'FATAL', 'CRITICAL']
            ][:5],
            "analyzed_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error analyzing pod health: {e}")
        return {
            "success": False,
            "error": str(e)
        }
