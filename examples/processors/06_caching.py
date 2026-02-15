"""
Smart Caching Configuration Examples
====================================

This example demonstrates the smart caching capabilities in UniversalProcessor,
including TTL, eviction policies, and cache statistics.
"""

import asyncio
import time
from ipfs_datasets_py.processors import UniversalProcessor
from ipfs_datasets_py.processors.universal_processor import ProcessorConfig


async def example_1_basic_caching():
    """Example 1: Basic caching."""
    print("\n" + "=" * 70)
    print("Example 1: Basic Caching")
    print("=" * 70)
    
    config = ProcessorConfig(
        enable_caching=True,
        cache_size_mb=100,  # 100MB cache
        cache_ttl_seconds=3600  # 1 hour TTL
    )
    
    processor = UniversalProcessor(config)
    
    print(f"✓ Cache configured:")
    print(f"  - Size limit: {config.cache_size_mb} MB")
    print(f"  - TTL: {config.cache_ttl_seconds} seconds ({config.cache_ttl_seconds/60:.0f} minutes)")
    
    # First processing - cache miss
    print("\n  Processing 'example.pdf' (first time)...")
    # await processor.process("example.pdf")  # Uncomment for real processing
    print("  ✓ Processed and cached")
    
    # Second processing - cache hit
    print("\n  Processing 'example.pdf' (second time)...")
    # await processor.process("example.pdf")  # Uncomment for real processing
    print("  ✓ Retrieved from cache (much faster!)")
    
    # Get statistics
    stats = processor.get_statistics()
    print(f"\n  Cache statistics:")
    print(f"  - Total calls: {stats['total_calls']}")
    print(f"  - Cache hits: {stats['cache_hits']}")


async def example_2_eviction_policies():
    """Example 2: Cache eviction policies."""
    print("\n" + "=" * 70)
    print("Example 2: Cache Eviction Policies")
    print("=" * 70)
    
    policies = ["lru", "lfu", "fifo"]
    
    for policy in policies:
        config = ProcessorConfig(
            enable_caching=True,
            cache_size_mb=10,  # Small cache to trigger eviction
            cache_eviction_policy=policy
        )
        
        processor = UniversalProcessor(config)
        
        print(f"\n{policy.upper()} Policy:")
        if policy == "lru":
            print("  - Evicts Least Recently Used entries")
            print("  - Best for: Most recently accessed data is likely needed again")
        elif policy == "lfu":
            print("  - Evicts Least Frequently Used entries")
            print("  - Best for: Most frequently accessed data is most important")
        else:  # fifo
            print("  - Evicts oldest entries First")
            print("  - Best for: Simple, predictable behavior")


async def example_3_ttl_configuration():
    """Example 3: TTL (Time-To-Live) configuration."""
    print("\n" + "=" * 70)
    print("Example 3: TTL Configuration")
    print("=" * 70)
    
    # Short TTL for frequently changing data
    config_short = ProcessorConfig(
        enable_caching=True,
        cache_ttl_seconds=300  # 5 minutes
    )
    
    print("Short TTL (5 minutes):")
    print("  - Use for: Frequently updated data")
    print("  - Example: Live news feeds, real-time data")
    
    # Medium TTL for moderately stable data
    config_medium = ProcessorConfig(
        enable_caching=True,
        cache_ttl_seconds=3600  # 1 hour
    )
    
    print("\nMedium TTL (1 hour):")
    print("  - Use for: Moderately stable data")
    print("  - Example: API responses, web pages")
    
    # Long TTL for stable data
    config_long = ProcessorConfig(
        enable_caching=True,
        cache_ttl_seconds=86400  # 24 hours
    )
    
    print("\nLong TTL (24 hours):")
    print("  - Use for: Stable, rarely changing data")
    print("  - Example: PDFs, archived content, static documents")
    
    # No TTL for permanent caching
    print("\nNote: TTL must be between 1 and 86400 seconds")
    print("      (Use cache clearing for manual invalidation)")


async def example_4_cache_statistics():
    """Example 4: Monitoring cache statistics."""
    print("\n" + "=" * 70)
    print("Example 4: Cache Statistics")
    print("=" * 70)
    
    config = ProcessorConfig(
        enable_caching=True,
        cache_size_mb=50
    )
    
    processor = UniversalProcessor(config)
    
    # Get cache statistics
    cache_stats = processor.get_cache_statistics()
    
    print("Available statistics:")
    print(f"  - Enabled: {cache_stats.get('enabled', False)}")
    print(f"  - Hits: {cache_stats.get('hits', 0)}")
    print(f"  - Misses: {cache_stats.get('misses', 0)}")
    print(f"  - Hit rate: {cache_stats.get('hit_rate', 0.0):.1%}")
    print(f"  - Evictions: {cache_stats.get('evictions', 0)}")
    print(f"  - Size (MB): {cache_stats.get('size_mb', 0.0):.2f}")
    print(f"  - Usage: {cache_stats.get('usage_percent', 0.0):.1f}%")
    
    print("\nUse these metrics to:")
    print("  • Monitor cache effectiveness")
    print("  • Tune cache size")
    print("  • Identify cache pressure")
    print("  • Optimize TTL settings")


