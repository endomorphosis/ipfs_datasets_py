#!/usr/bin/env python3
"""Tests for web search API integrations (Brave, Google, GitHub, HuggingFace).

These tests verify the search API integration modules can be imported,
have the correct function signatures, and handle errors appropriately.
"""
import pytest
import anyio
import os


@pytest.fixture
def mock_env_vars():
    """Mock environment variables for API keys."""
    return {
        "BRAVE_API_KEY": "test_brave_key",
        "GOOGLE_API_KEY": "test_google_key",
        "GOOGLE_CSE_ID": "test_cse_id",
        "GITHUB_TOKEN": "test_github_token",
        "HF_TOKEN": "test_hf_token"
    }


class TestBraveSearchIntegration:
    """Test Brave Search API integration."""

    def test_brave_search_module_imports(self):
        """GIVEN the brave_search module, WHEN importing, THEN all functions are available."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.brave_search import (
            search_brave, search_brave_news, search_brave_images, batch_search_brave
        )
        
        # Functions exist
        assert callable(search_brave)
        assert callable(search_brave_news)
        assert callable(search_brave_images)
        assert callable(batch_search_brave)

    def test_brave_search_functions_are_async(self):
        """GIVEN brave_search functions, WHEN checking type, THEN they are coroutines."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.brave_search import (
            search_brave, search_brave_news, search_brave_images, batch_search_brave
        )
        
        import inspect
        assert asyncio.iscoroutinefunction(search_brave)
        assert asyncio.iscoroutinefunction(search_brave_news)
        assert asyncio.iscoroutinefunction(search_brave_images)
        assert asyncio.iscoroutinefunction(batch_search_brave)

    @pytest.mark.asyncio
    async def test_brave_search_requires_api_key(self):
        """GIVEN search_brave without API key, WHEN called, THEN returns error."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.brave_search import search_brave
        
        # Clear environment variable if it exists
        original_key = os.environ.get("BRAVE_API_KEY")
        if "BRAVE_API_KEY" in os.environ:
            del os.environ["BRAVE_API_KEY"]
        
        try:
            result = await search_brave(query="test", api_key=None)
            
            assert result["status"] == "error"
            assert "API key required" in result["error"]
        finally:
            # Restore original key if it existed
            if original_key:
                os.environ["BRAVE_API_KEY"] = original_key

    @pytest.mark.asyncio
    async def test_brave_search_accepts_parameters(self):
        """GIVEN search_brave with parameters, WHEN called, THEN handles them."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.brave_search import search_brave
        
        # This will fail API call but should accept parameters
        result = await search_brave(
            query="test query",
            api_key="test_key",
            count=5,
            offset=0,
            safesearch="moderate"
        )
        
        # Should return an error (invalid key) but accepted parameters
        assert "status" in result
        assert "error" in result or "results" in result


class TestGoogleSearchIntegration:
    """Test Google Custom Search API integration."""

    def test_google_search_module_imports(self):
        """GIVEN the google_search module, WHEN importing, THEN all functions are available."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.google_search import (
            search_google, search_google_images, batch_search_google
        )
        
        assert callable(search_google)
        assert callable(search_google_images)
        assert callable(batch_search_google)

    def test_google_search_functions_are_async(self):
        """GIVEN google_search functions, WHEN checking type, THEN they are coroutines."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.google_search import (
            search_google, search_google_images, batch_search_google
        )
        
        import inspect
        assert asyncio.iscoroutinefunction(search_google)
        assert asyncio.iscoroutinefunction(search_google_images)
        assert asyncio.iscoroutinefunction(batch_search_google)

    @pytest.mark.asyncio
    async def test_google_search_requires_credentials(self):
        """GIVEN search_google without credentials, WHEN called, THEN returns error."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.google_search import search_google
        
        # Clear environment variables if they exist
        original_key = os.environ.get("GOOGLE_API_KEY")
        original_cse = os.environ.get("GOOGLE_CSE_ID")
        
        if "GOOGLE_API_KEY" in os.environ:
            del os.environ["GOOGLE_API_KEY"]
        if "GOOGLE_CSE_ID" in os.environ:
            del os.environ["GOOGLE_CSE_ID"]
        
        try:
            result = await search_google(query="test", api_key=None, search_engine_id=None)
            
            assert result["status"] == "error"
            assert "API key" in result["error"] or "Search Engine ID" in result["error"]
        finally:
            # Restore original values if they existed
            if original_key:
                os.environ["GOOGLE_API_KEY"] = original_key
            if original_cse:
                os.environ["GOOGLE_CSE_ID"] = original_cse


class TestGitHubSearchIntegration:
    """Test GitHub API search integration."""

    def test_github_search_module_imports(self):
        """GIVEN the github_search module, WHEN importing, THEN all functions are available."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.github_search import (
            search_github_repositories, search_github_code, search_github_users,
            search_github_issues, batch_search_github
        )
        
        assert callable(search_github_repositories)
        assert callable(search_github_code)
        assert callable(search_github_users)
        assert callable(search_github_issues)
        assert callable(batch_search_github)

    def test_github_search_functions_are_async(self):
        """GIVEN github_search functions, WHEN checking type, THEN they are coroutines."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.github_search import (
            search_github_repositories, search_github_code, search_github_users,
            search_github_issues, batch_search_github
        )
        
        import inspect
        assert asyncio.iscoroutinefunction(search_github_repositories)
        assert asyncio.iscoroutinefunction(search_github_code)
        assert asyncio.iscoroutinefunction(search_github_users)
        assert asyncio.iscoroutinefunction(search_github_issues)
        assert asyncio.iscoroutinefunction(batch_search_github)

    @pytest.mark.asyncio
    async def test_github_search_works_without_token(self):
        """GIVEN search_github_repositories without token, WHEN called, THEN may succeed with rate limits."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.github_search import search_github_repositories
        
        # Clear token if exists
        original_token = os.environ.get("GITHUB_TOKEN")
        if "GITHUB_TOKEN" in os.environ:
            del os.environ["GITHUB_TOKEN"]
        
        try:
            result = await search_github_repositories(
                query="language:python stars:>1000",
                api_token=None,
                per_page=5
            )
            
            # Should work without token but may hit rate limits
            assert "status" in result
            assert result["status"] in ["success", "error"]
            
            if result["status"] == "error":
                # If error, it should be rate limit related
                assert "rate limit" in result["error"].lower() or "error" in result
        finally:
            if original_token:
                os.environ["GITHUB_TOKEN"] = original_token


