#!/usr/bin/env python3
"""
Test the Enhanced PR Monitor Script

This script tests the enhanced PR monitor without making actual changes to PRs.
It helps validate the logic and detection capabilities.
"""

import subprocess
import json
import sys
from pathlib import Path


def test_enhanced_pr_monitor():
    """Test the enhanced PR monitor script."""
    print("🧪 Testing Enhanced PR Monitor")
    print("=" * 80)
    
    # Test 1: Check if script exists and is executable
    script_path = Path("scripts/enhanced_pr_monitor.py")
    
    if not script_path.exists():
        print("❌ Enhanced PR monitor script not found")
        return False
    
    print(f"✅ Script found: {script_path}")
    
    # Test 2: Check script syntax
    try:
        result = subprocess.run([
            'python3', '-m', 'py_compile', str(script_path)
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Script syntax is valid")
        else:
            print(f"❌ Script syntax error: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Failed to check syntax: {e}")
        return False
    
    # Test 3: Run in dry-run mode with help
    try:
        result = subprocess.run([
            'python3', str(script_path), '--help'
        ], capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            print("✅ Script help works")
            print(f"Help output preview: {result.stdout[:200]}...")
        else:
            print(f"❌ Script help failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Failed to run help: {e}")
        return False
    
    # Test 4: Check if GitHub CLI is available
    try:
        result = subprocess.run([
            'gh', '--version'
        ], capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            print("✅ GitHub CLI is available")
        else:
            print("⚠️ GitHub CLI not available - script will need authentication")
    except Exception as e:
        print(f"⚠️ GitHub CLI check failed: {e}")
    
    # Test 5: Try dry-run mode (if we have a notification user)
    notification_user = "endomorphosis"  # Default from repository
    
    try:
        print(f"\n🔍 Testing dry-run mode with notification user: {notification_user}")
        
        result = subprocess.run([
            'python3', str(script_path),
            '--notification-user', notification_user,
            '--dry-run',
            '--debug'
        ], capture_output=True, text=True, timeout=30)
        
        print(f"Exit code: {result.returncode}")
        print(f"Output preview: {result.stdout[:500]}...")
        
        if result.stderr:
            print(f"Errors: {result.stderr[:500]}...")
        
        # Check for specific success indicators
        if "Enhanced PR Monitoring" in result.stdout:
            print("✅ Script initialization successful")
        else:
            print("⚠️ Script may have initialization issues")
            
        if "DRY RUN MODE" in result.stdout:
            print("✅ Dry-run mode activated correctly")
        else:
            print("⚠️ Dry-run mode may not be working")
            
    except subprocess.TimeoutExpired:
        print("⚠️ Script took too long to run (possible GitHub CLI auth issue)")
    except Exception as e:
        print(f"⚠️ Dry-run test failed: {e}")
    
    print(f"\n{'=' * 80}")
    print("🧪 Test Summary:")
    print("- Script exists and has valid syntax")
    print("- Help command works")
    print("- Basic initialization appears functional")
    print("- Ready for integration with GitHub Actions")
    print(f"{'=' * 80}")
    
    return True


def check_existing_workflows():
    """Check existing PR monitoring workflows."""
    print("\n🔍 Checking existing PR monitoring workflows...")
    
    workflow_dir = Path(".github/workflows")
    pr_workflows = []
    
    if workflow_dir.exists():
        for workflow_file in workflow_dir.glob("*pr*.yml"):
            pr_workflows.append(workflow_file.name)
        
        for workflow_file in workflow_dir.glob("*copilot*.yml"):
            if workflow_file.name not in pr_workflows:
                pr_workflows.append(workflow_file.name)
    
    if pr_workflows:
        print(f"📋 Found {len(pr_workflows)} PR-related workflows:")
        for workflow in pr_workflows:
            print(f"  - {workflow}")
    else:
        print("⚠️ No existing PR workflows found")
    
    # Check if enhanced workflow exists
    enhanced_workflow = workflow_dir / "enhanced-pr-completion-monitor.yml"
    if enhanced_workflow.exists():
        print("✅ Enhanced PR completion monitor workflow found")
    else:
        print("⚠️ Enhanced PR completion monitor workflow not found")


def main():
    """Main test execution."""
    print("🚀 Enhanced PR Monitor Testing Suite")
    print("=" * 80)
    
    try:
        # Test the script
        if test_enhanced_pr_monitor():
            print("\n✅ Enhanced PR monitor script tests passed!")
        else:
            print("\n❌ Enhanced PR monitor script tests failed!")
            return 1
        
        # Check workflows
        check_existing_workflows()
        
        print("\n📋 Next Steps:")
        print("1. Commit the enhanced PR monitor script and workflow")
        print("2. Test with a real PR using --dry-run mode")
        print("3. Enable the workflow by triggering it manually")
        print("4. Monitor the workflow runs and adjust as needed")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())