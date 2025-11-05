#!/usr/bin/env python3
"""
Test the complete queue management system.

This script validates that all components are working correctly.
"""

import subprocess
import json
import sys
import time
from datetime import datetime


def run_command(cmd, description=""):
    """Run a command and return success status."""
    if description:
        print(f"🔄 {description}")
    
    try:
        result = subprocess.run(
            cmd, 
            shell=True,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            print(f"✅ Success: {description}")
            if result.stdout.strip():
                print(f"   Output: {result.stdout.strip()[:200]}...")
            return True
        else:
            print(f"❌ Failed: {description}")
            if result.stderr.strip():
                print(f"   Error: {result.stderr.strip()[:200]}...")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"⏰ Timeout: {description}")
        return False
    except Exception as e:
        print(f"💥 Exception: {description} - {e}")
        return False


def test_queue_manager():
    """Test the queue manager utility."""
    print(f"\n{'='*60}")
    print("🧪 Testing Queue Manager")
    print(f"{'='*60}")
    
    # Test status functionality
    success1 = run_command(
        "python scripts/queue_manager.py --status --json",
        "Testing queue status with JSON output"
    )
    
    # Test help
    success2 = run_command(
        "python scripts/queue_manager.py --help",
        "Testing queue manager help"
    )
    
    return success1 and success2


def test_enhanced_pr_monitor():
    """Test the enhanced PR monitor."""
    print(f"\n{'='*60}")
    print("🧪 Testing Enhanced PR Monitor")
    print(f"{'='*60}")
    
    # Test the enhanced PR monitor
    success = run_command(
        "python scripts/enhanced_pr_monitor.py --dry-run",
        "Testing enhanced PR monitor in dry-run mode"
    )
    
    return success


def test_workflows():
    """Test workflow existence and syntax."""
    print(f"\n{'='*60}")
    print("🧪 Testing Workflows")
    print(f"{'='*60}")
    
    # Check enhanced PR monitor workflow
    success1 = run_command(
        "test -f .github/workflows/enhanced-pr-completion-monitor.yml",
        "Checking enhanced PR monitor workflow exists"
    )
    
    # Check continuous queue management workflow
    success2 = run_command(
        "test -f .github/workflows/continuous-queue-management.yml",
        "Checking continuous queue management workflow exists"
    )
    
    # Validate YAML syntax
    success3 = run_command(
        "python -c \"import yaml; yaml.safe_load(open('.github/workflows/continuous-queue-management.yml'))\"",
        "Validating continuous queue management YAML syntax"
    )
    
    success4 = run_command(
        "python -c \"import yaml; yaml.safe_load(open('.github/workflows/enhanced-pr-completion-monitor.yml'))\"",
        "Validating enhanced PR monitor YAML syntax"
    )
    
    return success1 and success2 and success3 and success4


def test_github_cli():
    """Test GitHub CLI functionality."""
    print(f"\n{'='*60}")
    print("🧪 Testing GitHub CLI")
    print(f"{'='*60}")
    
    # Test GitHub CLI authentication
    success1 = run_command(
        "gh auth status",
        "Checking GitHub CLI authentication"
    )
    
    # Test PR listing
    success2 = run_command(
        "gh pr list --limit 5 --json number,title",
        "Testing PR listing"
    )
    
    # Test issue listing  
    success3 = run_command(
        "gh issue list --limit 5 --json number,title",
        "Testing issue listing"
    )
    
    return success1 and success2 and success3


def generate_test_report():
    """Generate a comprehensive test report."""
    print(f"\n{'='*80}")
    print("📋 COMPREHENSIVE SYSTEM TEST REPORT")
    print(f"{'='*80}")
    print(f"Test Time: {datetime.now().isoformat()}")
    print()
    
    results = {}
    
    # Run all tests
    print("Running comprehensive system tests...")
    
    results['github_cli'] = test_github_cli()
    results['enhanced_pr_monitor'] = test_enhanced_pr_monitor()
    results['queue_manager'] = test_queue_manager()
    results['workflows'] = test_workflows()
    
    # Summary
    print(f"\n{'='*80}")
    print("📊 TEST SUMMARY")
    print(f"{'='*80}")
    
    total_tests = len(results)
    passed_tests = sum(results.values())
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {test_name:20} : {status}")
    
    print(f"\n🎯 Overall Result: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        print("🎉 ALL TESTS PASSED! System is ready for deployment.")
        success_rate = 100.0
    else:
        success_rate = (passed_tests / total_tests) * 100
        print(f"⚠️  {total_tests - passed_tests} test(s) failed. Success rate: {success_rate:.1f}%")
    
    print(f"\n📋 DEPLOYMENT READINESS:")
    if success_rate >= 90:
        print("🟢 READY - System meets deployment criteria")
    elif success_rate >= 70:
        print("🟡 CAUTION - Some issues detected, review before deployment")
    else:
        print("🔴 NOT READY - Critical issues must be resolved")
    
    print(f"{'='*80}")
    
    return success_rate >= 90


def main():
    """Main test execution."""
    print("🚀 Starting Comprehensive Queue Management System Test")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        ready = generate_test_report()
        sys.exit(0 if ready else 1)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()