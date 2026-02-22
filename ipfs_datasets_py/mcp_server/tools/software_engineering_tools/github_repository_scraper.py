"""
GitHub Repository Scraper — thin MCP wrapper.

Business logic lives in the canonical package module:
    ipfs_datasets_py.web_archiving.github_repository_engine

This file re-exports domain classes for backward compatibility and provides
MCP-callable standalone async functions.
"""

import logging
from typing import Any, Dict, Optional

from ipfs_datasets_py.web_archiving.github_repository_engine import (  # noqa: F401
    GitHubRepositoryScraper,
    analyze_repository_health,
    scrape_github_repository,
)

logger = logging.getLogger(__name__)


async def scrape_repository(
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
        repository_url: GitHub repository URL.
        include_prs: Whether to include pull request data.
        include_issues: Whether to include issue data.
        include_workflows: Whether to include workflow data.
        include_commits: Whether to include commit history.
        max_items: Maximum items to fetch per category.
        github_token: Optional GitHub personal access token.

    Returns:
        Dict with repository metadata and statistics.
    """
    return scrape_github_repository(
        repository_url=repository_url,
        include_prs=include_prs,
        include_issues=include_issues,
        include_workflows=include_workflows,
        include_commits=include_commits,
        max_items=max_items,
        github_token=github_token,
    )


async def analyze_repository(repository_data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyse the health of a GitHub repository from scraped data.

    Args:
        repository_data: Dictionary from :func:`scrape_github_repository`.

    Returns:
        Dict with overall_score, scores, and recommendations.
    """
    return analyze_repository_health(repository_data)


async def search_repositories(
    query: str,
    max_results: int = 3,
    github_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Search GitHub for repositories matching a query.

    Args:
        query: Search query string.
        max_results: Maximum number of repositories to return.
        github_token: Optional GitHub personal access token.

    Returns:
        Dict with ``status``, ``results``, and ``count`` keys.
    """
    try:
        scraper = GitHubRepositoryScraper(github_token=github_token)
        results = scraper.search_repositories(query=query, max_results=max_results)
        return {"status": "success", "results": results, "count": len(results)}
    except Exception as exc:
        logger.error("search_repositories failed: %s", exc)
        return {"status": "error", "error": str(exc), "results": []}
