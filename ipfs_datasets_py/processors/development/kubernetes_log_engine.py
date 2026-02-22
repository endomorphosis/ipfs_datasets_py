"""
Kubernetes Log Analysis Engine — canonical package module.

Business logic extracted from mcp_server/tools/software_engineering_tools/kubernetes_log_analyzer.py.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_K8S_PATTERN = r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)\s+(\w+)\s+(?:\[([^\]]+)\])?\s*(.+)"
_SIMPLE_PATTERN = r"(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s+(\w+):\s+(.+)"


def parse_kubernetes_logs(
    log_content: str,
    namespace_filter: Optional[str] = None,
    pod_filter: Optional[str] = None,
    severity_filter: Optional[str] = None,
    max_entries: int = 1000,
) -> Dict[str, Any]:
    """Parse Kubernetes logs and extract structured information."""
    try:
        result: Dict[str, Any] = {
            "success": True,
            "entries": [],
            "statistics": {
                "total_entries": 0,
                "by_severity": {},
                "by_namespace": {},
                "by_pod": {},
                "by_container": {},
            },
            "errors": [],
            "recommendations": [],
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

        for line in log_content.split("\n")[:max_entries]:
            if not line.strip():
                continue

            entry: Optional[Dict[str, Any]] = None
            m = re.match(_K8S_PATTERN, line)
            if m:
                timestamp, severity, component, message = m.groups()
                entry = {
                    "timestamp": timestamp,
                    "severity": severity.upper(),
                    "component": component or "unknown",
                    "message": message.strip(),
                }
            else:
                m = re.match(_SIMPLE_PATTERN, line)
                if m:
                    timestamp, severity, message = m.groups()
                    entry = {
                        "timestamp": timestamp,
                        "severity": severity.upper(),
                        "component": "unknown",
                        "message": message.strip(),
                    }

            if not entry:
                for sev in ("ERROR", "WARN", "INFO", "DEBUG", "FATAL"):
                    if sev in line.upper():
                        entry = {
                            "timestamp": "unknown",
                            "severity": sev,
                            "component": "unknown",
                            "message": line.strip(),
                        }
                        break
            if not entry:
                entry = {
                    "timestamp": "unknown",
                    "severity": "INFO",
                    "component": "unknown",
                    "message": line.strip(),
                }

            namespace = "unknown"
            pod = "unknown"
            ns_m = re.search(r"namespace[=:\s]+([a-z0-9-]+)", entry["message"], re.I)
            if ns_m:
                namespace = ns_m.group(1)
            pod_m = re.search(r"pod[=:\s]+([a-z0-9-]+)", entry["message"], re.I)
            if pod_m:
                pod = pod_m.group(1)

            entry["namespace"] = namespace
            entry["pod"] = pod

            if namespace_filter and namespace_filter.lower() not in namespace.lower():
                continue
            if pod_filter and pod_filter.lower() not in pod.lower():
                continue
            if severity_filter and entry["severity"] != severity_filter.upper():
                continue

            result["entries"].append(entry)
            result["statistics"]["total_entries"] += 1
            sev = entry["severity"]
            result["statistics"]["by_severity"][sev] = (
                result["statistics"]["by_severity"].get(sev, 0) + 1
            )
            result["statistics"]["by_namespace"][namespace] = (
                result["statistics"]["by_namespace"].get(namespace, 0) + 1
            )
            result["statistics"]["by_pod"][pod] = (
                result["statistics"]["by_pod"].get(pod, 0) + 1
            )
            if sev in ("ERROR", "FATAL", "CRITICAL"):
                result["errors"].append({
                    "namespace": namespace,
                    "pod": pod,
                    "severity": sev,
                    "message": entry["message"][:200],
                    "timestamp": entry["timestamp"],
                })

        error_count = result["statistics"]["by_severity"].get("ERROR", 0)
        fatal_count = result["statistics"]["by_severity"].get("FATAL", 0)
        if error_count + fatal_count > 50:
            result["recommendations"].append({
                "severity": "high",
                "message": (
                    f"High number of error/fatal entries ({error_count + fatal_count}) detected"
                ),
                "action": "Investigate pod and deployment issues",
            })

        pod_errors: Counter = Counter()
        for err in result["errors"]:
            if err["pod"] != "unknown":
                pod_errors[err["pod"]] += 1
        for pod, count in pod_errors.most_common(3):
            if count > 10:
                result["recommendations"].append({
                    "severity": "medium",
                    "message": f"Pod '{pod}' has {count} error entries",
                    "action": f"Check pod '{pod}' status and describe for details",
                })

        msgs = [e["message"].lower() for e in result["entries"]]
        if any("oomkilled" in m or "out of memory" in m for m in msgs):
            result["recommendations"].append({
                "severity": "high",
                "message": "OOMKilled detected - pods running out of memory",
                "action": "Increase memory limits or optimize application memory usage",
            })
        if any("crashloopbackoff" in m for m in msgs):
            result["recommendations"].append({
                "severity": "high",
                "message": "CrashLoopBackOff detected - pods failing to start",
                "action": "Check pod logs and configuration",
            })

        return result

    except Exception as e:
        logger.error("Error parsing Kubernetes logs: %s", e)
        return {"success": False, "error": str(e)}


def analyze_pod_health(log_data: Dict[str, Any], pod_name: str) -> Dict[str, Any]:
    """Analyze the health of a specific Kubernetes pod from parsed logs."""
    try:
        if not log_data.get("success"):
            return {"success": False, "error": "Invalid log data provided"}

        pod_entries = [
            e for e in log_data.get("entries", [])
            if pod_name.lower() in e.get("pod", "").lower()
        ]
        if not pod_entries:
            return {"success": False, "error": f"No entries found for pod '{pod_name}'"}

        total = len(pod_entries)
        errors = len([e for e in pod_entries if e.get("severity") in ("ERROR", "FATAL", "CRITICAL")])
        error_rate = (errors / total * 100) if total else 0
        health_score = 100 - min(error_rate * 2, 100)

        if health_score >= 90:
            health_status = "healthy"
        elif health_score >= 70:
            health_status = "warning"
        else:
            health_status = "critical"

        issues: List[str] = []
        for e in pod_entries:
            m = e.get("message", "").lower()
            if "oomkilled" in m:
                issues.append("OOM (Out of Memory)")
            if "crashloopbackoff" in m:
                issues.append("CrashLoopBackOff")
            if "imagepullbackoff" in m:
                issues.append("ImagePullBackOff")
            if "readiness probe failed" in m:
                issues.append("Readiness probe failed")

        return {
            "success": True,
            "pod": pod_name,
            "health_score": round(health_score, 2),
            "health_status": health_status,
            "metrics": {
                "total_entries": total,
                "error_entries": errors,
                "error_rate": round(error_rate, 2),
            },
            "issues": list(set(issues)),
            "recent_errors": [
                {
                    "timestamp": e.get("timestamp"),
                    "severity": e.get("severity"),
                    "message": e.get("message", "")[:100],
                }
                for e in pod_entries
                if e.get("severity") in ("ERROR", "FATAL", "CRITICAL")
            ][:5],
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error("Error analyzing pod health: %s", e)
        return {"success": False, "error": str(e)}
