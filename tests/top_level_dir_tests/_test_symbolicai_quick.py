#!/usr/bin/env python3
"""
Quick SymbolicAI API Test
Tests basic SymbolicAI functionality with timeout
"""

import os
import sys
import signal
from contextlib import contextmanager

# Add project root to path
sys.path.insert(0, '/home/barberb/ipfs_datasets_py')

@contextmanager
def timeout(duration):
    """Context manager for timeout"""
    def timeout_handler(signum, frame):
        raise TimeoutError(f"Operation timed out after {duration} seconds")
    
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(duration)
    try:
        yield
    finally:
        signal.alarm(0)

def test_symbolicai_quick():
    """Quick test of SymbolicAI with timeout"""
    print("Testing SymbolicAI API connection...")
    
    # Check environment
    api_key = os.getenv('NEUROSYMBOLIC_ENGINE_API_KEY')
    if not api_key:
        print("✗ No API key found")
        return False
    
    print(f"✓ API key found: {api_key[:20]}...")
    
    try:
        with timeout(30):  # 30 second timeout
            # Import and test
            import symai as sym
            from symai import Symbol
            print("✓ SymbolicAI imported successfully")
            
            # Simple test
            result = Symbol("What is 1+1?", semantic=True)
            print(f"✓ Basic symbol creation successful: {result}")
            
            return True
            
    except TimeoutError:
        print("✗ Test timed out")
        return False
    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False

def test_logic_integration_quick():
    """Quick test of logic integration modules"""
    print("\nTesting logic integration modules...")
    
    try:
        from ipfs_datasets_py.logic_integration import (
            SymbolicFOLBridge,
            get_available_engines
        )
        print("✓ Logic integration modules imported")
        
        # Check available engines
        engines = get_available_engines()
        print(f"✓ Available engines: {engines}")
        
        # Quick bridge test (with fallback)
        bridge = SymbolicFOLBridge()
        print("✓ SymbolicFOLBridge created successfully")
        
        return True
        
    except Exception as e:
        print(f"✗ Logic integration test failed: {e}")
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("QUICK SYMBOLICAI API TEST")
    print("=" * 50)
    
    api_success = test_symbolicai_quick()
    integration_success = test_logic_integration_quick()
    
    print("\n" + "=" * 50)
    print("RESULTS:")
    print(f"API Test: {'✓ PASSED' if api_success else '✗ FAILED'}")
    print(f"Integration Test: {'✓ PASSED' if integration_success else '✗ FAILED'}")
    
    if api_success and integration_success:
        print("🎉 ALL TESTS PASSED!")
        exit(0)
    else:
        print("❌ SOME TESTS FAILED")
        exit(1)
