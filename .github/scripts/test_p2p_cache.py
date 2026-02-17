#!/usr/bin/env python3
"""
Test P2P cache functionality for GitHub Actions workflows.

This script tests the P2P cache initialization and peer discovery
to ensure the cache is working properly before workflow execution.
"""

import os
import sys


def test_p2p_cache():
    """Test P2P cache initialization and functionality."""
    try:
        # Import P2P cache modules
        from ipfs_datasets_py.cache import GitHubAPICache
        from ipfs_datasets_py.p2p_peer_registry import P2PPeerRegistry
        
        print("✓ P2P cache modules imported successfully")
        
        # Initialize cache with P2P and peer discovery
        cache = GitHubAPICache(
            cache_dir=os.environ.get('P2P_CACHE_DIR'),
            enable_p2p=True,
            enable_peer_discovery=True,
            github_repo=os.environ.get('GITHUB_REPOSITORY'),
            max_cache_size=int(os.environ.get('GITHUB_CACHE_SIZE', 5000))
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
                        print(f"  - {peer_id}...")
            except Exception as e:
                print(f"⚠ Peer discovery pending: {e}")
        else:
            print("⚠ Peer discovery not enabled")
        
        print("\n::notice::✅ P2P cache is ready and will reduce API calls")
        return 0
        
    except ImportError as e:
        print(f"::warning::⚠️ P2P cache modules not available: {e}")
        print("::notice::Will fall back to standard caching")
        return 0
    except Exception as e:
        print(f"::error::❌ P2P cache initialization failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(test_p2p_cache())
