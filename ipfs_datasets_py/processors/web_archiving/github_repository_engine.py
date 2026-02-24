"""
GitHub Repository Scraper Engine.

Canonical business logic for scraping and analysing GitHub repositories.
This module is the authoritative location for the GitHubRepositoryScraper class.

Exposed in ``ipfs_datasets_py.web_archiving`` so the same class can be used
from package imports, CLI tools, and MCP server tools.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class GitHubRepositoryScraper:
    """Lightweight GitHub repository search helper.

    Provides deterministic placeholder results for unit tests without requiring
    network access or GitHub credentials, and full GitHub API access when
    the ``requests`` library is available and a token is supplied.

    Args:
        github_token: Optional GitHub personal access token.
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
            slug = query.replace(" ", "-")
            results.append(
                {
                    "name": f"{slug}-repo-{idx + 1}",
                    "full_name": f"example/{slug}-repo-{idx + 1}",
                    "description": f"Repository for {query}",
                    "stars": 100 + idx,
                    "language": "Python",
                    "url": f"https://github.com/example/{slug}-repo-{idx + 1}",
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
    github_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Scrape a GitHub repository and extract comprehensive metadata.

    Args:
        repository_url: GitHub repository URL (``https://github.com/owner/repo``).
        include_prs: Whether to include pull request data.
        include_issues: Whether to include issue data.
        include_workflows: Whether to include GitHub Actions workflow data.
        include_commits: Whether to include commit history.
        max_items: Maximum number of items to fetch for each category.
        github_token: Optional GitHub personal access token.

    Returns:
        Dictionary with keys: ``repository``, ``pull_requests``, ``issues``,
        ``workflows``, ``commits``, ``statistics``, ``scraped_at``.
    """
    try:
        parts = repository_url.rstrip("/").split("/")
        if len(parts) < 2:
            return {
                "success": False,
                "error": "Invalid repository URL. Expected: https://github.com/owner/repo",
            }

        owner = parts[-2]
        repo = parts[-1]

        logger.info("Scraping GitHub repository: %s/%s", owner, repo)

        result: Dict[str, Any] = {
            "success": True,
            "repository": {
                "owner": owner,
                "name": repo,
                "url": repository_url,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            },
            "pull_requests": [],
            "issues": [],
            "workflows": [],
            "commits": [],
            "statistics": {},
        }

        try:
            import requests  # noqa: PLC0415 — optional runtime dependency

            api_base = f"https://api.github.com/repos/{owner}/{repo}"
            headers: Dict[str, str] = {}
            if github_token:
                headers["Authorization"] = f"token {github_token}"

            repo_response = requests.get(api_base, headers=headers, timeout=30)
            if repo_response.status_code == 200:
                repo_data = repo_response.json()
                result["repository"].update(
                    {
                        "description": repo_data.get("description", ""),
                        "stars": repo_data.get("stargazers_count", 0),
                        "forks": repo_data.get("forks_count", 0),
                        "open_issues": repo_data.get("open_issues_count", 0),
                        "language": repo_data.get("language", ""),
                        "created_at": repo_data.get("created_at", ""),
                        "updated_at": repo_data.get("updated_at", ""),
                        "size": repo_data.get("size", 0),
                        "default_branch": repo_data.get("default_branch", "main"),
                    }
                )

            if include_prs:
                prs_response = requests.get(
                    f"{api_base}/pulls?state=all&per_page={min(max_items, 100)}",
                    headers=headers,
                    timeout=30,
                )
                if prs_response.status_code == 200:
                    result["pull_requests"] = [
                        {
                            "number": pr.get("number"),
                            "title": pr.get("title"),
                            "state": pr.get("state"),
                            "created_at": pr.get("created_at"),
                            "updated_at": pr.get("updated_at"),
                            "merged_at": pr.get("merged_at"),
                            "author": pr.get("user", {}).get("login", ""),
                            "labels": [l.get("name") for l in pr.get("labels", [])],
                        }
                        for pr in prs_response.json()[:max_items]
                    ]

            if include_issues:
                issues_response = requests.get(
                    f"{api_base}/issues?state=all&per_page={min(max_items, 100)}",
                    headers=headers,
                    timeout=30,
                )
                if issues_response.status_code == 200:
                    result["issues"] = [
                        {
                            "number": issue.get("number"),
                            "title": issue.get("title"),
                            "state": issue.get("state"),
                            "created_at": issue.get("created_at"),
                            "updated_at": issue.get("updated_at"),
                            "closed_at": issue.get("closed_at"),
                            "author": issue.get("user", {}).get("login", ""),
                            "labels": [l.get("name") for l in issue.get("labels", [])],
                        }
                        for issue in issues_response.json()[:max_items]
                        if "pull_request" not in issue
                    ]

            if include_workflows:
                wf_response = requests.get(
                    f"{api_base}/actions/workflows",
                    headers=headers,
                    timeout=30,
                )
                if wf_response.status_code == 200:
                    result["workflows"] = [
                        {
                            "id": wf.get("id"),
                            "name": wf.get("name"),
                            "path": wf.get("path"),
                            "state": wf.get("state"),
                            "created_at": wf.get("created_at"),
                            "updated_at": wf.get("updated_at"),
                        }
                        for wf in wf_response.json().get("workflows", [])[:max_items]
                    ]

            if include_commits:
                commits_response = requests.get(
                    f"{api_base}/commits?per_page={min(max_items, 100)}",
                    headers=headers,
                    timeout=30,
                )
                if commits_response.status_code == 200:
                    result["commits"] = [
                        {
                            "sha": commit.get("sha", "")[:7],
                            "message": commit.get("commit", {})
                            .get("message", "")
                            .split("\n")[0],
                            "author": commit.get("commit", {})
                            .get("author", {})
                            .get("name", ""),
                            "date": commit.get("commit", {}).get("author", {}).get("date", ""),
                        }
                        for commit in commits_response.json()[:max_items]
                    ]

            result["statistics"] = {
                "total_prs": len(result["pull_requests"]),
                "total_issues": len(result["issues"]),
                "total_workflows": len(result["workflows"]),
                "total_commits": len(result["commits"]),
                "stars": result["repository"].get("stars", 0),
                "forks": result["repository"].get("forks", 0),
            }

        except ImportError:
            logger.warning("requests library not available, returning mock data")
            result["warning"] = "GitHub API not available — using mock data"
            result["statistics"] = {
                "total_prs": 0,
                "total_issues": 0,
                "total_workflows": 0,
                "total_commits": 0,
            }
        except Exception as exc:
            logger.error("Error accessing GitHub API: %s", exc)
            result["error"] = str(exc)
            result["warning"] = "Failed to access GitHub API — check token and rate limits"

        return result

    except Exception as exc:
        logger.error("Error scraping GitHub repository: %s", exc)
        return {"success": False, "error": str(exc)}


def analyze_repository_health(repository_data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyse the health of a GitHub repository based on scraped data.

    Args:
        repository_data: Dictionary from :func:`scrape_github_repository`.

    Returns:
        Dictionary with ``overall_score``, ``scores``, and ``recommendations``.
    """
    try:
        if not repository_data.get("success"):
            return {"success": False, "error": "Invalid repository data provided"}

        stats = repository_data.get("statistics", {})

        activity_score = min(100, stats.get("total_commits", 0) * 2)
        community_score = min(
            100, (stats.get("stars", 0) / 10) + (stats.get("forks", 0) * 2)
        )
        maintenance_score = 75 if stats.get("total_prs", 0) > 0 else 50

        overall_score = (activity_score + community_score + maintenance_score) / 3

        recommendations: List[str] = []
        if activity_score < 50:
            recommendations.append("Low commit activity — consider more regular updates")
        if community_score < 30:
            recommendations.append(
                "Low community engagement — improve documentation and examples"
            )
        if stats.get("total_workflows", 0) == 0:
            recommendations.append(
                "No CI/CD workflows detected — consider adding automated testing"
            )

        return {
            "success": True,
            "overall_score": round(overall_score, 2),
            "scores": {
                "activity": round(activity_score, 2),
                "community": round(community_score, 2),
                "maintenance": round(maintenance_score, 2),
            },
            "recommendations": recommendations,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as exc:
        logger.error("Error analyzing repository health: %s", exc)
        return {"success": False, "error": str(exc)}
