#!/usr/bin/env python3
"""
Demo script showing web search API integrations in action.

This script demonstrates basic usage of the search integrations without
requiring API keys (uses mock searches for demo purposes).

To use with real API keys, set the environment variables:
    BRAVE_API_KEY, GOOGLE_API_KEY, GOOGLE_CSE_ID, GITHUB_TOKEN, HF_TOKEN
"""
import anyio
import sys
from pathlib import Path

# Add the repository root so demos import the canonical package modules directly.
def _find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "setup.py").is_file() and (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError(f"Could not determine repository root from {start}")


ROOT = _find_repo_root(Path(__file__).resolve().parent)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

async def demo_brave_search():
    """Demo Brave Search integration."""
    print("=" * 70)
    print("Brave Search API Demo")
    print("=" * 70)
    
    from ipfs_datasets_py.processors.web_archiving.brave_search_engine import search_brave
    
    result = await search_brave(
        query="IPFS dataset storage",
        api_key="demo_key",  # Invalid key for demo
        count=5
    )
    
    print(f"Status: {result['status']}")
    if result['status'] == 'error':
        print(f"Expected error (no valid API key): {result['error']}")
    print()


async def demo_google_search():
    """Demo Google Search integration."""
    print("=" * 70)
    print("Google Custom Search API Demo")
    print("=" * 70)
    
    from ipfs_datasets_py.processors.web_archiving.google_search_engine import search_google
    
    result = await search_google(
        query="decentralized storage",
        api_key="demo_key",
        search_engine_id="demo_id",
        num=5
    )
    
    print(f"Status: {result['status']}")
    if result['status'] == 'error':
        print(f"Expected error (no valid credentials): {result['error']}")
    print()


async def demo_github_search():
    """Demo GitHub Search integration."""
    print("=" * 70)
    print("GitHub API Search Demo")
    print("=" * 70)
    
    from ipfs_datasets_py.processors.web_archiving.github_search_engine import (
        search_github_repositories,
    )
    
    # GitHub allows limited searches without authentication
    result = await search_github_repositories(
        query="ipfs language:python",
        api_token=None,  # No token for demo
        per_page=5
    )
    
    print(f"Status: {result['status']}")
    
    if result['status'] == 'success':
        print(f"Found {result['total_count']} repositories")
        print("\nTop 5 repositories:")
        for i, repo in enumerate(result['results'][:5], 1):
            print(f"{i}. {repo['full_name']}")
            print(f"   ⭐ {repo['stars']} stars | 🔀 {repo['forks']} forks")
            print(f"   {repo['description'][:100]}..." if len(repo['description']) > 100 else f"   {repo['description']}")
    else:
        print(f"Note: {result.get('error', 'Rate limit may be exceeded')}")
    print()


async def demo_huggingface_search():
    """Demo HuggingFace Search integration."""
    print("=" * 70)
    print("HuggingFace Hub API Search Demo")
    print("=" * 70)
    
    from ipfs_datasets_py.processors.web_archiving.huggingface_search_engine import (
        search_huggingface_models,
    )
    
    # HuggingFace allows searches without authentication for public data
    result = await search_huggingface_models(
        query="bert",
        api_token=None,  # No token for demo
        limit=5
    )
    
    print(f"Status: {result['status']}")
    
    if result['status'] == 'success':
        print(f"Found {result['total_count']} models")
        print("\nTop 5 models:")
        for i, model in enumerate(result['results'][:5], 1):
            print(f"{i}. {model['model_id']}")
            print(f"   📥 {model['downloads']} downloads | ❤️ {model['likes']} likes")
            print(f"   Pipeline: {model['pipeline_tag']}")
    else:
        print(f"Note: {result.get('error', 'API may be unavailable')}")
    print()


async def demo_batch_search():
    """Demo batch search functionality."""
    print("=" * 70)
    print("Batch Search Demo (GitHub)")
    print("=" * 70)
    
    from ipfs_datasets_py.processors.web_archiving.github_search_engine import (
        batch_search_github,
    )
    
    queries = [
        "machine-learning language:python stars:>1000",
        "web3 language:javascript stars:>500"
    ]
    
    result = await batch_search_github(
        queries=queries,
        search_type="repositories",
        api_token=None,
        per_page=3,
        delay_seconds=2.0
    )
    
    print(f"Status: {result['status']}")
    print(f"Total queries: {result['total_queries']}")
    print(f"Successful: {result['success_count']}")
    print(f"Errors: {result['error_count']}")
    
    if result['status'] == 'success':
        for query, query_result in result['results'].items():
            print(f"\nQuery: {query}")
            if query_result['status'] == 'success':
                print(f"  Found {len(query_result['results'])} repositories")
            else:
                print(f"  Error: {query_result.get('error', 'Unknown error')}")
    print()


async def main():
    """Run all demos."""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "Web Search API Integrations Demo" + " " * 20 + "║")
    print("╚" + "=" * 68 + "╝")
    print()
    print("This demo shows the search integrations in action.")
    print("For full functionality, set API keys as environment variables.")
    print()
    
    try:
        # Run demos
        await demo_brave_search()
        await demo_google_search()
        await demo_github_search()
        await demo_huggingface_search()
        await demo_batch_search()
        
        print("=" * 70)
        print("Demo Complete!")
        print("=" * 70)
        print("\nFor more information, see: docs/WEB_SEARCH_API_GUIDE.md")
        print()
        
    except Exception as e:
        print(f"\n❌ Demo error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(anyio.run(main()))
