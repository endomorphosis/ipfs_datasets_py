#!/usr/bin/env python3
"""
P2P Cache System Monitor

Real-time monitoring of P2P cache system in production.
Shows cache statistics, P2P status, and performance metrics.
"""

import os
import sys
import time
import signal
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Enable P2P
os.environ['CACHE_ENABLE_P2P'] = 'true'
os.environ['P2P_LISTEN_PORT'] = '9000'

from ipfs_accelerate_py.github_cli.cache import get_global_cache

def signal_handler(sig, frame):
    print('\n\nMonitoring stopped.')
    sys.exit(0)

def print_banner():
    print("\n" + "="*70)
    print("  P2P CACHE SYSTEM - PRODUCTION MONITOR")
    print("="*70)
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")

def print_stats(cache):
    """Print cache statistics"""
    stats = cache.get_stats()
    
    print("📊 CACHE STATISTICS")
    print("-" * 70)
    print(f"  Cache Size:        {stats['cache_size']:,} entries")
    print(f"  Max Size:          {stats['max_cache_size']:,} entries")
    print(f"  Fill Rate:         {stats['cache_size']/stats['max_cache_size']*100:.1f}%")
    print()
    print(f"  Total Requests:    {stats['total_requests']:,}")
    print(f"  Local Hits:        {stats.get('local_hits', stats['hits']):,}")
    print(f"  Peer Hits:         {stats['peer_hits']:,}")
    print(f"  Misses:            {stats['misses']:,}")
    print(f"  Hit Rate:          {stats['hit_rate']*100:.1f}%")
    print()
    print(f"  Expirations:       {stats['expirations']:,}")
    print(f"  Evictions:         {stats['evictions']:,}")
    print(f"  API Calls Saved:   {stats['api_calls_saved']:,}")
    print()
    
    # P2P Status
    print("🌐 P2P NETWORKING")
    print("-" * 70)
    p2p_status = "✅ ENABLED" if stats['p2p_enabled'] else "❌ DISABLED"
    print(f"  P2P Status:        {p2p_status}")
    
    if stats['p2p_enabled']:
        connected_peers = stats.get('connected_peers', 0)
        print(f"  Connected Peers:   {connected_peers}")
        if connected_peers > 0:
            print(f"  Peer Cache Hits:   {stats['peer_hits']}")
            peer_hit_rate = stats['peer_hits'] / stats['total_requests'] * 100 if stats['total_requests'] > 0 else 0
            print(f"  Peer Hit Rate:     {peer_hit_rate:.1f}%")
    else:
        print(f"  Reason:            P2P initialization pending or failed")
        print(f"  Note:              Cache still works in local-only mode")
    print()
    
    # Encryption Status
    print("🔒 SECURITY")
    print("-" * 70)
    if hasattr(cache, '_cipher') and cache._cipher:
        print(f"  Encryption:        ✅ ENABLED (Fernet AES-128-CBC)")
        print(f"  Key Derivation:    PBKDF2-HMAC-SHA256 (100k iterations)")
        print(f"  Authorization:     GitHub token as shared secret")
    else:
        print(f"  Encryption:        ⚠️  NOT ENABLED")
        print(f"  Reason:            GITHUB_TOKEN not available")
        print(f"  Impact:            P2P messages sent unencrypted")
    print()
    
    # Performance Metrics
    if stats['total_requests'] > 0:
        print("⚡ PERFORMANCE")
        print("-" * 70)
        
        # Calculate API reduction
        api_reduction = stats['api_calls_saved'] / (stats['api_calls_saved'] + stats['misses']) * 100 if (stats['api_calls_saved'] + stats['misses']) > 0 else 0
        print(f"  API Reduction:     {api_reduction:.1f}%")
        
        # Estimated time saved (assuming 200ms per API call)
        time_saved = stats['api_calls_saved'] * 0.2
        print(f"  Time Saved:        {time_saved:.1f}s")
        
        # Rate limit impact
        print(f"  Rate Limit Impact: -{stats['api_calls_saved']} API calls")
        print()

def monitor_loop(interval=10):
    """Monitor cache in a loop"""
    print_banner()
    
    # Get cache
    cache = get_global_cache()
    
    print("✅ Cache initialized successfully")
    print(f"   Monitoring interval: {interval} seconds")
    print(f"   Press Ctrl+C to stop\n")
    
    iteration = 0
    
    try:
        while True:
            iteration += 1
            
            if iteration > 1:
                print("\n" + "="*70)
                print(f"  UPDATE #{iteration} - {time.strftime('%H:%M:%S')}")
                print("="*70 + "\n")
            
            print_stats(cache)
            
            if iteration == 1:
                print("💡 TIP: Use the cache by running GitHub autoscaler or API calls")
                print("   The cache will automatically store responses and share via P2P")
                print()
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        signal_handler(None, None)

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Monitor P2P cache system')
    parser.add_argument('--interval', type=int, default=10, 
                       help='Update interval in seconds (default: 10)')
    parser.add_argument('--once', action='store_true',
                       help='Print stats once and exit')
    
    args = parser.parse_args()
    
    # Register signal handler
    signal.signal(signal.SIGINT, signal_handler)
    
    if args.once:
        print_banner()
        cache = get_global_cache()
        print_stats(cache)
    else:
        monitor_loop(args.interval)

if __name__ == '__main__':
    main()