async def example_5_cache_management():
    """Example 5: Cache management operations."""
    print("\n" + "=" * 70)
    print("Example 5: Cache Management")
    print("=" * 70)
    
    config = ProcessorConfig(enable_caching=True)
    processor = UniversalProcessor(config)
    
    print("Cache management operations:")
    
    # Clear cache
    print("\n1. Clear entire cache:")
    print("   processor.clear_cache()")
    print("   ✓ Removes all cached entries")
    
    # Get statistics
    print("\n2. Get cache statistics:")
    print("   stats = processor.get_cache_statistics()")
    print("   ✓ Returns dict with hits, misses, size, etc.")
    
    # Disable caching
    print("\n3. Disable caching:")
    print("   config = ProcessorConfig(enable_caching=False)")
    print("   ✓ All processing will be fresh (no cache)")
    
    # Programmatic cache clearing based on conditions
    print("\n4. Conditional cache clearing:")
    print("   if cache_stats['usage_percent'] > 90:")
    print("       processor.clear_cache()")
    print("   ✓ Clear when cache is nearly full")


async def example_6_performance_optimization():
    """Example 6: Performance optimization with caching."""
    print("\n" + "=" * 70)
    print("Example 6: Performance Optimization")
    print("=" * 70)
    
    # Example: Processing the same document multiple times
    config = ProcessorConfig(
        enable_caching=True,
        cache_size_mb=200,
        cache_ttl_seconds=7200  # 2 hours
    )
    
    processor = UniversalProcessor(config)
    
    print("Scenario: Processing same document multiple times")
    print("\nWithout caching:")
    print("  Request 1: 10.5 seconds")
    print("  Request 2: 10.3 seconds")
    print("  Request 3: 10.7 seconds")
    print("  Total: 31.5 seconds")
    
    print("\nWith caching:")
    print("  Request 1: 10.5 seconds (cache miss)")
    print("  Request 2: 0.001 seconds (cache hit)")
    print("  Request 3: 0.001 seconds (cache hit)")
    print("  Total: 10.5 seconds")
    print("\n  ⚡ 67% faster with caching!")
    
    print("\nBest practices:")
    print("  • Cache stable, frequently accessed content")
    print("  • Use appropriate TTL for your data freshness needs")
    print("  • Monitor hit rate to tune cache size")
    print("  • Consider LRU for general use cases")
    print("  • Use LFU for hot data scenarios")


async def example_7_cache_sizing():
    """Example 7: Choosing the right cache size."""
    print("\n" + "=" * 70)
    print("Example 7: Cache Sizing Guidelines")
    print("=" * 70)
    
    print("Cache size recommendations:")
    
    print("\nSmall (10-50 MB):")
    print("  • For: Development, testing")
    print("  • Handles: ~10-50 PDF documents or web pages")
    print("  • Memory footprint: Minimal")
    
    print("\nMedium (100-500 MB):")
    print("  • For: Production APIs, web services")
    print("  • Handles: ~100-500 documents or pages")
    print("  • Memory footprint: Moderate")
    
    print("\nLarge (1-10 GB):")
    print("  • For: High-traffic applications")
    print("  • Handles: ~1,000-10,000 documents")
    print("  • Memory footprint: Significant")
    
    print("\nExample configurations:")
    examples = [
        ("Development", 10, "Small cache for testing"),
        ("Production API", 200, "Medium cache for common requests"),
        ("High-traffic web", 1000, "Large cache for hot content"),
    ]
    
    for name, size_mb, desc in examples:
        print(f"\n  {name}:")
        print(f"    cache_size_mb={size_mb}  # {desc}")


async def main():
    """Run all examples."""
    print("\n")
    print("=" * 70)
    print("SMART CACHING EXAMPLES")
    print("=" * 70)
    
    examples = [
        example_1_basic_caching,
        example_2_eviction_policies,
        example_3_ttl_configuration,
        example_4_cache_statistics,
        example_5_cache_management,
        example_6_performance_optimization,
        example_7_cache_sizing
    ]
    
    for example in examples:
        await example()
        await asyncio.sleep(0.1)
    
    print("\n" + "=" * 70)
    print("Examples complete!")
    print("=" * 70)
    print("\nKey Takeaways:")
    print("  • Caching can provide 50-90% performance improvement")
    print("  • Choose eviction policy based on access patterns")
    print("  • TTL prevents stale data")
    print("  • Monitor statistics to optimize configuration")
    print("  • Cache size should match your working set")
    print()


if __name__ == "__main__":
    asyncio.run(main())
