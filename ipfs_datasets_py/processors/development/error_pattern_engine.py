"""
Error Pattern Detection Engine — canonical package module.

Business logic extracted from mcp_server/tools/software_engineering_tools/error_pattern_detector.py.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_PATTERN_LIBRARY: Dict[str, str] = {
    "connection_timeout": r"(?i)(connection|timeout|timed out)",
    "out_of_memory": r"(?i)(out of memory|oom|memory error)",
    "permission_denied": r"(?i)(permission denied|access denied)",
    "file_not_found": r"(?i)(file not found|no such file)",
    "network_unreachable": r"(?i)(network unreachable|cannot reach)",
    "authentication_failed": r"(?i)(auth.*failed|authentication error)",
    "database_connection": r"(?i)(database.*connection|db.*error)",
    "api_rate_limit": r"(?i)(rate limit|too many requests)",
    "disk_full": r"(?i)(disk full|no space left)",
    "syntax_error": r"(?i)(syntax error|invalid syntax)",
}

_FIX_LIBRARY: Dict[str, Any] = {
    "connection_timeout": {
        "fixes": [
            {
                "action": "Implement retry logic",
                "code_example": (
                    "for attempt in range(3): try: connect(); break except: sleep(2**attempt)"
                ),
                "priority": "high",
            },
            {
                "action": "Increase timeout duration",
                "code_example": "timeout=60  # Increase from default 30s",
                "priority": "medium",
            },
        ]
    },
    "out_of_memory": {
        "fixes": [
            {
                "action": "Increase memory allocation",
                "code_example": "resources.limits.memory: 8Gi",
                "priority": "high",
            },
            {
                "action": "Implement batch processing",
                "code_example": "for batch in chunks(data, 1000): process(batch)",
                "priority": "medium",
            },
        ]
    },
    "permission_denied": {
        "fixes": [
            {
                "action": "Fix file permissions",
                "code_example": "chmod 644 file.txt  # or sudo chown user:group file.txt",
                "priority": "high",
            }
        ]
    },
    "api_rate_limit": {
        "fixes": [
            {
                "action": "Implement request throttling",
                "code_example": "time.sleep(1)  # Add delay between requests",
                "priority": "high",
            },
            {
                "action": "Use exponential backoff",
                "code_example": "sleep(min(2**attempt, 60))",
                "priority": "medium",
            },
        ]
    },
}


def detect_error_patterns(
    error_logs: List[str],
    pattern_library: Optional[Dict[str, str]] = None,
    min_occurrences: int = 2,
) -> Dict[str, Any]:
    """Detect common error patterns in log data."""
    try:
        result: Dict[str, Any] = {
            "success": True,
            "patterns": [],
            "most_common": [],
            "recommendations": [],
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

        if not error_logs:
            return result

        lib = pattern_library if pattern_library is not None else _DEFAULT_PATTERN_LIBRARY

        pattern_counts: Counter = Counter()
        pattern_examples: Dict[str, List[str]] = {}

        for log in error_logs:
            for pattern_name, regex in lib.items():
                if re.search(regex, log):
                    pattern_counts[pattern_name] += 1
                    examples = pattern_examples.setdefault(pattern_name, [])
                    if len(examples) < 3:
                        examples.append(log[:200])

        for pattern_name, count in pattern_counts.items():
            if count >= min_occurrences:
                result["patterns"].append({
                    "pattern": pattern_name,
                    "occurrences": count,
                    "percentage": round(count / len(error_logs) * 100, 2),
                    "examples": pattern_examples.get(pattern_name, []),
                })

        result["patterns"].sort(key=lambda x: x["occurrences"], reverse=True)
        result["most_common"] = result["patterns"][:5]

        _rec_map = {
            "connection_timeout": {
                "severity": "medium",
                "recommendation": "Implement connection retry logic with exponential backoff",
                "auto_healable": True,
            },
            "out_of_memory": {
                "severity": "high",
                "recommendation": "Increase memory limits or optimize memory usage",
                "auto_healable": False,
            },
            "permission_denied": {
                "severity": "medium",
                "recommendation": "Check and fix file/directory permissions",
                "auto_healable": True,
            },
            "api_rate_limit": {
                "severity": "medium",
                "recommendation": "Implement rate limiting and request throttling",
                "auto_healable": True,
            },
        }
        for pattern in result["most_common"]:
            pname = pattern["pattern"]
            if pname in _rec_map:
                result["recommendations"].append({"pattern": pname, **_rec_map[pname]})

        return result

    except Exception as e:
        logger.error("Error detecting error patterns: %s", e)
        return {"success": False, "error": str(e)}


def suggest_fixes(error_pattern: str) -> Dict[str, Any]:
    """Suggest fixes for a detected error pattern."""
    try:
        fixes = _FIX_LIBRARY.get(
            error_pattern,
            {"fixes": [{"action": "Manual investigation required", "code_example": "N/A", "priority": "medium"}]},
        )
        return {"success": True, "pattern": error_pattern, **fixes}
    except Exception as e:
        logger.error("Error suggesting fixes: %s", e)
        return {"success": False, "error": str(e)}
