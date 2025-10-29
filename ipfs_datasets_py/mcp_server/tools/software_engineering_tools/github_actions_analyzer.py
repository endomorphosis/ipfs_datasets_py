"""
GitHub Actions Analyzer for Software Engineering Dashboard.

This module provides tools to analyze GitHub Actions workflows, runs, and logs.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def analyze_github_actions(
    repository_url: str,
    workflow_id: Optional[str] = None,
    max_runs: int = 50,
    github_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analyze GitHub Actions workflows and their execution history.
    
    Fetches and analyzes GitHub Actions workflow runs, providing insights into
    CI/CD performance, failure patterns, and resource usage.
    
    Args:
        repository_url: GitHub repository URL (e.g., 'https://github.com/owner/repo')
        workflow_id: Optional specific workflow ID or filename to analyze
        max_runs: Maximum number of workflow runs to fetch
        github_token: Optional GitHub personal access token for authentication
        
    Returns:
        Dictionary containing workflow analysis with keys:
        - workflows: List of workflows with run statistics
        - success_rate: Overall success rate percentage
        - average_duration: Average workflow duration in seconds
        - failure_patterns: Common failure patterns detected
        - resource_usage: Estimated resource usage
        - analyzed_at: Timestamp of analysis
        
    Example:
        >>> result = analyze_github_actions(
        ...     repository_url="https://github.com/pytorch/pytorch",
        ...     max_runs=100
        ... )
        >>> print(f"Success rate: {result['success_rate']}%")
    """
    try:
        # Parse repository URL
        parts = repository_url.rstrip('/').split('/')
        if len(parts) < 2:
            return {
                "success": False,
                "error": "Invalid repository URL format"
            }
        
        owner = parts[-2]
        repo = parts[-1]
        
        logger.info(f"Analyzing GitHub Actions for {owner}/{repo}")
        
        result = {
            "success": True,
            "repository": f"{owner}/{repo}",
            "workflows": [],
            "success_rate": 0.0,
            "average_duration": 0.0,
            "failure_patterns": [],
            "resource_usage": {},
            "analyzed_at": datetime.utcnow().isoformat()
        }
        
        try:
            import requests
            
            api_base = f"https://api.github.com/repos/{owner}/{repo}"
            headers = {}
            if github_token:
                headers["Authorization"] = f"token {github_token}"
            
            # Get workflows
            workflows_response = requests.get(
                f"{api_base}/actions/workflows",
                headers=headers,
                timeout=30
            )
            
            if workflows_response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Failed to fetch workflows: {workflows_response.status_code}"
                }
            
            workflows_data = workflows_response.json()
            
            total_runs = 0
            successful_runs = 0
            total_duration = 0
            
            for workflow in workflows_data.get("workflows", []):
                workflow_name = workflow.get("name", "")
                workflow_path = workflow.get("path", "")
                
                # Get runs for this workflow
                runs_response = requests.get(
                    f"{api_base}/actions/workflows/{workflow['id']}/runs?per_page={min(max_runs, 100)}",
                    headers=headers,
                    timeout=30
                )
                
                if runs_response.status_code == 200:
                    runs_data = runs_response.json()
                    runs = runs_data.get("workflow_runs", [])
                    
                    workflow_stats = {
                        "name": workflow_name,
                        "path": workflow_path,
                        "total_runs": len(runs),
                        "successful_runs": 0,
                        "failed_runs": 0,
                        "average_duration": 0,
                        "last_run": None
                    }
                    
                    durations = []
                    
                    for run in runs:
                        total_runs += 1
                        
                        conclusion = run.get("conclusion", "")
                        if conclusion == "success":
                            successful_runs += 1
                            workflow_stats["successful_runs"] += 1
                        elif conclusion in ["failure", "cancelled", "timed_out"]:
                            workflow_stats["failed_runs"] += 1
                        
                        # Calculate duration
                        created_at = run.get("created_at")
                        updated_at = run.get("updated_at")
                        if created_at and updated_at:
                            try:
                                created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                                updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                                duration = (updated - created).total_seconds()
                                durations.append(duration)
                                total_duration += duration
                            except:
                                pass
                        
                        # Track last run
                        if not workflow_stats["last_run"]:
                            workflow_stats["last_run"] = {
                                "conclusion": conclusion,
                                "created_at": created_at,
                                "html_url": run.get("html_url", "")
                            }
                    
                    if durations:
                        workflow_stats["average_duration"] = sum(durations) / len(durations)
                    
                    result["workflows"].append(workflow_stats)
            
            # Calculate overall statistics
            if total_runs > 0:
                result["success_rate"] = round((successful_runs / total_runs) * 100, 2)
                result["average_duration"] = round(total_duration / total_runs, 2)
            
            # Detect failure patterns (simplified)
            if result["success_rate"] < 70:
                result["failure_patterns"].append({
                    "pattern": "High failure rate",
                    "severity": "high",
                    "description": f"Success rate is {result['success_rate']}% (below 70% threshold)"
                })
            
            if result["average_duration"] > 1800:  # 30 minutes
                result["failure_patterns"].append({
                    "pattern": "Long workflow duration",
                    "severity": "medium",
                    "description": f"Average duration is {result['average_duration']/60:.1f} minutes"
                })
            
            # Estimate resource usage
            result["resource_usage"] = {
                "total_workflow_runs": total_runs,
                "estimated_compute_minutes": round(total_duration / 60, 2),
                "estimated_cost_usd": round((total_duration / 60) * 0.008, 2)  # Rough GitHub Actions pricing
            }
            
        except ImportError:
            logger.warning("requests library not available")
            result["warning"] = "GitHub API not available - using mock data"
        except Exception as e:
            logger.error(f"Error accessing GitHub API: {e}")
            result["error"] = str(e)
        
        return result
        
    except Exception as e:
        logger.error(f"Error analyzing GitHub Actions: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def parse_workflow_logs(
    log_content: str,
    detect_errors: bool = True,
    extract_patterns: bool = True
) -> Dict[str, Any]:
    """
    Parse GitHub Actions workflow logs and extract insights.
    
    Analyzes workflow log content to identify errors, warnings, and patterns
    that can help with debugging and optimization.
    
    Args:
        log_content: Raw log content from a GitHub Actions workflow run
        detect_errors: Whether to detect and extract error messages
        extract_patterns: Whether to extract common patterns
        
    Returns:
        Dictionary containing parsed log information with keys:
        - errors: List of detected errors
        - warnings: List of detected warnings
        - patterns: Common patterns found
        - statistics: Log statistics
        
    Example:
        >>> logs = "Step 1: Build\\nError: Failed to build\\nWarning: Deprecated API"
        >>> result = parse_workflow_logs(logs)
        >>> print(f"Found {len(result['errors'])} errors")
    """
    try:
        result = {
            "success": True,
            "errors": [],
            "warnings": [],
            "patterns": [],
            "statistics": {
                "total_lines": 0,
                "error_lines": 0,
                "warning_lines": 0
            }
        }
        
        lines = log_content.split('\n')
        result["statistics"]["total_lines"] = len(lines)
        
        if detect_errors:
            # Common error patterns
            error_patterns = [
                r'(?i)error:?\s+(.+)',
                r'(?i)failed:?\s+(.+)',
                r'(?i)exception:?\s+(.+)',
                r'(?i)fatal:?\s+(.+)',
            ]
            
            for line in lines:
                for pattern in error_patterns:
                    match = re.search(pattern, line)
                    if match:
                        result["errors"].append({
                            "message": match.group(1).strip(),
                            "line": line.strip()
                        })
                        result["statistics"]["error_lines"] += 1
                        break
        
        # Detect warnings
        warning_patterns = [
            r'(?i)warning:?\s+(.+)',
            r'(?i)deprecated:?\s+(.+)',
        ]
        
        for line in lines:
            for pattern in warning_patterns:
                match = re.search(pattern, line)
                if match:
                    result["warnings"].append({
                        "message": match.group(1).strip(),
                        "line": line.strip()
                    })
                    result["statistics"]["warning_lines"] += 1
                    break
        
        if extract_patterns:
            # Extract common patterns
            if "timeout" in log_content.lower():
                result["patterns"].append("Timeout detected")
            if "out of memory" in log_content.lower() or "oom" in log_content.lower():
                result["patterns"].append("Out of memory issue")
            if "connection" in log_content.lower() and "refused" in log_content.lower():
                result["patterns"].append("Connection refused")
            if "permission denied" in log_content.lower():
                result["patterns"].append("Permission issue")
        
        return result
        
    except Exception as e:
        logger.error(f"Error parsing workflow logs: {e}")
        return {
            "success": False,
            "error": str(e)
        }
