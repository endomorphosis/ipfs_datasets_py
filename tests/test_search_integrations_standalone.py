#!/usr/bin/env python3
"""Standalone test script for web search API integrations.

This script tests the search integration modules without requiring
the full pytest infrastructure or other package dependencies.
"""
import sys
import os
import anyio

# Add the web_archive_tools directory to the path
web_archive_tools_path = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    '../ipfs_datasets_py/mcp_server/tools/web_archive_tools'
))
sys.path.insert(0, web_archive_tools_path)

import asyncio


def test_brave_search():
    """Test Brave Search integration."""
    print("Testing Brave Search Integration...")
    import brave_search
    
    # Test module has expected functions
    assert callable(brave_search.search_brave), "search_brave should be callable"
    assert callable(brave_search.search_brave_news), "search_brave_news should be callable"
    assert callable(brave_search.search_brave_images), "search_brave_images should be callable"
    assert callable(brave_search.batch_search_brave), "batch_search_brave should be callable"
    
    # Test functions are async
    assert asyncio.iscoroutinefunction(brave_search.search_brave), "search_brave should be async"
    assert asyncio.iscoroutinefunction(brave_search.search_brave_news), "search_brave_news should be async"
    assert asyncio.iscoroutinefunction(brave_search.search_brave_images), "search_brave_images should be async"
    assert asyncio.iscoroutinefunction(brave_search.batch_search_brave), "batch_search_brave should be async"
    
    print("  ✓ All Brave Search functions present and async")


def test_google_search():
    """Test Google Search integration."""
    print("Testing Google Search Integration...")
    import google_search
    
    # Test module has expected functions
    assert callable(google_search.search_google), "search_google should be callable"
    assert callable(google_search.search_google_images), "search_google_images should be callable"
    assert callable(google_search.batch_search_google), "batch_search_google should be callable"
    
    # Test functions are async
    assert asyncio.iscoroutinefunction(google_search.search_google), "search_google should be async"
    assert asyncio.iscoroutinefunction(google_search.search_google_images), "search_google_images should be async"
    assert asyncio.iscoroutinefunction(google_search.batch_search_google), "batch_search_google should be async"
    
    print("  ✓ All Google Search functions present and async")


def test_github_search():
    """Test GitHub Search integration."""
    print("Testing GitHub Search Integration...")
    import github_search
    
    # Test module has expected functions
    assert callable(github_search.search_github_repositories), "search_github_repositories should be callable"
    assert callable(github_search.search_github_code), "search_github_code should be callable"
    assert callable(github_search.search_github_users), "search_github_users should be callable"
    assert callable(github_search.search_github_issues), "search_github_issues should be callable"
    assert callable(github_search.batch_search_github), "batch_search_github should be callable"
    
    # Test functions are async
    assert asyncio.iscoroutinefunction(github_search.search_github_repositories), "search_github_repositories should be async"
    assert asyncio.iscoroutinefunction(github_search.search_github_code), "search_github_code should be async"
    assert asyncio.iscoroutinefunction(github_search.search_github_users), "search_github_users should be async"
    assert asyncio.iscoroutinefunction(github_search.search_github_issues), "search_github_issues should be async"
    assert asyncio.iscoroutinefunction(github_search.batch_search_github), "batch_search_github should be async"
    
    print("  ✓ All GitHub Search functions present and async")


def test_huggingface_search():
    """Test HuggingFace Search integration."""
    print("Testing HuggingFace Search Integration...")
    import huggingface_search
    
    # Test module has expected functions
    assert callable(huggingface_search.search_huggingface_models), "search_huggingface_models should be callable"
    assert callable(huggingface_search.search_huggingface_datasets), "search_huggingface_datasets should be callable"
    assert callable(huggingface_search.search_huggingface_spaces), "search_huggingface_spaces should be callable"
    assert callable(huggingface_search.get_huggingface_model_info), "get_huggingface_model_info should be callable"
    assert callable(huggingface_search.batch_search_huggingface), "batch_search_huggingface should be callable"
    
    # Test functions are async
    assert asyncio.iscoroutinefunction(huggingface_search.search_huggingface_models), "search_huggingface_models should be async"
    assert asyncio.iscoroutinefunction(huggingface_search.search_huggingface_datasets), "search_huggingface_datasets should be async"
    assert asyncio.iscoroutinefunction(huggingface_search.search_huggingface_spaces), "search_huggingface_spaces should be async"
    assert asyncio.iscoroutinefunction(huggingface_search.get_huggingface_model_info), "get_huggingface_model_info should be async"
    assert asyncio.iscoroutinefunction(huggingface_search.batch_search_huggingface), "batch_search_huggingface should be async"
    
    print("  ✓ All HuggingFace Search functions present and async")


async def test_api_key_validation():
    """Test that functions properly validate API keys."""
    print("Testing API key validation...")
    import brave_search
    import google_search
    
    # Remove env vars if they exist
    for key in ['BRAVE_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_CSE_ID']:
        if key in os.environ:
            del os.environ[key]
    
    # Test Brave Search requires API key
    result = await brave_search.search_brave(query="test", api_key=None)
    assert result['status'] == 'error', "Brave search should error without API key"
    assert 'API key' in result['error'], "Error should mention API key"
    print("  ✓ Brave Search properly validates API key")
    
    # Test Google Search requires credentials
    result = await google_search.search_google(query="test", api_key=None, search_engine_id=None)
    assert result['status'] == 'error', "Google search should error without credentials"
    assert ('API key' in result['error'] or 'Search Engine ID' in result['error']), "Error should mention credentials"
    print("  ✓ Google Search properly validates credentials")


def test_exports():
    """Test that __init__.py properly exports all functions."""
    print("Testing web_archive_tools exports...")
    
    init_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__),
        '../ipfs_datasets_py/mcp_server/tools/web_archive_tools/__init__.py'
    ))
    
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
    
    print(f"  ✓ All {len(expected_functions)} search functions exported in __init__.py")


def main():
    """Run all tests."""
    print("=" * 70)
    print("Testing Web Search API Integrations")
    print("=" * 70)
    
    try:
        # Test each integration
        test_brave_search()
        test_google_search()
        test_github_search()
        test_huggingface_search()
        test_exports()
        
        # Test async functionality
        anyio.run(test_api_key_validation())
        
        print("\n" + "=" * 70)
        print("✅ All tests passed!")
        print("=" * 70)
        return 0
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
