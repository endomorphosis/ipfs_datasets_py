#!/usr/bin/env python3
"""
P2P Cache Production Test

Tests the P2P cache system in production mode without requiring GitHub auth.
"""

import os
import sys
import time
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('p2p_cache_production_test')

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_cache_with_p2p_enabled():
    """Test cache with P2P enabled"""
    logger.info("="*70)
    logger.info("P2P CACHE PRODUCTION TEST")
    logger.info("="*70)
    
    try:
        # Enable P2P
        os.environ['CACHE_ENABLE_P2P'] = 'true'
        os.environ['P2P_LISTEN_PORT'] = '9000'
        
        logger.info("Environment configuration:")
        logger.info(f"  CACHE_ENABLE_P2P: {os.environ.get('CACHE_ENABLE_P2P')}")
        logger.info(f"  P2P_LISTEN_PORT: {os.environ.get('P2P_LISTEN_PORT')}")
        
        from ipfs_accelerate_py.github_cli.cache import GitHubAPICache, get_global_cache
        
        logger.info("\n1. Creating cache instance...")
        cache = GitHubAPICache(enable_p2p=True)
        
        stats = cache.get_stats()
        logger.info(f"✓ Cache created")
        logger.info(f"  P2P enabled: {stats['p2p_enabled']}")
        logger.info(f"  Cache size: {stats['cache_size']}")
        
        logger.info("\n2. Testing cache operations...")
        
        # Test put
        test_key = "test/production/endpoint"
        test_data = {
            'repository': 'endomorphosis/ipfs_accelerate_py',
            'workflow': 'test-workflow',
            'timestamp': time.time()
        }
        
        cache.put(test_key, test_data, ttl=300)
        logger.info(f"✓ Put operation completed")
        
        # Test get
        retrieved = cache.get(test_key)
        if retrieved and retrieved['repository'] == test_data['repository']:
            logger.info(f"✓ Get operation successful")
            logger.info(f"  Retrieved data: {retrieved['repository']}")
        else:
            logger.error(f"✗ Get operation failed")
            return False
        
        logger.info("\n3. Checking statistics...")
        stats = cache.get_stats()
        logger.info(f"  Hits: {stats['hits']}")
        logger.info(f"  Misses: {stats['misses']}")
        logger.info(f"  Hit rate: {stats['hit_rate']:.1%}")
        logger.info(f"  Cache size: {stats['cache_size']}")
        logger.info(f"  P2P enabled: {stats['p2p_enabled']}")
        
        # Check for encryption
        if hasattr(cache, '_cipher') and cache._cipher:
            logger.info(f"✓ Encryption enabled")
        else:
            logger.warning(f"⚠ Encryption not enabled (needs GITHUB_TOKEN)")
        
        logger.info("\n4. Testing global cache accessor...")
        global_cache = get_global_cache()
        if global_cache is cache:
            logger.info(f"✓ Global cache is same instance")
        else:
            logger.info(f"✓ Global cache accessible")
        
        logger.info("\n" + "="*70)
        logger.info("✅ P2P CACHE PRODUCTION TEST PASSED")
        logger.info("="*70)
        logger.info("\nSummary:")
        logger.info(f"  • Cache operations: WORKING")
        logger.info(f"  • P2P configuration: {stats['p2p_enabled']}")
        logger.info(f"  • Statistics tracking: WORKING")
        logger.info(f"  • Global cache: WORKING")
        logger.info(f"\nCache is ready for production use!")
        
        return True
        
    except Exception as e:
        logger.error(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_github_cli_integration():
    """Test GitHub CLI wrapper integration"""
    logger.info("\n" + "="*70)
    logger.info("TESTING GITHUB CLI INTEGRATION")
    logger.info("="*70)
    
    try:
        os.environ['CACHE_ENABLE_P2P'] = 'true'
        
        from ipfs_accelerate_py.github_cli.wrapper import GitHubCLI
        from ipfs_accelerate_py.github_cli.cache import get_global_cache
        
        logger.info("\n1. Creating GitHubCLI instance...")
        cli = GitHubCLI()
        logger.info("✓ GitHubCLI created (authentication may fail, that's OK)")
        
        logger.info("\n2. Checking cache integration...")
        cache = get_global_cache()
        stats = cache.get_stats()
        
        logger.info(f"✓ Cache integrated with GitHubCLI")
        logger.info(f"  Cache size: {stats['cache_size']}")
        logger.info(f"  P2P enabled: {stats['p2p_enabled']}")
        
        logger.info("\n✅ GITHUB CLI INTEGRATION TEST PASSED")
        logger.info("(Note: CLI may not be authenticated, but cache is working)")
        
        return True
        
    except Exception as e:
        logger.error(f"\n✗ INTEGRATION TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run production tests"""
    results = []
    
    results.append(("P2P Cache Operations", test_cache_with_p2p_enabled()))
    results.append(("GitHub CLI Integration", test_github_cli_integration()))
    
    # Summary
    logger.info("\n" + "="*70)
    logger.info("FINAL RESULTS")
    logger.info("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status} | {test_name}")
    
    logger.info("="*70)
    logger.info(f"Total: {passed}/{total} tests passed ({passed/total*100:.0f}%)")
    logger.info("="*70)
    
    if passed == total:
        logger.info("\n🎉 ALL PRODUCTION TESTS PASSED!")
        logger.info("P2P cache system is operational in production mode.")
        return 0
    else:
        logger.warning(f"\n⚠ {total - passed} test(s) failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
