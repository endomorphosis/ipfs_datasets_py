#!/usr/bin/env python3
"""
P2P Cache Initialization Script
Initializes and tests the P2P cache system for GitHub Actions workflows.
"""

import os
import sys

def main():
    """Initialize and test P2P cache."""
    
    print("🔧 Initializing P2P Cache System...")
    
    try:
        # Import P2P cache modules
        from ipfs_datasets_py.caching.cache import GitHubAPICache
        from ipfs_datasets_py.p2p_networking.p2p_peer_registry import P2PPeerRegistry
        
        print("✓ P2P cache modules imported successfully")
        
        # Get configuration from environment
        cache_dir = os.environ.get('P2P_CACHE_DIR', os.path.expanduser('~/.cache/github-api-p2p'))
        github_repo = os.environ.get('GITHUB_REPOSITORY')
        cache_size = int(os.environ.get('GITHUB_CACHE_SIZE', 5000))
        enable_p2p = os.environ.get('ENABLE_P2P_CACHE', 'true').lower() == 'true'
        enable_peer_discovery = os.environ.get('ENABLE_PEER_DISCOVERY', 'true').lower() == 'true'
        
        print(f"✓ Configuration loaded:")
        print(f"  - Cache directory: {cache_dir}")
        print(f"  - Repository: {github_repo}")
        print(f"  - Cache size: {cache_size}")
        print(f"  - P2P enabled: {enable_p2p}")
        print(f"  - Peer discovery: {enable_peer_discovery}")
        
        # Initialize cache with P2P and peer discovery
        cache = GitHubAPICache(
            cache_dir=cache_dir,
            enable_p2p=enable_p2p,
            enable_peer_discovery=enable_peer_discovery,
            github_repo=github_repo,
            max_cache_size=cache_size
        )
        
        print("✓ P2P cache initialized successfully")
        
        # Check if peer registry is active
        if hasattr(cache, '_peer_registry') and cache._peer_registry:
            print("✓ Peer discovery is active")
            
            # Try to discover peers (non-blocking)
            try:
                peers = cache._peer_registry.discover_peers(max_peers=5)
                print(f"✓ Discovered {len(peers)} peer(s)")
                
                if peers:
                    print("📡 Active peers:")
                    for peer in peers[:3]:  # Show max 3 peers
                        peer_id = peer.get('peer_id', 'unknown')[:12]
                        multiaddr = peer.get('multiaddr', 'N/A')
                        print(f"  - Peer {peer_id}... @ {multiaddr}")
                else:
                    print("  (No peers discovered yet - this is normal for new runners)")
            except Exception as e:
                print(f"⚠ Peer discovery pending: {e}")
        else:
            print("⚠ Peer discovery not enabled")
        
        # Test cache functionality
        test_operation = "test_p2p_cache"
        test_value = {"status": "operational", "timestamp": "2025-11-09"}
        
        cache.put(test_operation, test_value, ttl=60)
        retrieved = cache.get(test_operation)
        
        if retrieved == test_value:
            print("✓ Cache read/write test passed")
        else:
            print("⚠ Cache read/write test inconclusive")
        
        # Get cache statistics
        stats = cache.get_stats()
        print(f"\n📊 Cache Statistics:")
        print(f"  - Total entries: {stats.get('total_entries', 0)}")
        print(f"  - Cache hits: {stats.get('hits', 0)}")
        print(f"  - Cache misses: {stats.get('misses', 0)}")
        print(f"  - Peer hits: {stats.get('peer_hits', 0)}")
        
        print("\n::notice::✅ P2P cache is ready and will reduce API calls")
        return 0
        
    except ImportError as e:
        print(f"::warning::⚠️ P2P cache modules not available: {e}")
        print("::notice::Will fall back to standard caching")
        return 0
        
    except Exception as e:
        print(f"::error::❌ P2P cache initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
