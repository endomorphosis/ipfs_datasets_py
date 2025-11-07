#!/usr/bin/env python3
"""
Test script for GitHub API Counter

This script tests the counter functionality to ensure it works correctly.
"""

import os
import sys
import tempfile
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from github_api_counter import GitHubAPICounter
from github_api_counter_helper import tracked_subprocess, get_counter, patch_subprocess


def test_basic_counting():
    """Test basic API call counting."""
    print("="*80)
    print("Test 1: Basic API Call Counting")
    print("="*80)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        metrics_file = Path(tmpdir) / 'test_metrics.json'
        counter = GitHubAPICounter(metrics_file=str(metrics_file))
        
        # Manually count some calls
        counter.count_api_call('gh_pr_list', 5)
        counter.count_api_call('gh_issue_create', 2)
        counter.count_api_call('gh_run_view', 10)
        
        # Check totals
        assert counter.get_total_calls() == 17, f"Expected 17 calls, got {counter.get_total_calls()}"
        assert counter.get_estimated_cost() == 17, f"Expected cost 17, got {counter.get_estimated_cost()}"
        
        # Check breakdown
        breakdown = counter.get_call_breakdown()
        assert breakdown['gh_pr_list'] == 5
        assert breakdown['gh_issue_create'] == 2
        assert breakdown['gh_run_view'] == 10
        
        # Save metrics
        counter.save_metrics()
        
        # Verify file was created
        assert metrics_file.exists(), "Metrics file was not created"
        
        print("✅ Test passed!")
        print(f"   Total calls: {counter.get_total_calls()}")
        print(f"   Estimated cost: {counter.get_estimated_cost()}")
    
    print()


def test_rate_limit_detection():
    """Test rate limit detection."""
    print("="*80)
    print("Test 2: Rate Limit Detection")
    print("="*80)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        metrics_file = Path(tmpdir) / 'test_metrics.json'
        counter = GitHubAPICounter(metrics_file=str(metrics_file))
        
        # Add calls below threshold
        counter.count_api_call('gh_pr_list', 3000)
        assert not counter.is_approaching_limit(), "Should not be approaching limit at 3000"
        print(f"✅ 3000 calls: Not approaching limit")
        
        # Add calls to approach threshold (80% of 5000 = 4000)
        counter.count_api_call('gh_pr_list', 1500)
        assert counter.is_approaching_limit(), "Should be approaching limit at 4500"
        print(f"✅ 4500 calls: Approaching limit detected")
    
    print()


def test_command_detection():
    """Test command type detection."""
    print("="*80)
    print("Test 3: Command Type Detection")
    print("="*80)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        metrics_file = Path(tmpdir) / 'test_metrics.json'
        counter = GitHubAPICounter(metrics_file=str(metrics_file))
        
        test_commands = [
            (['gh', 'pr', 'list'], 'gh_pr_list'),
            (['gh', 'pr', 'view', '123'], 'gh_pr_view'),
            (['gh', 'issue', 'create', '--title', 'Test'], 'gh_issue_create'),
            (['gh', 'run', 'view', '456'], 'gh_run_view'),
            (['gh', 'api', '/repos/owner/repo'], 'gh_api'),
        ]
        
        for command, expected_type in test_commands:
            detected_type = counter._detect_command_type(command)
            assert detected_type == expected_type, \
                f"Expected {expected_type}, got {detected_type} for {command}"
            print(f"✅ {' '.join(command):50s} -> {detected_type}")
    
    print()


def test_context_manager():
    """Test context manager functionality."""
    print("="*80)
    print("Test 4: Context Manager")
    print("="*80)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        metrics_file = Path(tmpdir) / 'test_metrics.json'
        
        with GitHubAPICounter(metrics_file=str(metrics_file)) as counter:
            counter.count_api_call('gh_pr_list', 3)
            counter.count_api_call('gh_issue_list', 2)
        
        # Metrics should be auto-saved
        assert metrics_file.exists(), "Metrics file should exist after context exit"
        print(f"✅ Metrics auto-saved on context exit")
        
        # Verify content
        import json
        with open(metrics_file) as f:
            data = json.load(f)
            assert data['total_calls'] == 5
            print(f"✅ Metrics contain correct data: {data['total_calls']} calls")
    
    print()


def test_helper_module():
    """Test helper module functionality."""
    print("="*80)
    print("Test 5: Helper Module")
    print("="*80)
    
    # Test getting global counter
    counter = get_counter()
    assert counter is not None, "Should get a counter instance"
    print(f"✅ Global counter instance created")
    
    # Test that it's the same instance
    counter2 = get_counter()
    assert counter is counter2, "Should return same instance"
    print(f"✅ Global counter is singleton")
    
    print()


def test_report_generation():
    """Test report generation."""
    print("="*80)
    print("Test 6: Report Generation")
    print("="*80)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        metrics_file = Path(tmpdir) / 'test_metrics.json'
        counter = GitHubAPICounter(metrics_file=str(metrics_file))
        
        counter.count_api_call('gh_pr_list', 10)
        counter.count_api_call('gh_issue_create', 5)
        counter.count_api_call('gh_run_view', 15)
        
        # Generate report
        counter.report()
        print(f"✅ Report generated successfully")
    
    print()


def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("GitHub API Counter - Test Suite")
    print("="*80 + "\n")
    
    tests = [
        test_basic_counting,
        test_rate_limit_detection,
        test_command_detection,
        test_context_manager,
        test_helper_module,
        test_report_generation,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ Test failed: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ Test error: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("="*80)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("="*80)
    
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
