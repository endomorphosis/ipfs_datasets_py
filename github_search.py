"""Compatibility shim for legacy top-level ``github_search`` imports."""

from ipfs_datasets_py.processors.web_archiving.github_search_engine import (
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
