"""
GitHub Actions Analysis Engine — canonical package module.

Business logic extracted from mcp_server/tools/software_engineering_tools/github_actions_analyzer.py.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def analyze_github_actions(
    repository_url: str,
    workflow_id: Optional[str] = None,
    max_runs: int = 50,
    github_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Analyze GitHub Actions workflows and their execution history."""
    try:
        parts = repository_url.rstrip("/").split("/")
        if len(parts) < 2:
            return {"success": False, "error": "Invalid repository URL format"}

        owner, repo = parts[-2], parts[-1]
        logger.info("Analyzing GitHub Actions for %s/%s", owner, repo)

        result: Dict[str, Any] = {
            "success": True,
            "repository": f"{owner}/{repo}",
            "workflows": [],
            "success_rate": 0.0,
            "average_duration": 0.0,
            "failure_patterns": [],
            "resource_usage": {},
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            import requests  # type: ignore[import]

            api_base = f"https://api.github.com/repos/{owner}/{repo}"
            headers: Dict[str, str] = {}
            if github_token:
                headers["Authorization"] = f"token {github_token}"

            workflows_resp = requests.get(
                f"{api_base}/actions/workflows", headers=headers, timeout=30
            )
            if workflows_resp.status_code != 200:
                return {
                    "success": False,
                    "error": f"Failed to fetch workflows: {workflows_resp.status_code}",
                }

            total_runs = 0
            successful_runs = 0
            total_duration = 0.0

            for workflow in workflows_resp.json().get("workflows", []):
                runs_resp = requests.get(
                    f"{api_base}/actions/workflows/{workflow['id']}/runs"
                    f"?per_page={min(max_runs, 100)}",
                    headers=headers,
                    timeout=30,
                )
                if runs_resp.status_code != 200:
                    continue

                runs = runs_resp.json().get("workflow_runs", [])
                stats: Dict[str, Any] = {
                    "name": workflow.get("name", ""),
                    "path": workflow.get("path", ""),
                    "total_runs": len(runs),
                    "successful_runs": 0,
                    "failed_runs": 0,
                    "average_duration": 0,
                    "last_run": None,
                }

                durations: List[float] = []
                for run in runs:
                    total_runs += 1
                    conclusion = run.get("conclusion", "")
                    if conclusion == "success":
                        successful_runs += 1
                        stats["successful_runs"] += 1
                    elif conclusion in ("failure", "cancelled", "timed_out"):
                        stats["failed_runs"] += 1

                    created_at = run.get("created_at")
                    updated_at = run.get("updated_at")
                    if created_at and updated_at:
                        try:
                            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                            updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                            dur = (updated - created).total_seconds()
                            durations.append(dur)
                            total_duration += dur
                        except (ValueError, AttributeError, TypeError):
                            pass

                    if not stats["last_run"]:
                        stats["last_run"] = {
                            "conclusion": conclusion,
                            "created_at": created_at,
                            "html_url": run.get("html_url", ""),
                        }

                if durations:
                    stats["average_duration"] = sum(durations) / len(durations)
                result["workflows"].append(stats)

            if total_runs > 0:
                result["success_rate"] = round(successful_runs / total_runs * 100, 2)
                result["average_duration"] = round(total_duration / total_runs, 2)

            if result["success_rate"] < 70:
                result["failure_patterns"].append({
                    "pattern": "High failure rate",
                    "severity": "high",
                    "description": f"Success rate is {result['success_rate']}% (below 70% threshold)",
                })
            if result["average_duration"] > 1800:
                result["failure_patterns"].append({
                    "pattern": "Long workflow duration",
                    "severity": "medium",
                    "description": f"Average duration is {result['average_duration'] / 60:.1f} minutes",
                })

            result["resource_usage"] = {
                "total_workflow_runs": total_runs,
                "estimated_compute_minutes": round(total_duration / 60, 2),
                "estimated_cost_usd": round((total_duration / 60) * 0.008, 2),
            }

        except ImportError:
            logger.warning("requests library not available")
            result["warning"] = "GitHub API not available - using mock data"
        except Exception as e:
            logger.error("Error accessing GitHub API: %s", e)
            result["error"] = str(e)

        return result

    except Exception as e:
        logger.error("Error analyzing GitHub Actions: %s", e)
        return {"success": False, "error": str(e)}


def parse_workflow_logs(
    log_content: str,
    detect_errors: bool = True,
    extract_patterns: bool = True,
) -> Dict[str, Any]:
    """Parse GitHub Actions workflow logs and extract insights."""
    try:
        result: Dict[str, Any] = {
            "success": True,
            "errors": [],
            "warnings": [],
            "patterns": [],
            "statistics": {
                "total_lines": 0,
                "error_lines": 0,
                "warning_lines": 0,
            },
        }

        lines = log_content.split("\n")
        result["statistics"]["total_lines"] = len(lines)

        error_patterns = [
            r"(?i)error:?\s+(.+)",
            r"(?i)failed:?\s+(.+)",
            r"(?i)exception:?\s+(.+)",
            r"(?i)fatal:?\s+(.+)",
        ]
        warning_patterns = [
            r"(?i)warning:?\s+(.+)",
            r"(?i)deprecated:?\s+(.+)",
        ]

        if detect_errors:
            for line in lines:
                for pattern in error_patterns:
                    m = re.search(pattern, line)
                    if m:
                        result["errors"].append({"message": m.group(1).strip(), "line": line.strip()})
                        result["statistics"]["error_lines"] += 1
                        break

        for line in lines:
            for pattern in warning_patterns:
                m = re.search(pattern, line)
                if m:
                    result["warnings"].append({"message": m.group(1).strip(), "line": line.strip()})
                    result["statistics"]["warning_lines"] += 1
                    break

        if extract_patterns:
            lc = log_content.lower()
            if "timeout" in lc:
                result["patterns"].append("Timeout detected")
            if "out of memory" in lc or "oom" in lc:
                result["patterns"].append("Out of memory issue")
            if "connection" in lc and "refused" in lc:
                result["patterns"].append("Connection refused")
            if "permission denied" in lc:
                result["patterns"].append("Permission issue")

        return result

    except Exception as e:
        logger.error("Error parsing workflow logs: %s", e)
        return {"success": False, "error": str(e)}
