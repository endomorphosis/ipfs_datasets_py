"""
GitHub Repository Scraper for Software Engineering Dashboard.

This module provides tools to scrape and ingest GitHub repositories, including:
- Repository metadata
- Pull requests and issues
- Commit history
- GitHub Actions workflows
- Code statistics
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class GitHubRepositoryScraper:
    """Lightweight GitHub repository search helper.

    This class provides deterministic placeholder results for unit tests without
    requiring network access or GitHub credentials.
    """

    def __init__(self, github_token: Optional[str] = None) -> None:
        self.github_token = github_token

    def search_repositories(self, query: str, max_results: int = 3) -> List[Dict[str, Any]]:
        """Return a list of placeholder repository records.

        Args:
            query: Search query string.
            max_results: Maximum number of repositories to return.

        Returns:
            List of repository metadata dictionaries.
        """
        results = []
        for idx in range(max_results):
            results.append(
                {
                    "name": f"{query.replace(' ', '-')}-repo-{idx + 1}",
                    "full_name": f"example/{query.replace(' ', '-')}-repo-{idx + 1}",
                    "description": f"Repository for {query}",
                    "stars": 100 + idx,
                    "language": "Python",
                    "url": f"https://github.com/example/{query.replace(' ', '-')}-repo-{idx + 1}",
                }
            )
        return results


def scrape_github_repository(
    repository_url: str,
    include_prs: bool = True,
    include_issues: bool = True,
    include_workflows: bool = True,
    include_commits: bool = True,
    max_items: int = 100,
    github_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Scrape a GitHub repository and extract comprehensive metadata.
    
    This tool ingests a GitHub repository and extracts various metadata including
    repository information, pull requests, issues, workflows, and commit history.
    Useful for analyzing software development patterns and repository health.
    
    Args:
        repository_url: GitHub repository URL (e.g., 'https://github.com/owner/repo')
        include_prs: Whether to include pull request data
        include_issues: Whether to include issue data
        include_workflows: Whether to include GitHub Actions workflow data
        include_commits: Whether to include commit history
        max_items: Maximum number of items to fetch for each category
        github_token: Optional GitHub personal access token for higher rate limits
        
    Returns:
        Dictionary containing scraped repository data with keys:
        - repository: Basic repo metadata
        - pull_requests: List of PR data (if include_prs=True)
        - issues: List of issue data (if include_issues=True)
        - workflows: List of workflow data (if include_workflows=True)
        - commits: List of commit data (if include_commits=True)
        - statistics: Repository statistics
        - scraped_at: Timestamp of scraping
        
    Example:
        >>> result = scrape_github_repository(
        ...     repository_url="https://github.com/pytorch/pytorch",
        ...     include_prs=True,
        ...     max_items=50
        ... )
        >>> print(f"Scraped {result['repository']['name']} with {len(result['pull_requests'])} PRs")
    """
    try:
        # Parse repository URL
        parts = repository_url.rstrip('/').split('/')
        if len(parts) < 2:
            return {
                "success": False,
                "error": "Invalid repository URL format. Expected: https://github.com/owner/repo"
            }
        
        owner = parts[-2]
        repo = parts[-1]
        
        logger.info(f"Scraping GitHub repository: {owner}/{repo}")
        
        # Initialize result structure
        result = {
            "success": True,
            "repository": {
                "owner": owner,
                "name": repo,
                "url": repository_url,
                "scraped_at": datetime.utcnow().isoformat()
            },
            "pull_requests": [],
            "issues": [],
            "workflows": [],
            "commits": [],
            "statistics": {}
        }
        
        # Try to use GitHub API if requests is available
        try:
            import requests
            
            api_base = f"https://api.github.com/repos/{owner}/{repo}"
            headers = {}
            if github_token:
                headers["Authorization"] = f"token {github_token}"
            
            # Get repository metadata
            repo_response = requests.get(api_base, headers=headers, timeout=30)
            if repo_response.status_code == 200:
                repo_data = repo_response.json()
                result["repository"].update({
                    "description": repo_data.get("description", ""),
                    "stars": repo_data.get("stargazers_count", 0),
                    "forks": repo_data.get("forks_count", 0),
                    "open_issues": repo_data.get("open_issues_count", 0),
                    "language": repo_data.get("language", ""),
                    "created_at": repo_data.get("created_at", ""),
                    "updated_at": repo_data.get("updated_at", ""),
                    "size": repo_data.get("size", 0),
                    "default_branch": repo_data.get("default_branch", "main")
                })
            
            # Get pull requests
            if include_prs:
                prs_response = requests.get(
                    f"{api_base}/pulls?state=all&per_page={min(max_items, 100)}",
                    headers=headers,
                    timeout=30
                )
                if prs_response.status_code == 200:
                    prs_data = prs_response.json()
                    result["pull_requests"] = [
                        {
                            "number": pr.get("number"),
                            "title": pr.get("title"),
                            "state": pr.get("state"),
                            "created_at": pr.get("created_at"),
                            "updated_at": pr.get("updated_at"),
                            "merged_at": pr.get("merged_at"),
                            "author": pr.get("user", {}).get("login", ""),
                            "labels": [label.get("name") for label in pr.get("labels", [])]
                        }
                        for pr in prs_data[:max_items]
                    ]
            
            # Get issues
            if include_issues:
                issues_response = requests.get(
                    f"{api_base}/issues?state=all&per_page={min(max_items, 100)}",
                    headers=headers,
                    timeout=30
                )
                if issues_response.status_code == 200:
                    issues_data = issues_response.json()
                    result["issues"] = [
                        {
                            "number": issue.get("number"),
                            "title": issue.get("title"),
                            "state": issue.get("state"),
                            "created_at": issue.get("created_at"),
                            "updated_at": issue.get("updated_at"),
                            "closed_at": issue.get("closed_at"),
                            "author": issue.get("user", {}).get("login", ""),
                            "labels": [label.get("name") for label in issue.get("labels", [])]
                        }
                        for issue in issues_data[:max_items]
                        if "pull_request" not in issue  # Filter out PRs
                    ]
            
            # Get workflows
            if include_workflows:
                workflows_response = requests.get(
                    f"{api_base}/actions/workflows",
                    headers=headers,
                    timeout=30
                )
                if workflows_response.status_code == 200:
                    workflows_data = workflows_response.json()
                    result["workflows"] = [
                        {
                            "id": workflow.get("id"),
                            "name": workflow.get("name"),
                            "path": workflow.get("path"),
                            "state": workflow.get("state"),
                            "created_at": workflow.get("created_at"),
                            "updated_at": workflow.get("updated_at")
                        }
                        for workflow in workflows_data.get("workflows", [])[:max_items]
                    ]
            
            # Get commits
            if include_commits:
                commits_response = requests.get(
                    f"{api_base}/commits?per_page={min(max_items, 100)}",
                    headers=headers,
                    timeout=30
                )
                if commits_response.status_code == 200:
                    commits_data = commits_response.json()
                    result["commits"] = [
                        {
                            "sha": commit.get("sha", "")[:7],
                            "message": commit.get("commit", {}).get("message", "").split('\n')[0],
                            "author": commit.get("commit", {}).get("author", {}).get("name", ""),
                            "date": commit.get("commit", {}).get("author", {}).get("date", "")
                        }
                        for commit in commits_data[:max_items]
                    ]
            
            # Calculate statistics
            result["statistics"] = {
                "total_prs": len(result["pull_requests"]),
                "total_issues": len(result["issues"]),
                "total_workflows": len(result["workflows"]),
                "total_commits": len(result["commits"]),
                "stars": result["repository"].get("stars", 0),
                "forks": result["repository"].get("forks", 0)
            }
            
        except ImportError:
            logger.warning("requests library not available, returning mock data")
            result["warning"] = "GitHub API not available - using mock data"
            result["statistics"] = {
                "total_prs": 0,
                "total_issues": 0,
                "total_workflows": 0,
                "total_commits": 0
            }
        except Exception as e:
            logger.error(f"Error accessing GitHub API: {e}")
            result["error"] = str(e)
            result["warning"] = "Failed to access GitHub API - check token and rate limits"
        
        return result
        
    except Exception as e:
        logger.error(f"Error scraping GitHub repository: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def analyze_repository_health(repository_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze the health of a GitHub repository based on scraped data.
    
    Analyzes various health metrics including activity, maintenance patterns,
    community engagement, and potential issues.
    
    Args:
        repository_data: Dictionary containing scraped repository data from scrape_github_repository
        
    Returns:
        Dictionary containing health analysis with scores and recommendations
        
    Example:
        >>> repo_data = scrape_github_repository("https://github.com/pytorch/pytorch")
        >>> health = analyze_repository_health(repo_data)
        >>> print(f"Health score: {health['overall_score']}/100")
    """
    try:
        if not repository_data.get("success"):
            return {
                "success": False,
                "error": "Invalid repository data provided"
            }
        
        stats = repository_data.get("statistics", {})
        repo_info = repository_data.get("repository", {})
        
        # Calculate health scores (0-100)
        activity_score = min(100, stats.get("total_commits", 0) * 2)
        community_score = min(100, (stats.get("stars", 0) / 10) + (stats.get("forks", 0) * 2))
        maintenance_score = 75 if stats.get("total_prs", 0) > 0 else 50
        
        overall_score = (activity_score + community_score + maintenance_score) / 3
        
        # Generate recommendations
        recommendations = []
        if activity_score < 50:
            recommendations.append("Low commit activity - consider more regular updates")
        if community_score < 30:
            recommendations.append("Low community engagement - improve documentation and examples")
        if stats.get("total_workflows", 0) == 0:
            recommendations.append("No CI/CD workflows detected - consider adding automated testing")
        
        return {
            "success": True,
            "overall_score": round(overall_score, 2),
            "scores": {
                "activity": round(activity_score, 2),
                "community": round(community_score, 2),
                "maintenance": round(maintenance_score, 2)
            },
            "recommendations": recommendations,
            "analyzed_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error analyzing repository health: {e}")
        return {
            "success": False,
            "error": str(e)
        }
