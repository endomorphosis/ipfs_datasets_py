#!/usr/bin/env python3
"""
Test P2P Cache with Encryption

This script tests the distributed P2P cache functionality including:
1. Encryption/decryption with GitHub token
2. Key derivation from GitHub token
3. Message encryption and authentication
4. Cache sharing between peers
5. Unauthorized access prevention
"""

import os
import sys
import time
import json
import logging
import tempfile
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("test_p2p_cache")


def test_encryption_dependencies():
    """Test that encryption dependencies are available."""
    logger.info("=" * 60)
    logger.info("TEST 1: Checking Encryption Dependencies")
    logger.info("=" * 60)
    
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        logger.info("✓ cryptography package available")
        return True
    except ImportError as e:
        logger.error(f"✗ cryptography package not available: {e}")
        logger.error("  Install with: pip install cryptography")
        return False


def test_multiformats_dependencies():
    """Test that multiformats dependencies are available."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 2: Checking Multiformats Dependencies")
    logger.info("=" * 60)
    
    try:
        from multiformats import CID, multihash
        logger.info("✓ multiformats package available")
        return True
    except ImportError as e:
        logger.warning(f"⚠ multiformats package not available: {e}")
        logger.warning("  Optional but recommended: pip install py-multiformats-cid")
        return False


def test_libp2p_dependencies():
    """Test that libp2p dependencies are available."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 3: Checking libp2p Dependencies")
    logger.info("=" * 60)
    
    try:
        from libp2p import new_host
        logger.info("✓ libp2p package available")
        return True
    except ImportError as e:
        logger.warning(f"⚠ libp2p package not available: {e}")
        logger.warning("  Optional but required for P2P: pip install libp2p")
        return False


def test_github_token_available():
    """Test that GitHub token is available."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 4: Checking GitHub Token Availability")
    logger.info("=" * 60)
    
    # Check environment variable
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        logger.info("✓ GITHUB_TOKEN environment variable set")
        logger.info(f"  Token prefix: {token[:10]}...")
        return True
    
    # Try gh CLI
    try:
        import subprocess
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            token = result.stdout.strip()
            logger.info("✓ GitHub token available from gh CLI")
            logger.info(f"  Token prefix: {token[:10]}...")
            # Set for other tests
            os.environ["GITHUB_TOKEN"] = token
            return True
    except Exception as e:
        logger.debug(f"Failed to get token from gh CLI: {e}")
    
    logger.error("✗ GitHub token not available")
    logger.error("  Set GITHUB_TOKEN environment variable or run 'gh auth login'")
    return False


def test_encryption_key_derivation():
    """Test encryption key derivation from GitHub token."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 5: Testing Encryption Key Derivation")
    logger.info("=" * 60)
    
    try:
        from ipfs_accelerate_py.github_cli.cache import GitHubAPICache
        
        # Create cache with encryption
        cache_dir = tempfile.mkdtemp(prefix="test_cache_")
        cache = GitHubAPICache(
            cache_dir=cache_dir,
            enable_persistence=False,
            enable_p2p=False  # Don't start P2P for this test
        )
        
        # Try to initialize encryption
        try:
            cache._init_encryption()
            logger.info("✓ Encryption key derived successfully")
            
            if cache._cipher:
                logger.info("✓ Fernet cipher created")
                logger.info(f"  Cipher type: {type(cache._cipher).__name__}")
            else:
                logger.error("✗ Fernet cipher is None")
                return False
            
            return True
        except Exception as e:
            logger.error(f"✗ Failed to initialize encryption: {e}")
            return False
    
    except Exception as e:
        logger.error(f"✗ Failed to create cache: {e}")
        return False


