"""
Web Archiving package — canonical location for web search and archiving engine classes.

Engine classes:
    - BraveSearchAPI            (brave_search_engine.py)
    - SerpStackSearchAPI        (serpstack_engine.py)
    - OpenVerseSearchAPI        (openverse_engine.py)
    - GitHubRepositoryScraper   (github_repository_engine.py)
    - scrape_github_repository  (github_repository_engine.py)
    - analyze_repository_health (github_repository_engine.py)

MCP tool wrappers live in:
    ipfs_datasets_py/mcp_server/tools/web_archive_tools/
    ipfs_datasets_py/mcp_server/tools/software_engineering_tools/
"""

from .brave_search_engine import BraveSearchAPI  # noqa: F401
from .serpstack_engine import SerpStackSearchAPI  # noqa: F401
from .openverse_engine import OpenVerseSearchAPI  # noqa: F401
from .github_repository_engine import (  # noqa: F401
    GitHubRepositoryScraper,
    analyze_repository_health,
    scrape_github_repository,
)

__all__ = [
    "BraveSearchAPI",
    "SerpStackSearchAPI",
    "OpenVerseSearchAPI",
    "GitHubRepositoryScraper",
    "scrape_github_repository",
    "analyze_repository_health",
]
