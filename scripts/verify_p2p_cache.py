#!/usr/bin/env python3
"""
P2P Cache System Verification Script

Quick verification that all components are working correctly.
Run this anytime to check system health.
"""

import sys
import subprocess
from pathlib import Path

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def check(name, test_func):
    """Run a test and print result"""
    try:
        result = test_func()
        if result:
            print(f"{GREEN}✓{RESET} {name}")
            return True
        else:
            print(f"{RED}✗{RESET} {name}")
            return False
    except Exception as e:
        print(f"{RED}✗{RESET} {name}: {e}")
        return False

def test_cryptography():
    """Test cryptography library"""
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        return True
    except ImportError:
        return False

def test_multiformats():
    """Test multiformats library"""
    try:
        from multiformats import CID
        return True
    except ImportError:
        return False

def test_libp2p():
    """Test libp2p library"""
    try:
        from libp2p import new_host
        host = new_host()
        return host.get_id() is not None
    except Exception:
        return False

def test_cache_module():
    """Test cache module imports"""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from ipfs_accelerate_py.github_cli.cache import GitHubAPICache
        return True
    except Exception:
        return False

def test_github_token():
    """Test GitHub token availability"""
    import os
    if os.environ.get('GITHUB_TOKEN'):
        return True
    try:
        result = subprocess.run(
            ['gh', 'auth', 'token'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False

def test_encryption_functionality():
    """Test encryption works"""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from ipfs_accelerate_py.github_cli.cache import GitHubAPICache
        import json
        
        cache = GitHubAPICache()
        if not hasattr(cache, '_cipher') or cache._cipher is None:
            return None  # Not a failure, just needs token
        
        test_data = {'key': 'test', 'data': {'value': 123}}
        encrypted = cache._encrypt_message(test_data)
        decrypted = cache._decrypt_message(encrypted)
        
        return decrypted and decrypted['key'] == test_data['key']
    except Exception:
        return False

def test_cache_operations():
    """Test basic cache operations"""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from ipfs_accelerate_py.github_cli.cache import GitHubAPICache
        
        cache = GitHubAPICache(enable_p2p=False)
        
        # Test put/get
        cache.put('test_key', {'data': 'test'}, ttl=60)
        result = cache.get('test_key')
        
        return result and result['data'] == 'test'
    except Exception:
        return False

def run_test_suite():
    """Run specific test file"""
    try:
        result = subprocess.run(
            [sys.executable, 'test_p2p_cache_encryption.py'],
            capture_output=True,
            text=True,
            timeout=30
        )
        return '10/10 tests passed' in result.stdout
    except Exception:
        return False

def main():
    """Main verification"""
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}  P2P Cache System Verification{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")
    
    results = []
    
    print(f"{YELLOW}Dependencies:{RESET}")
    results.append(check("cryptography library", test_cryptography))
    results.append(check("multiformats library", test_multiformats))
    results.append(check("libp2p library", test_libp2p))
    
    print(f"\n{YELLOW}Configuration:{RESET}")
    has_token = check("GitHub token available", test_github_token)
    results.append(has_token)
    
    print(f"\n{YELLOW}Core Functionality:{RESET}")
    results.append(check("Cache module imports", test_cache_module))
    results.append(check("Cache operations (put/get)", test_cache_operations))
    
    # Encryption test (may be skipped if no token)
    enc_result = test_encryption_functionality()
    if enc_result is None:
        print(f"{YELLOW}⚠{RESET} Encryption test skipped (no GitHub token)")
    elif enc_result:
        results.append(True)
        print(f"{GREEN}✓{RESET} Encryption functionality")
    else:
        results.append(False)
        print(f"{RED}✗{RESET} Encryption functionality")
    
    print(f"\n{YELLOW}Test Suite:{RESET}")
    if Path('test_p2p_cache_encryption.py').exists():
        results.append(check("Full test suite (10 tests)", run_test_suite))
    else:
        print(f"{YELLOW}⚠{RESET} Test file not found (skipped)")
    
    # Summary
    passed = sum(1 for r in results if r)
    total = len(results)
    percentage = (passed / total * 100) if total > 0 else 0
    
    print(f"\n{BLUE}{'='*60}{RESET}")
    if passed == total:
        print(f"{GREEN}✅ All checks passed: {passed}/{total} (100%){RESET}")
        print(f"{GREEN}System is OPERATIONAL{RESET}")
        status = 0
    elif passed >= total * 0.8:
        print(f"{YELLOW}⚠ Most checks passed: {passed}/{total} ({percentage:.0f}%){RESET}")
        print(f"{YELLOW}System is MOSTLY OPERATIONAL{RESET}")
        status = 0
    else:
        print(f"{RED}✗ Some checks failed: {passed}/{total} ({percentage:.0f}%){RESET}")
        print(f"{RED}System may have issues{RESET}")
        status = 1
    
    print(f"{BLUE}{'='*60}{RESET}\n")
    
    # Usage hints
    if not has_token:
        print(f"{YELLOW}Hint:{RESET} Set GITHUB_TOKEN or run 'gh auth login' for encryption")
    
    print(f"\n{BLUE}Quick Commands:{RESET}")
    print(f"  • Run full tests: python test_p2p_cache_encryption.py")
    print(f"  • Run P2P tests: python test_p2p_networking.py")
    print(f"  • Enable P2P: export CACHE_ENABLE_P2P=true")
    print()
    
    return status

if __name__ == '__main__':
    sys.exit(main())
