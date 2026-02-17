#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI Caching Demo

This script demonstrates the query caching capabilities for GitHub CLI
and Copilot CLI, showing performance improvements and cache statistics.
"""

import time
import sys
from pathlib import Path
from typing import Optional

# Add parent directory to path for running as script
sys.path.insert(0, str(Path(__file__).parent.parent))


def demo_github_cli_caching():
    """Demonstrate GitHub CLI caching with performance measurements."""
    print("=" * 70)
    print("GitHub CLI Caching Demo")
    print("=" * 70)
    print()
    
    try:
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        
        # Initialize with caching enabled
        print("1. Initializing GitHub CLI with caching enabled...")
        cli = GitHubCLI(
            enable_cache=True,
            cache_maxsize=100,
            cache_ttl=300
        )
        print(f"   ✓ Cache initialized (maxsize=100, ttl=300s)")
        print()
        
        # Check if gh is installed
        if not cli.is_installed():
            print("⚠️  GitHub CLI not installed. Run:")
            print("   python -m ipfs_datasets_py.utils.github_cli")
            print("   to install it first.")
            return
        
        # First query - will hit API
        print("2. First query (cache MISS - will execute command):")
        start = time.time()
        result1 = cli.execute(['--version'])
        elapsed1 = time.time() - start
        print(f"   Command: gh --version")
        print(f"   Time: {elapsed1*1000:.2f}ms")
        print(f"   Output: {result1.stdout.strip()[:50]}")
        print()
        
        # Second query - will use cache
        print("3. Second query (cache HIT - will use cached result):")
        start = time.time()
        result2 = cli.execute(['--version'])
        elapsed2 = time.time() - start
        print(f"   Command: gh --version")
        print(f"   Time: {elapsed2*1000:.2f}ms")
        print(f"   Speedup: {elapsed1/elapsed2:.1f}x faster")
        print()
        
        # Show cache statistics
        print("4. Cache Statistics:")
        stats = cli.get_cache_stats()
        if stats:
            print(f"   Hits: {stats['hits']}")
            print(f"   Misses: {stats['misses']}")
            print(f"   Sets: {stats['sets']}")
            print(f"   Size: {stats['size']}/{stats['maxsize']}")
            print(f"   Hit Rate: {stats['hit_rate']:.2%}")
            print()
        
        # Demonstrate cache bypass
        print("5. Query with cache bypass:")
        start = time.time()
        result3 = cli.execute(['--version'], use_cache=False)
        elapsed3 = time.time() - start
        print(f"   Command: gh --version (use_cache=False)")
        print(f"   Time: {elapsed3*1000:.2f}ms")
        print(f"   ✓ Cache bypassed, command executed")
        print()
        
        # Show updated statistics
        print("6. Updated Cache Statistics:")
        stats = cli.get_cache_stats()
        if stats:
            print(f"   Hits: {stats['hits']}")
            print(f"   Misses: {stats['misses']}")
            print(f"   Sets: {stats['sets']}")
            print(f"   Hit Rate: {stats['hit_rate']:.2%}")
        
        print()
        print("✓ GitHub CLI caching demo completed successfully!")
        
    except ImportError as e:
        print(f"❌ Error importing GitHub CLI: {e}")
        print("   Make sure dependencies are installed:")
        print("   pip install cachetools")
    except Exception as e:
        print(f"❌ Error during demo: {e}")
        import traceback
        traceback.print_exc()


def demo_copilot_cli_caching():
    """Demonstrate Copilot CLI caching."""
    print()
    print("=" * 70)
    print("Copilot CLI Caching Demo")
    print("=" * 70)
    print()
    
    try:
        from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
        
        # Initialize with caching enabled
        print("1. Initializing Copilot CLI with caching enabled...")
        copilot = CopilotCLI(
            enable_cache=True,
            cache_maxsize=100,
            cache_ttl=600  # Longer TTL for AI responses
        )
        print(f"   ✓ Cache initialized (maxsize=100, ttl=600s)")
        print()
        
        # Check if copilot is installed
        if not copilot.installed:
            print("⚠️  GitHub Copilot CLI not installed.")
            print("   Run: gh extension install github/gh-copilot")
            return
        
        # Simulate a cached code explanation
        test_code = "print('Hello, World!')"
        
        print("2. First code explanation (cache MISS):")
        print(f"   Code: {test_code}")
        start = time.time()
        result1 = copilot.explain_code(test_code)
        elapsed1 = time.time() - start
        
        if result1['success']:
            print(f"   Time: {elapsed1*1000:.2f}ms")
            print(f"   ✓ Explanation received and cached")
        else:
            print(f"   ⚠️  API call failed: {result1.get('error', 'Unknown error')}")
        print()
        
        print("3. Second code explanation (cache HIT):")
        print(f"   Code: {test_code}")
        start = time.time()
        result2 = copilot.explain_code(test_code)
        elapsed2 = time.time() - start
        
        if result2['success']:
            print(f"   Time: {elapsed2*1000:.2f}ms")
            if elapsed1 > 0:
                print(f"   Speedup: {elapsed1/elapsed2:.1f}x faster")
            print(f"   ✓ Cached result returned")
        print()
        
        # Show cache statistics
        print("4. Cache Statistics:")
        stats = copilot.get_cache_stats()
        if stats:
            print(f"   Hits: {stats['hits']}")
            print(f"   Misses: {stats['misses']}")
            print(f"   Sets: {stats['sets']}")
            print(f"   Hit Rate: {stats['hit_rate']:.2%}")
        
        print()
        print("✓ Copilot CLI caching demo completed!")
        
    except ImportError as e:
        print(f"❌ Error importing Copilot CLI: {e}")
    except Exception as e:
        print(f"❌ Error during demo: {e}")
        import traceback
        traceback.print_exc()


def demo_query_cache():
    """Demonstrate the QueryCache class directly."""
    print()
    print("=" * 70)
    print("QueryCache Module Demo")
    print("=" * 70)
    print()
    
    try:
        from ipfs_datasets_py.utils.query_cache import QueryCache, cached_query
        
        # Create a cache
        print("1. Creating a QueryCache instance:")
        cache = QueryCache(maxsize=10, ttl=60)
        print(f"   ✓ Cache created (maxsize=10, ttl=60s)")
        print()
        
        # Basic set/get operations
        print("2. Basic cache operations:")
        cache.set("key1", "value1")
        cache.set("key2", {"data": "value2"})
        print("   ✓ Set key1 = 'value1'")
        print("   ✓ Set key2 = {'data': 'value2'}")
        print()
        
        value1 = cache.get("key1")
        value2 = cache.get("key2")
        print(f"   Get key1: {value1}")
        print(f"   Get key2: {value2}")
        print()
        
        # Test cache miss
        print("3. Cache miss:")
        missing = cache.get("nonexistent")
        print(f"   Get nonexistent: {missing}")
        print()
        
        # Show statistics
        print("4. Cache Statistics:")
        stats = cache.get_stats()
        print(f"   Hits: {stats['hits']}")
        print(f"   Misses: {stats['misses']}")
        print(f"   Sets: {stats['sets']}")
        print(f"   Size: {stats['size']}/{stats['maxsize']}")
        print(f"   Hit Rate: {stats['hit_rate']:.2%}")
        print()
        
        # Demonstrate decorator
        print("5. Using @cached_query decorator:")
        call_count = [0]
        
        @cached_query(cache)
        def expensive_function(x, y):
            """Simulates an expensive operation."""
            call_count[0] += 1
            time.sleep(0.1)  # Simulate delay
            return x + y
        
        print("   First call (will execute function):")
        start = time.time()
        result1 = expensive_function(5, 3)
        elapsed1 = time.time() - start
        print(f"   Result: {result1}, Time: {elapsed1*1000:.2f}ms")
        
        print("   Second call (will use cache):")
        start = time.time()
        result2 = expensive_function(5, 3)
        elapsed2 = time.time() - start
        print(f"   Result: {result2}, Time: {elapsed2*1000:.2f}ms")
        print(f"   Speedup: {elapsed1/elapsed2:.1f}x faster")
        print(f"   Function called {call_count[0]} time(s)")
        
        print()
        print("✓ QueryCache demo completed!")
        
    except ImportError as e:
        print(f"❌ Error importing QueryCache: {e}")
    except Exception as e:
        print(f"❌ Error during demo: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Run all caching demos."""
    print()
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 15 + "CLI Query Caching Demo Suite" + " " * 25 + "║")
    print("╚" + "═" * 68 + "╝")
    print()
    print("This demo showcases the query caching functionality for:")
    print("  • GitHub CLI (gh)")
    print("  • GitHub Copilot CLI")
    print("  • QueryCache module")
    print()
    
    # Run demos
    demo_query_cache()
    demo_github_cli_caching()
    demo_copilot_cli_caching()
    
    print()
    print("=" * 70)
    print("All Demos Completed!")
    print("=" * 70)
    print()
    print("For more information, see:")
    print("  • docs/CLI_CACHING_GUIDE.md")
    print("  • ipfs_datasets_py/utils/query_cache.py")
    print("  • tests/test_query_cache.py")
    print("  • tests/test_cli_caching.py")
    print()


if __name__ == '__main__':
    main()
