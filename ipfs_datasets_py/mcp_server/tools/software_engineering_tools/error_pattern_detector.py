"""
Error Pattern Detector for Software Engineering Dashboard.

This module provides tools to detect and analyze common error patterns in logs.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from collections import Counter

logger = logging.getLogger(__name__)


def detect_error_patterns(
    error_logs: List[str],
    pattern_library: Optional[Dict[str, str]] = None,
    min_occurrences: int = 2
) -> Dict[str, Any]:
    """
    Detect common error patterns in log data.
    
    Analyzes error logs to identify recurring patterns, helping identify
    systemic issues and potential auto-healing opportunities.
    
    Args:
        error_logs: List of error log messages
        pattern_library: Optional dict of known error patterns to match
        min_occurrences: Minimum occurrences to consider a pattern
        
    Returns:
        Dictionary containing detected patterns with keys:
        - patterns: List of detected error patterns
        - most_common: Most frequently occurring patterns
        - recommendations: Suggested fixes
        
    Example:
        >>> logs = ["Connection timeout", "Connection timeout", "Out of memory"]
        >>> result = detect_error_patterns(logs)
        >>> print(f"Found {len(result['patterns'])} patterns")
    """
    try:
        result = {
            "success": True,
            "patterns": [],
            "most_common": [],
            "recommendations": [],
            "analyzed_at": datetime.utcnow().isoformat()
        }
        
        if not error_logs:
            return result
        
        # Default pattern library
        if pattern_library is None:
            pattern_library = {
                "connection_timeout": r"(?i)(connection|timeout|timed out)",
                "out_of_memory": r"(?i)(out of memory|oom|memory error)",
                "permission_denied": r"(?i)(permission denied|access denied)",
                "file_not_found": r"(?i)(file not found|no such file)",
                "network_unreachable": r"(?i)(network unreachable|cannot reach)",
                "authentication_failed": r"(?i)(auth.*failed|authentication error)",
                "database_connection": r"(?i)(database.*connection|db.*error)",
                "api_rate_limit": r"(?i)(rate limit|too many requests)",
                "disk_full": r"(?i)(disk full|no space left)",
                "syntax_error": r"(?i)(syntax error|invalid syntax)"
            }
        
        # Detect patterns
        pattern_counts = Counter()
        pattern_examples = {}
        
        for log in error_logs:
            for pattern_name, pattern_regex in pattern_library.items():
                if re.search(pattern_regex, log):
                    pattern_counts[pattern_name] += 1
                    if pattern_name not in pattern_examples:
                        pattern_examples[pattern_name] = []
                    if len(pattern_examples[pattern_name]) < 3:
                        pattern_examples[pattern_name].append(log[:200])
        
        # Filter by minimum occurrences
        for pattern_name, count in pattern_counts.items():
            if count >= min_occurrences:
                result["patterns"].append({
                    "pattern": pattern_name,
                    "occurrences": count,
                    "percentage": round((count / len(error_logs)) * 100, 2),
                    "examples": pattern_examples.get(pattern_name, [])
                })
        
        # Sort by occurrence
        result["patterns"].sort(key=lambda x: x["occurrences"], reverse=True)
        result["most_common"] = result["patterns"][:5]
        
        # Generate recommendations
        for pattern in result["most_common"]:
            pattern_name = pattern["pattern"]
            
            if pattern_name == "connection_timeout":
                result["recommendations"].append({
                    "pattern": pattern_name,
                    "severity": "medium",
                    "recommendation": "Implement connection retry logic with exponential backoff",
                    "auto_healable": True
                })
            elif pattern_name == "out_of_memory":
                result["recommendations"].append({
                    "pattern": pattern_name,
                    "severity": "high",
                    "recommendation": "Increase memory limits or optimize memory usage",
                    "auto_healable": False
                })
            elif pattern_name == "permission_denied":
                result["recommendations"].append({
                    "pattern": pattern_name,
                    "severity": "medium",
                    "recommendation": "Check and fix file/directory permissions",
                    "auto_healable": True
                })
            elif pattern_name == "api_rate_limit":
                result["recommendations"].append({
                    "pattern": pattern_name,
                    "severity": "medium",
                    "recommendation": "Implement rate limiting and request throttling",
                    "auto_healable": True
                })
        
        return result
        
    except Exception as e:
        logger.error(f"Error detecting error patterns: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def suggest_fixes(error_pattern: str) -> Dict[str, Any]:
    """
    Suggest fixes for a detected error pattern.
    
    Provides specific fix recommendations for common error patterns.
    
    Args:
        error_pattern: Name of the error pattern
        
    Returns:
        Dictionary containing fix suggestions
        
    Example:
        >>> fixes = suggest_fixes("connection_timeout")
        >>> print(fixes['fixes'][0]['action'])
    """
    try:
        fix_library = {
            "connection_timeout": {
                "fixes": [
                    {
                        "action": "Implement retry logic",
                        "code_example": "for attempt in range(3): try: connect(); break except: sleep(2**attempt)",
                        "priority": "high"
                    },
                    {
                        "action": "Increase timeout duration",
                        "code_example": "timeout=60  # Increase from default 30s",
                        "priority": "medium"
                    }
                ]
            },
            "out_of_memory": {
                "fixes": [
                    {
                        "action": "Increase memory allocation",
                        "code_example": "resources.limits.memory: 8Gi",
                        "priority": "high"
                    },
                    {
                        "action": "Implement batch processing",
                        "code_example": "for batch in chunks(data, 1000): process(batch)",
                        "priority": "medium"
                    }
                ]
            },
            "permission_denied": {
                "fixes": [
                    {
                        "action": "Fix file permissions",
                        "code_example": "chmod 644 file.txt  # or sudo chown user:group file.txt",
                        "priority": "high"
                    }
                ]
            },
            "api_rate_limit": {
                "fixes": [
                    {
                        "action": "Implement request throttling",
                        "code_example": "time.sleep(1)  # Add delay between requests",
                        "priority": "high"
                    },
                    {
                        "action": "Use exponential backoff",
                        "code_example": "sleep(min(2**attempt, 60))",
                        "priority": "medium"
                    }
                ]
            }
        }
        
        fixes = fix_library.get(error_pattern, {
            "fixes": [
                {
                    "action": "Manual investigation required",
                    "code_example": "No automatic fix available",
                    "priority": "medium"
                }
            ]
        })
        
        return {
            "success": True,
            "pattern": error_pattern,
            **fixes
        }
        
    except Exception as e:
        logger.error(f"Error suggesting fixes: {e}")
        return {
            "success": False,
            "error": str(e)
        }
