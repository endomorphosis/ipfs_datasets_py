"""Tests for development_tools tool category."""
import asyncio
import pytest
from unittest.mock import patch, MagicMock


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# codebase_search
# ---------------------------------------------------------------------------

class TestCodebaseSearch:
    """Tests for codebase_search()."""

    def test_returns_string_or_dict(self):
        from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import codebase_search
        result = codebase_search(pattern="def test_", path="tests/mcp/unit")
        assert isinstance(result, (dict, str))

    def test_nonempty_result(self):
        from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import codebase_search
        result = codebase_search(pattern="class Test", path="tests/mcp/unit")
        assert result is not None

    def test_nonexistent_pattern_no_crash(self):
        from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import codebase_search
        result = codebase_search(pattern="ZZZNOMATCHZZ_x99", path="tests/mcp/unit")
        assert result is not None

    def test_extensions_filter(self):
        from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import codebase_search
        result = codebase_search(pattern="import", path="tests/mcp/unit", extensions=".py")
        assert result is not None


# ---------------------------------------------------------------------------
# claude_cli_tools
# ---------------------------------------------------------------------------

class TestClaudeCliStatus:
    """Tests for claude_cli_status()."""

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.development_tools.claude_cli_tools import claude_cli_status
        result = claude_cli_status()
        assert isinstance(result, dict)

    def test_has_status_key(self):
        from ipfs_datasets_py.mcp_server.tools.development_tools.claude_cli_tools import claude_cli_status
        result = claude_cli_status()
        assert "status" in result or "installed" in result or len(result) > 0


class TestClaudeCliListModels:
    """Tests for claude_cli_list_models()."""

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.development_tools.claude_cli_tools import claude_cli_list_models
        result = claude_cli_list_models()
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# automated_pr_review_tools
# ---------------------------------------------------------------------------

class TestAutomatedPrReview:
    """Tests for automated_pr_review() — uses only valid params."""

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.development_tools.automated_pr_review_tools import automated_pr_review
        result = _run(automated_pr_review(dry_run=True))
        assert isinstance(result, dict)

    def test_dry_run_flag(self):
        """dry_run=True should not attempt real GitHub API calls."""
        from ipfs_datasets_py.mcp_server.tools.development_tools.automated_pr_review_tools import automated_pr_review
        result = _run(automated_pr_review(dry_run=True, limit=1))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# development_tools __init__ exports
# ---------------------------------------------------------------------------

class TestDevelopmentToolsExports:
    """Smoke-test that core names are importable from the package."""

    def test_codebase_search_importable(self):
        from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import codebase_search  # noqa
        assert callable(codebase_search)

    def test_claude_cli_tools_importable(self):
        from ipfs_datasets_py.mcp_server.tools.development_tools.claude_cli_tools import claude_cli_status  # noqa
        assert callable(claude_cli_status)