def test_message_encryption_decryption():
    """Test message encryption and decryption."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 6: Testing Message Encryption/Decryption")
    logger.info("=" * 60)
    
    try:
        from ipfs_accelerate_py.github_cli.cache import GitHubAPICache
        
        cache_dir = tempfile.mkdtemp(prefix="test_cache_")
        cache = GitHubAPICache(
            cache_dir=cache_dir,
            enable_persistence=False,
            enable_p2p=False
        )
        
        cache._init_encryption()
        
        # Test message
        test_message = {
            "key": "test_key",
            "entry": {
                "data": {"repos": ["repo1", "repo2"]},
                "timestamp": time.time(),
                "ttl": 300
            }
        }
        
        # Encrypt
        logger.info("Encrypting test message...")
        encrypted = cache._encrypt_message(test_message)
        logger.info(f"✓ Message encrypted: {len(encrypted)} bytes")
        logger.info(f"  Encrypted data (first 50 bytes): {encrypted[:50].hex()}")
        
        # Verify it's actually encrypted (not plaintext)
        plaintext = json.dumps(test_message).encode('utf-8')
        if encrypted == plaintext:
            logger.error("✗ Message not actually encrypted!")
            return False
        logger.info("✓ Message is encrypted (differs from plaintext)")
        
        # Decrypt
        logger.info("Decrypting message...")
        decrypted = cache._decrypt_message(encrypted)
        logger.info(f"✓ Message decrypted")
        
        # Verify decryption matches original
        if decrypted == test_message:
            logger.info("✓ Decrypted message matches original")
            return True
        else:
            logger.error("✗ Decrypted message doesn't match original")
            logger.error(f"  Original: {test_message}")
            logger.error(f"  Decrypted: {decrypted}")
            return False
    
    except Exception as e:
        logger.error(f"✗ Encryption/decryption test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_wrong_key_decryption():
    """Test that messages encrypted with different keys cannot be decrypted."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 7: Testing Unauthorized Decryption Prevention")
    logger.info("=" * 60)
    
    try:
        from ipfs_accelerate_py.github_cli.cache import GitHubAPICache
        from cryptography.fernet import Fernet
        
        # Create cache 1 with real GitHub token
        cache_dir1 = tempfile.mkdtemp(prefix="test_cache_1_")
        cache1 = GitHubAPICache(
            cache_dir=cache_dir1,
            enable_persistence=False,
            enable_p2p=False
        )
        cache1._init_encryption()
        
        # Create cache 2 with different key (simulating different GitHub token)
        cache_dir2 = tempfile.mkdtemp(prefix="test_cache_2_")
        cache2 = GitHubAPICache(
            cache_dir=cache_dir2,
            enable_persistence=False,
            enable_p2p=False
        )
        cache2._init_encryption()
        # Replace with different key
        cache2._cipher = Fernet(Fernet.generate_key())
        
        # Test message
        test_message = {
            "key": "test_key",
            "entry": {"data": "secret_data"}
        }
        
        # Encrypt with cache1
        logger.info("Encrypting message with key 1...")
        encrypted = cache1._encrypt_message(test_message)
        logger.info(f"✓ Message encrypted with key 1")
        
        # Try to decrypt with cache2 (wrong key)
        logger.info("Attempting to decrypt with wrong key...")
        decrypted = cache2._decrypt_message(encrypted)
        
        if decrypted is None:
            logger.info("✓ Decryption failed as expected (wrong key)")
            logger.info("✓ Unauthorized access prevented")
            return True
        else:
            logger.error("✗ Message decrypted with wrong key!")
            logger.error("  This should not happen - security breach!")
            return False
    
    except Exception as e:
        logger.error(f"✗ Wrong key test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_cache_basic_operations():
    """Test basic cache operations without P2P."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 8: Testing Basic Cache Operations")
    logger.info("=" * 60)
    
    try:
        from ipfs_accelerate_py.github_cli.cache import GitHubAPICache
        
        cache_dir = tempfile.mkdtemp(prefix="test_cache_")
        cache = GitHubAPICache(
            cache_dir=cache_dir,
            enable_persistence=False,
            enable_p2p=False,
            default_ttl=5
        )
        
        # Test put
        logger.info("Testing cache.put()...")
        test_data = [{"name": "repo1"}, {"name": "repo2"}]
        cache.put("list_repos", test_data, owner="testuser")
        logger.info("✓ Data cached")
        
        # Test get
        logger.info("Testing cache.get()...")
        cached_data = cache.get("list_repos", owner="testuser")
        if cached_data == test_data:
            logger.info("✓ Retrieved correct data from cache")
        else:
            logger.error("✗ Retrieved data doesn't match")
            return False
        
        # Test TTL expiration
        logger.info("Testing TTL expiration (waiting 6 seconds)...")
        time.sleep(6)
        expired_data = cache.get("list_repos", owner="testuser")
        if expired_data is None:
            logger.info("✓ Cache entry expired as expected")
        else:
            logger.error("✗ Cache entry didn't expire")
            return False
        
        # Test statistics
        logger.info("Testing cache statistics...")
        stats = cache.get_stats()
        logger.info(f"  Cache stats: {json.dumps(stats, indent=2)}")
        if stats['hits'] > 0 and stats['misses'] > 0:
            logger.info("✓ Statistics tracking works")
        else:
            logger.error("✗ Statistics not tracking correctly")
            return False
        
        return True
    
    except Exception as e:
        logger.error(f"✗ Basic cache operations failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_content_hashing():
    """Test content-addressable hashing with IPFS multiformats."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 9: Testing Content-Addressable Hashing")
    logger.info("=" * 60)
    
    try:
        from ipfs_accelerate_py.github_cli.cache import GitHubAPICache
        
        cache = GitHubAPICache(enable_persistence=False, enable_p2p=False)
        
        # Test validation fields extraction
        logger.info("Testing validation field extraction...")
        test_repos = [
            {"name": "repo1", "updatedAt": "2025-11-08T10:00:00Z"},
            {"name": "repo2", "updatedAt": "2025-11-08T11:00:00Z"}
        ]
        
        validation_fields = cache._extract_validation_fields("list_repos", test_repos)
        if validation_fields:
            logger.info("✓ Validation fields extracted")
            logger.info(f"  Fields: {list(validation_fields.keys())}")
        else:
            logger.warning("⚠ No validation fields extracted (multiformats may not be available)")
        
        # Test hash computation
        if validation_fields:
            logger.info("Testing content hash computation...")
            content_hash = cache._compute_validation_hash(validation_fields)
            logger.info(f"✓ Content hash computed")
            logger.info(f"  Hash: {content_hash[:50]}...")
            
            # Test hash determinism
            content_hash2 = cache._compute_validation_hash(validation_fields)
            if content_hash == content_hash2:
                logger.info("✓ Hash is deterministic (same input → same hash)")
            else:
                logger.error("✗ Hash is not deterministic")
                return False
            
            # Test hash changes with data
            modified_fields = validation_fields.copy()
            modified_fields["repo1"] = {"updatedAt": "2025-11-08T12:00:00Z"}
            content_hash3 = cache._compute_validation_hash(modified_fields)
            if content_hash != content_hash3:
                logger.info("✓ Hash changes when data changes")
            else:
                logger.error("✗ Hash didn't change with modified data")
                return False
        
        return True
    
    except Exception as e:
        logger.error(f"✗ Content hashing test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_github_cli_integration():
    """Test that GitHubCLI uses cache correctly."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 10: Testing GitHub CLI Integration")
    logger.info("=" * 60)
    
    try:
        from ipfs_accelerate_py.github_cli import GitHubCLI
        from ipfs_accelerate_py.github_cli.cache import get_global_cache
        
        # Create GitHub CLI instance
        logger.info("Creating GitHubCLI instance...")
        gh = GitHubCLI(enable_cache=True)
        logger.info("✓ GitHubCLI created")
        
        # Get cache instance
        cache = get_global_cache()
        logger.info(f"✓ Global cache retrieved")
        
        # Check if encryption is enabled
        if hasattr(cache, '_cipher') and cache._cipher:
            logger.info("✓ Cache has encryption enabled")
        else:
            logger.warning("⚠ Cache encryption not enabled")
        
        # Check statistics
        stats = cache.get_stats()
        logger.info(f"Cache statistics:")
        logger.info(f"  Cache size: {stats['cache_size']}")
        logger.info(f"  P2P enabled: {stats.get('p2p_enabled', False)}")
        logger.info(f"  Total requests: {stats['total_requests']}")
        logger.info(f"  Hit rate: {stats['hit_rate']:.1%}")
        
        return True
    
    except Exception as e:
        logger.error(f"✗ GitHub CLI integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all tests and report results."""
    logger.info("\n" + "=" * 70)
    logger.info(" " * 15 + "P2P CACHE ENCRYPTION TEST SUITE")
    logger.info("=" * 70)
    
    results = {}
    
    # Run tests
    results["Dependencies: cryptography"] = test_encryption_dependencies()
    results["Dependencies: multiformats"] = test_multiformats_dependencies()
    results["Dependencies: libp2p"] = test_libp2p_dependencies()
    results["GitHub Token Available"] = test_github_token_available()
    
    # Only run encryption tests if dependencies are available
    if results["Dependencies: cryptography"] and results["GitHub Token Available"]:
        results["Key Derivation"] = test_encryption_key_derivation()
        results["Encryption/Decryption"] = test_message_encryption_decryption()
        results["Unauthorized Prevention"] = test_wrong_key_decryption()
    else:
        logger.warning("\n⚠ Skipping encryption tests (dependencies not available)")
    
    # Basic tests
    results["Basic Cache Operations"] = test_cache_basic_operations()
    results["Content Hashing"] = test_content_hashing()
    results["GitHub CLI Integration"] = test_github_cli_integration()
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info(" " * 25 + "TEST SUMMARY")
    logger.info("=" * 70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"{status:10} | {test_name}")
    
    logger.info("=" * 70)
    logger.info(f"Total: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
    logger.info("=" * 70)
    
    if passed == total:
        logger.info("\n🎉 All tests passed!")
        return 0
    else:
        logger.error(f"\n❌ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
