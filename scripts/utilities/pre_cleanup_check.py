#!/usr/bin/env python3
"""
Pre-cleanup validation script
Checks if the project is ready for cleanup execution
"""

import os
import subprocess
from pathlib import Path

def check_git_status():
    """Check if there are uncommitted changes"""
    try:
        result = subprocess.run(['git', 'status', '--porcelain'], 
                              capture_output=True, text=True, check=True)
        uncommitted = result.stdout.strip()
        if uncommitted:
            print("⚠️  Warning: There are uncommitted changes:")
            print(uncommitted)
            return False
        else:
            print("✅ Git status clean - no uncommitted changes")
            return True
    except subprocess.CalledProcessError:
        print("❌ Could not check git status")
        return False

def check_critical_files():
    """Check that critical files exist"""
    critical_files = [
        'README.md',
        'requirements.txt', 
        'pyproject.toml',
        'LICENSE',
        'ipfs_datasets_py/',
        'tests/',
        'cleanup_implementation.py'
    ]
    
    missing = []
    for file_path in critical_files:
        if not Path(file_path).exists():
            missing.append(file_path)
    
    if missing:
        print(f"❌ Missing critical files: {missing}")
        return False
    else:
        print("✅ All critical files present")
        return True

def check_cleanup_preview():
    """Check if cleanup preview exists"""
    if Path('cleanup_summary_preview.txt').exists():
        print("✅ Cleanup preview exists")
        with open('cleanup_summary_preview.txt', 'r') as f:
            content = f.read()
            lines = content.split('\n')
            for line in lines:
                if 'Files moved:' in line:
                    print(f"📋 {line}")
                elif 'Files removed:' in line:
                    print(f"📋 {line}")
                elif 'Directories created:' in line:
                    print(f"📋 {line}")
        return True
    else:
        print("❌ No cleanup preview found - run dry run first")
        return False

def main():
    """Main validation function"""
    print("🔍 PRE-CLEANUP VALIDATION")
    print("=" * 40)
    
    checks = [
        ("Git Status", check_git_status),
        ("Critical Files", check_critical_files), 
        ("Cleanup Preview", check_cleanup_preview)
    ]
    
    all_passed = True
    for check_name, check_func in checks:
        print(f"\n🔧 Checking {check_name}...")
        if not check_func():
            all_passed = False
    
    print("\n" + "=" * 40)
    if all_passed:
        print("✅ ALL CHECKS PASSED - Ready for cleanup!")
        print("\nTo execute cleanup run:")
        print("  python3 cleanup_implementation.py --execute")
    else:
        print("❌ Some checks failed - address issues before cleanup")
    
    return all_passed

if __name__ == "__main__":
    main()
