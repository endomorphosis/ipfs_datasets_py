#!/usr/bin/env python3
"""
Import Debugging Script

Tests imports one by one to identify what's causing the hang.
"""

import subprocess
import sys
import time
from pathlib import Path

def test_import_with_timeout(import_statement, timeout=10):
    """Test an import statement with timeout."""
    script = f"""
import sys
sys.path.insert(0, '.')
print("Starting import test...")
{import_statement}
print("Import successful!")
"""
    
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(Path.cwd())
        )
        
        if result.returncode == 0:
            return True, result.stdout
        else:
            return False, result.stderr
            
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT after {timeout}s"
    except Exception as e:
        return False, str(e)

def main():
    """Test various import scenarios."""
    
    print("Import Debugging Report")
    print("=" * 50)
    
    # Test imports in order of complexity
    test_cases = [
        ("Basic Python modules", "import os, sys, json"),
        ("Pathlib", "from pathlib import Path"),
        ("Config only", "from ipfs_datasets_py.config import config"),
        ("Audit only", "from ipfs_datasets_py.audit import AuditLogger"),
        ("Base tool only", "from ipfs_datasets_py.mcp_server.tools.development_tools.base_tool import BaseDevelopmentTool"),
        ("Full package", "import ipfs_datasets_py"),
        ("Development tools init", "from ipfs_datasets_py.mcp_server.tools.development_tools import codebase_search"),
    ]
    
    results = []
    
    for description, import_stmt in test_cases:
        print(f"\nTesting: {description}")
        print(f"Import: {import_stmt}")
        
        success, output = test_import_with_timeout(import_stmt, timeout=15)
        
        if success:
            print("✅ SUCCESS")
            if "Import successful!" in output:
                print("   Import completed normally")
            else:
                print(f"   Output: {output.strip()}")
        else:
            print("❌ FAILED")
            print(f"   Error: {output}")
            
        results.append((description, success, output))
        
        # If we hit a failure, stop here to prevent hanging
        if not success and "TIMEOUT" in output:
            print(f"\n⚠️  Import hanging detected at: {description}")
            break
    
    # Summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    
    last_successful = None
    first_failure = None
    
    for description, success, output in results:
        status = "✅" if success else "❌"
        print(f"{status} {description}")
        
        if success:
            last_successful = description
        elif first_failure is None:
            first_failure = description
    
    if first_failure:
        print(f"\n🎯 Issue identified at: {first_failure}")
        if last_successful:
            print(f"   Last successful: {last_successful}")
        print("\n📋 Recommendation: Focus debugging on the transition between these imports")
    else:
        print("\n✅ All imports successful!")

if __name__ == "__main__":
    main()
