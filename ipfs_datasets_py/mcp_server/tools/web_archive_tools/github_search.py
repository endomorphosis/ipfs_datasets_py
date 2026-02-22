"""GitHub API search tools — thin MCP wrapper.

All domain logic lives at:
  ipfs_datasets_py.web_archiving.github_search_engine
"""
from ipfs_datasets_py.web_archiving.github_search_engine import (  # noqa: F401
    batch_search_github,
    search_github_code,
    search_github_issues,
    search_github_repositories,
    search_github_users,
)

__all__ = [
    "search_github_repositories",
    "search_github_code",
    "search_github_users",
    "search_github_issues",
    "batch_search_github",
]
