"""
Systemd Log Parsing Engine — canonical package module.

Business logic extracted from mcp_server/tools/software_engineering_tools/systemd_log_parser.py.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SYSTEMD_PATTERN = r"(\w+\s+\d+\s+\d+:\d+:\d+)\s+(\S+)\s+(\S+?)(?:\[(\d+)\])?:\s+(.+)"

_PRIORITY_MAP = {
    "emerg": 0, "alert": 1, "crit": 2, "err": 3,
    "warning": 4, "notice": 5, "info": 6, "debug": 7,
}


def parse_systemd_logs(
    log_content: str,
    service_filter: Optional[str] = None,
    priority_filter: Optional[str] = None,
    max_entries: int = 1000,
) -> Dict[str, Any]:
    """Parse systemd journal logs and extract structured information."""
    try:
        result: Dict[str, Any] = {
            "success": True,
            "entries": [],
            "statistics": {
                "total_entries": 0,
                "by_priority": {},
                "by_service": {},
                "by_hour": {},
            },
            "errors": [],
            "recommendations": [],
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

        for line in log_content.split("\n")[:max_entries]:
            if not line.strip():
                continue

            m = re.match(_SYSTEMD_PATTERN, line)
            if not m:
                continue

            timestamp, hostname, service, pid, message = m.groups()

            if service_filter and service_filter.lower() not in service.lower():
                continue

            priority = "info"
            for level in ("error", "err", "fail", "crit", "alert", "emerg"):
                if level in message.lower():
                    priority = level if level in _PRIORITY_MAP else "err"
                    break

            if priority_filter:
                if _PRIORITY_MAP.get(priority, 6) > _PRIORITY_MAP.get(priority_filter, 6):
                    continue

            entry: Dict[str, Any] = {
                "timestamp": timestamp,
                "hostname": hostname,
                "service": service,
                "pid": pid,
                "priority": priority,
                "message": message,
            }

            result["entries"].append(entry)
            result["statistics"]["total_entries"] += 1
            result["statistics"]["by_priority"][priority] = (
                result["statistics"]["by_priority"].get(priority, 0) + 1
            )
            result["statistics"]["by_service"][service] = (
                result["statistics"]["by_service"].get(service, 0) + 1
            )

            try:
                hour = timestamp.split(":")[0].split()[-1]
                result["statistics"]["by_hour"][hour] = (
                    result["statistics"]["by_hour"].get(hour, 0) + 1
                )
            except (IndexError, ValueError, AttributeError):
                pass

            if any(kw in message.lower() for kw in ("failed", "error", "crash")):
                result["errors"].append({
                    "service": service,
                    "message": message[:200],
                    "timestamp": timestamp,
                })

        err_count = result["statistics"]["by_priority"].get("err", 0)
        if err_count > 50:
            result["recommendations"].append({
                "severity": "high",
                "message": f"High number of error entries ({err_count}) detected",
                "action": "Investigate error patterns and root causes",
            })

        svc_errors: Counter = Counter(e["service"] for e in result["errors"])
        for service, count in svc_errors.most_common(3):
            if count > 10:
                result["recommendations"].append({
                    "severity": "medium",
                    "message": f"Service '{service}' has {count} error entries",
                    "action": f"Check {service} configuration and logs",
                })

        return result

    except Exception as e:
        logger.error("Error parsing systemd logs: %s", e)
        return {"success": False, "error": str(e)}


def analyze_service_health(log_data: Dict[str, Any], service_name: str) -> Dict[str, Any]:
    """Analyze the health of a specific systemd service from parsed logs."""
    try:
        if not log_data.get("success"):
            return {"success": False, "error": "Invalid log data provided"}

        entries = [
            e for e in log_data.get("entries", [])
            if service_name.lower() in e.get("service", "").lower()
        ]
        if not entries:
            return {"success": False, "error": f"No entries found for service '{service_name}'"}

        total = len(entries)
        errors = len([
            e for e in entries
            if e.get("priority") in ("err", "crit", "alert", "emerg")
        ])
        error_rate = (errors / total * 100) if total else 0
        health_score = 100 - min(error_rate * 2, 100)

        if health_score >= 90:
            health_status = "healthy"
        elif health_score >= 70:
            health_status = "warning"
        else:
            health_status = "critical"

        return {
            "success": True,
            "service": service_name,
            "health_score": round(health_score, 2),
            "health_status": health_status,
            "metrics": {
                "total_entries": total,
                "error_entries": errors,
                "error_rate": round(error_rate, 2),
            },
            "recent_errors": [
                {
                    "timestamp": e.get("timestamp"),
                    "message": e.get("message", "")[:100],
                }
                for e in entries
                if e.get("priority") in ("err", "crit", "alert", "emerg")
            ][:5],
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error("Error analyzing service health: %s", e)
        return {"success": False, "error": str(e)}