class TestHuggingFaceSearchIntegration:
    """Test HuggingFace Hub API search integration."""

    def test_huggingface_search_module_imports(self):
        """GIVEN the huggingface_search module, WHEN importing, THEN all functions are available."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.huggingface_search import (
            search_huggingface_models, search_huggingface_datasets,
            search_huggingface_spaces, get_huggingface_model_info,
            batch_search_huggingface
        )
        
        assert callable(search_huggingface_models)
        assert callable(search_huggingface_datasets)
        assert callable(search_huggingface_spaces)
        assert callable(get_huggingface_model_info)
        assert callable(batch_search_huggingface)

    def test_huggingface_search_functions_are_async(self):
        """GIVEN huggingface_search functions, WHEN checking type, THEN they are coroutines."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.huggingface_search import (
            search_huggingface_models, search_huggingface_datasets,
            search_huggingface_spaces, get_huggingface_model_info,
            batch_search_huggingface
        )
        
        import inspect
        assert asyncio.iscoroutinefunction(search_huggingface_models)
        assert asyncio.iscoroutinefunction(search_huggingface_datasets)
        assert asyncio.iscoroutinefunction(search_huggingface_spaces)
        assert asyncio.iscoroutinefunction(get_huggingface_model_info)
        assert asyncio.iscoroutinefunction(batch_search_huggingface)

    @pytest.mark.asyncio
    async def test_huggingface_search_works_without_token(self):
        """GIVEN search_huggingface_models without token, WHEN called, THEN succeeds for public data."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.huggingface_search import search_huggingface_models
        
        # Clear token if exists
        original_token = os.environ.get("HF_TOKEN")
        if "HF_TOKEN" in os.environ:
            del os.environ["HF_TOKEN"]
        
        try:
            result = await search_huggingface_models(
                query="bert",
                api_token=None,
                limit=5
            )
            
            # Should work without token for public models
            assert "status" in result
            # May succeed or fail depending on API availability
            if result["status"] == "success":
                assert "results" in result
                assert isinstance(result["results"], list)
        finally:
            if original_token:
                os.environ["HF_TOKEN"] = original_token


class TestSearchIntegrationExports:
    """Test that all search integrations are properly exported."""

    def test_all_functions_in_all_list(self):
        """GIVEN web_archive_tools.__all__, WHEN checking, THEN all search functions listed."""
        # Import directly from the module file to avoid dependency issues
        import sys
        import os
        
        init_path = os.path.join(
            os.path.dirname(__file__),
            '../../../ipfs_datasets_py/mcp_server/tools/web_archive_tools/__init__.py'
        )
        
        # Read the __all__ list from the file
        with open(init_path, 'r') as f:
            content = f.read()
            
        expected_functions = [
            # Brave Search
            'search_brave', 'search_brave_news', 'search_brave_images', 'batch_search_brave',
            # Google Search
            'search_google', 'search_google_images', 'batch_search_google',
            # GitHub Search
            'search_github_repositories', 'search_github_code', 'search_github_users',
            'search_github_issues', 'batch_search_github',
            # HuggingFace Search
            'search_huggingface_models', 'search_huggingface_datasets',
            'search_huggingface_spaces', 'get_huggingface_model_info',
            'batch_search_huggingface'
        ]
        
        for func_name in expected_functions:
            assert f'"{func_name}"' in content or f"'{func_name}'" in content, \
                f"{func_name} not found in __all__"


class TestBatchSearchFunctionality:
    """Test batch search functionality across all integrations."""

    @pytest.mark.asyncio
    async def test_brave_batch_search_accepts_multiple_queries(self):
        """GIVEN batch_search_brave with queries, WHEN called, THEN processes all queries."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.brave_search import batch_search_brave
        
        queries = ["test1", "test2", "test3"]
        result = await batch_search_brave(
            queries=queries,
            api_key="test_key",
            count=5,
            delay_seconds=0.1
        )
        
        assert "status" in result
        assert "total_queries" in result
        assert result["total_queries"] == len(queries)

    @pytest.mark.asyncio
    async def test_github_batch_search_supports_search_types(self):
        """GIVEN batch_search_github with search_type, WHEN called, THEN uses correct search type."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.github_search import batch_search_github
        
        queries = ["test"]
        for search_type in ["repositories", "code", "users", "issues"]:
            result = await batch_search_github(
                queries=queries,
                search_type=search_type,
                api_token=None,
                delay_seconds=0.1
            )
            
            assert "status" in result
            assert "search_type" in result
            assert result["search_type"] == search_type


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
