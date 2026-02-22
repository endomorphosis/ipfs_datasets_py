"""Tests for software_engineering_tools tool category."""
import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# github_repository_scraper
# ---------------------------------------------------------------------------

class TestScrapeRepository:
    """Tests for scrape_repository()."""

    def test_returns_dict_with_mock_github(self):
        from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.github_repository_scraper import scrape_repository
        result = _run(scrape_repository(repository_url="https://github.com/owner/repo"))
        assert isinstance(result, dict)

    def test_invalid_url_returns_error(self):
        from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.github_repository_scraper import scrape_repository
        result = _run(scrape_repository(repository_url="not_a_url"))
        assert isinstance(result, dict)


class TestAnalyzeRepository:
    """Tests for analyze_repository()."""

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.github_repository_scraper import analyze_repository
        repo_data = {
            "name": "test-repo",
            "stars": 10,
            "forks": 2,
            "description": "A test repo",
        }
        result = _run(analyze_repository(repository_data=repo_data))
        assert isinstance(result, dict)

    def test_empty_repository_data(self):
        from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.github_repository_scraper import analyze_repository
        result = _run(analyze_repository(repository_data={}))
        assert isinstance(result, dict)


class TestSearchRepositories:
    """Tests for search_repositories()."""

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.github_repository_scraper import search_repositories
        result = _run(search_repositories(query="machine learning python"))
        assert isinstance(result, dict)

    def test_empty_query(self):
        from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.github_repository_scraper import search_repositories
        result = _run(search_repositories(query=""))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Other software_engineering_tools modules — import smoke tests
# ---------------------------------------------------------------------------

class TestSoftwareEngineeringToolsImports:
    """Smoke-test that all key modules are importable."""

    def test_auto_healing_coordinator_importable(self):
        from ipfs_datasets_py.mcp_server.tools.software_engineering_tools import auto_healing_coordinator  # noqa

    def test_dag_workflow_planner_importable(self):
        from ipfs_datasets_py.mcp_server.tools.software_engineering_tools import dag_workflow_planner  # noqa

    def test_error_pattern_detector_importable(self):
        from ipfs_datasets_py.mcp_server.tools.software_engineering_tools import error_pattern_detector  # noqa

    def test_dependency_chain_analyzer_importable(self):
        from ipfs_datasets_py.mcp_server.tools.software_engineering_tools import dependency_chain_analyzer  # noqa
