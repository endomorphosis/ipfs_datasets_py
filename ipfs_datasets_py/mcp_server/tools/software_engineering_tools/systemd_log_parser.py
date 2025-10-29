"""
Systemd Log Parser for Software Engineering Dashboard.

This module provides tools to parse and analyze systemd journal logs.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from collections import Counter

logger = logging.getLogger(__name__)


def parse_systemd_logs(
    log_content: str,
    service_filter: Optional[str] = None,
    priority_filter: Optional[str] = None,
    max_entries: int = 1000
) -> Dict[str, Any]:
    """
    Parse systemd journal logs and extract structured information.
    
    Analyzes systemd logs to identify service issues, error patterns, and
    system health indicators.
    
    Args:
        log_content: Raw systemd log content (from journalctl output)
        service_filter: Optional service name to filter logs
        priority_filter: Optional priority level (emerg, alert, crit, err, warning, notice, info, debug)
        max_entries: Maximum number of log entries to process
        
    Returns:
        Dictionary containing parsed log information with keys:
        - entries: List of parsed log entries
        - statistics: Log statistics by service and priority
        - errors: Detected error patterns
        - recommendations: System health recommendations
        - analyzed_at: Timestamp of analysis
        
    Example:
        >>> with open('/var/log/syslog') as f:
        ...     logs = f.read()
        >>> result = parse_systemd_logs(logs, service_filter='nginx')
        >>> print(f"Found {len(result['entries'])} entries")
    """
    try:
        result = {
            "success": True,
            "entries": [],
            "statistics": {
                "total_entries": 0,
                "by_priority": {},
                "by_service": {},
                "by_hour": {}
            },
            "errors": [],
            "recommendations": [],
            "analyzed_at": datetime.utcnow().isoformat()
        }
        
        lines = log_content.split('\n')[:max_entries]
        
        # Common systemd log patterns
        # Format: timestamp hostname service[pid]: message
        systemd_pattern = r'(\w+\s+\d+\s+\d+:\d+:\d+)\s+(\S+)\s+(\S+?)(?:\[(\d+)\])?:\s+(.+)'
        
        priority_map = {
            'emerg': 0, 'alert': 1, 'crit': 2, 'err': 3,
            'warning': 4, 'notice': 5, 'info': 6, 'debug': 7
        }
        
        for line in lines:
            if not line.strip():
                continue
            
            match = re.match(systemd_pattern, line)
            if match:
                timestamp, hostname, service, pid, message = match.groups()
                
                # Apply service filter
                if service_filter and service_filter.lower() not in service.lower():
                    continue
                
                # Detect priority from message
                priority = 'info'
                for level in ['error', 'err', 'fail', 'crit', 'alert', 'emerg']:
                    if level in message.lower():
                        priority = level if level in priority_map else 'err'
                        break
                
                # Apply priority filter
                if priority_filter:
                    if priority_map.get(priority, 6) > priority_map.get(priority_filter, 6):
                        continue
                
                entry = {
                    "timestamp": timestamp,
                    "hostname": hostname,
                    "service": service,
                    "pid": pid,
                    "priority": priority,
                    "message": message
                }
                
                result["entries"].append(entry)
                result["statistics"]["total_entries"] += 1
                
                # Update statistics
                result["statistics"]["by_priority"][priority] = \
                    result["statistics"]["by_priority"].get(priority, 0) + 1
                
                result["statistics"]["by_service"][service] = \
                    result["statistics"]["by_service"].get(service, 0) + 1
                
                # Extract hour from timestamp for time-based analysis
                try:
                    hour = timestamp.split(':')[0].split()[-1]
                    result["statistics"]["by_hour"][hour] = \
                        result["statistics"]["by_hour"].get(hour, 0) + 1
                except:
                    pass
                
                # Detect common errors
                if any(keyword in message.lower() for keyword in ['failed', 'error', 'crash']):
                    result["errors"].append({
                        "service": service,
                        "message": message[:200],
                        "timestamp": timestamp
                    })
        
        # Generate recommendations based on patterns
        if result["statistics"]["by_priority"].get("err", 0) > 50:
            result["recommendations"].append({
                "severity": "high",
                "message": f"High number of error entries ({result['statistics']['by_priority']['err']}) detected",
                "action": "Investigate error patterns and root causes"
            })
        
        # Check for service failures
        service_errors = Counter()
        for error in result["errors"]:
            service_errors[error["service"]] += 1
        
        for service, count in service_errors.most_common(3):
            if count > 10:
                result["recommendations"].append({
                    "severity": "medium",
                    "message": f"Service '{service}' has {count} error entries",
                    "action": f"Check {service} configuration and logs"
                })
        
        return result
        
    except Exception as e:
        logger.error(f"Error parsing systemd logs: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def analyze_service_health(log_data: Dict[str, Any], service_name: str) -> Dict[str, Any]:
    """
    Analyze the health of a specific systemd service from parsed logs.
    
    Provides detailed health analysis for a specific service including
    uptime, error rates, and performance indicators.
    
    Args:
        log_data: Parsed log data from parse_systemd_logs
        service_name: Name of the service to analyze
        
    Returns:
        Dictionary containing service health analysis
        
    Example:
        >>> log_data = parse_systemd_logs(logs)
        >>> health = analyze_service_health(log_data, 'nginx')
        >>> print(f"Health score: {health['health_score']}")
    """
    try:
        if not log_data.get("success"):
            return {
                "success": False,
                "error": "Invalid log data provided"
            }
        
        service_entries = [
            entry for entry in log_data.get("entries", [])
            if service_name.lower() in entry.get("service", "").lower()
        ]
        
        if not service_entries:
            return {
                "success": False,
                "error": f"No entries found for service '{service_name}'"
            }
        
        # Calculate metrics
        total_entries = len(service_entries)
        error_entries = len([e for e in service_entries if e.get("priority") in ['err', 'crit', 'alert', 'emerg']])
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
        
        return {
            "success": True,
            "service": service_name,
            "health_score": round(health_score, 2),
            "health_status": health_status,
            "metrics": {
                "total_entries": total_entries,
                "error_entries": error_entries,
                "error_rate": round(error_rate, 2)
            },
            "recent_errors": [
                {
                    "timestamp": e.get("timestamp"),
                    "message": e.get("message", "")[:100]
                }
                for e in service_entries
                if e.get("priority") in ['err', 'crit', 'alert', 'emerg']
            ][:5],
            "analyzed_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error analyzing service health: {e}")
        return {
            "success": False,
            "error": str(e)
        }
