#!/usr/bin/env python3
"""Simple test for individual development tools"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_individual_tools():
    """Test individual development tools"""
    
    print("🔧 Testing Individual Development Tools")
    print("=" * 50)
    
    # Test 1: development_tool_mcp_wrapper
    print("\n1. Testing development_tool_mcp_wrapper...")
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.base_tool import development_tool_mcp_wrapper
        result = development_tool_mcp_wrapper("TestToolClass")
        print(f"✅ PASS - {result.get('message', 'No message')}")
    except Exception as e:
        print(f"❌ FAIL - {e}")
    
    # Test 2: test_generator (which already passed)
    print("\n2. Testing test_generator...")
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import test_generator
        result = test_generator(
            name="test_suite",
            description="Test suite for testing",
            test_specification={"tests": [{"name": "test_example", "assertions": ["self.assertTrue(True)"]}]}
        )
        print(f"✅ PASS - Generated test result type: {type(result).__name__}")
    except Exception as e:
        print(f"❌ FAIL - {e}")
    
    # Test 3: Simple configuration check  
    print("\n3. Testing config access...")
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.config import get_config
        config = get_config()
        print(f"✅ PASS - Config loaded successfully")
    except Exception as e:
        print(f"❌ FAIL - {e}")
    
    print("\n✅ Individual tool tests completed!")

if __name__ == "__main__":
    test_individual_tools()
