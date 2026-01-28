#!/usr/bin/env python3
"""
Test script to verify ipfs_kit_py submodule integration
"""

import sys
from pathlib import Path

def test_ipfs_kit_py_submodule():
    """Test that ipfs_kit_py submodule can be imported and used."""
    
    print("🧪 Testing ipfs_kit_py submodule integration...")
    
    # Add the submodule to Python path
    submodule_path = Path(__file__).parent / "ipfs_kit_py"
    if submodule_path.exists():
        sys.path.insert(0, str(submodule_path))
        print(f"✅ Added {submodule_path} to Python path")
    else:
        print(f"❌ Submodule path {submodule_path} does not exist")
        return False
    
    # Test basic import
    try:
        import ipfs_kit_py
        print(f"✅ Successfully imported ipfs_kit_py from {ipfs_kit_py.__file__}")
        
        # Check if version is available
        if hasattr(ipfs_kit_py, '__version__'):
            print(f"📦 Version: {ipfs_kit_py.__version__}")
        else:
            print("📦 Version: Not specified")
            
    except ImportError as e:
        print(f"❌ Failed to import ipfs_kit_py: {e}")
        return False
    
    # Test that we can access some basic functionality
    try:
        # Check for common modules/classes that should be available
        test_imports = []
        
        # Try importing some expected modules
        expected_modules = [
            'ipfs_kit_py.ipfs_kit',
            'ipfs_kit_py.mcp',
        ]
        
        for module_name in expected_modules:
            try:
                __import__(module_name)
                test_imports.append(f"✅ {module_name}")
            except ImportError as e:
                test_imports.append(f"⚠️ {module_name}: {e}")
        
        print("📦 Module availability:")
        for result in test_imports:
            print(f"  {result}")
            
    except Exception as e:
        print(f"⚠️ Warning during module testing: {e}")
    
    print("🎉 ipfs_kit_py submodule integration test completed!")
    return True

def test_submodule_git_status():
    """Test that the submodule is properly configured."""
    
    print("\n🔍 Testing Git submodule configuration...")
    
    import subprocess
    
    try:
        # Check submodule status
        result = subprocess.run(['git', 'submodule', 'status'], 
                              capture_output=True, text=True, cwd=Path(__file__).parent)
        
        if result.returncode == 0:
            print(f"✅ Git submodule status:")
            for line in result.stdout.strip().split('\n'):
                if 'ipfs_kit_py' in line:
                    print(f"  📦 {line}")
        else:
            print(f"❌ Git submodule status failed: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Error checking git submodule status: {e}")
        return False
    
    # Check that we're on the correct branch
    try:
        result = subprocess.run(['git', 'branch', '-v'], 
                              capture_output=True, text=True, 
                              cwd=Path(__file__).parent / "ipfs_kit_py")
        
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if line.startswith('*'):
                    branch_info = line.strip()
                    print(f"✅ Current branch: {branch_info}")
                    if 'known_good' in branch_info:
                        print("✅ Confirmed on known_good branch")
                    else:
                        print("⚠️ Not on known_good branch")
                    break
        else:
            print(f"❌ Error checking branch: {result.stderr}")
            
    except Exception as e:
        print(f"❌ Error checking git branch: {e}")
    
    return True

if __name__ == "__main__":
    print("🚀 Starting ipfs_kit_py submodule integration tests")
    print("=" * 60)
    
    success = True
    
    # Run tests
    success &= test_ipfs_kit_py_submodule()
    success &= test_submodule_git_status()
    
    print("\n" + "=" * 60)
    if success:
        print("🎉 All tests completed successfully!")
        sys.exit(0)
    else:
        print("❌ Some tests failed!")
        sys.exit(1)