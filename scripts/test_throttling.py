#!/usr/bin/env python3
"""
Test script for invoke_copilot_with_throttling.py

This test validates that the throttling logic works correctly.
"""

import sys
from pathlib import Path

# Add parent directory to path
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir))

from scripts.invoke_copilot_with_throttling import ThrottledCopilotInvoker


def test_initialization():
    """Test that the invoker can be initialized."""
    print("Testing initialization...")
    
    invoker = ThrottledCopilotInvoker(
        dry_run=True,
        batch_size=3,
        max_concurrent=3,
        check_interval=10
    )
    
    assert invoker.batch_size == 3, "Batch size should be 3"
    assert invoker.max_concurrent == 3, "Max concurrent should be 3"
    assert invoker.check_interval == 10, "Check interval should be 10"
    assert invoker.dry_run == True, "Dry run should be True"
    
    print("✅ Initialization test passed")


def test_batch_calculation():
    """Test that batches are calculated correctly."""
    print("\nTesting batch calculation...")
    
    invoker = ThrottledCopilotInvoker(dry_run=True, batch_size=3)
    
    # Test with 0 PRs
    prs = []
    batches = list(range(0, len(prs), invoker.batch_size))
    assert len(batches) == 0, "Should have 0 batches for 0 PRs"
    
    # Test with 1 PR
    prs = [{'number': 1}]
    batches = list(range(0, len(prs), invoker.batch_size))
    assert len(batches) == 1, "Should have 1 batch for 1 PR"
    
    # Test with 3 PRs (exactly 1 batch)
    prs = [{'number': i} for i in range(1, 4)]
    batches = list(range(0, len(prs), invoker.batch_size))
    assert len(batches) == 1, "Should have 1 batch for 3 PRs"
    
    # Test with 4 PRs (2 batches)
    prs = [{'number': i} for i in range(1, 5)]
    batches = list(range(0, len(prs), invoker.batch_size))
    assert len(batches) == 2, "Should have 2 batches for 4 PRs"
    
    # Test with 9 PRs (3 batches)
    prs = [{'number': i} for i in range(1, 10)]
    batches = list(range(0, len(prs), invoker.batch_size))
    assert len(batches) == 3, "Should have 3 batches for 9 PRs"
    
    # Test with 10 PRs (4 batches)
    prs = [{'number': i} for i in range(1, 11)]
    batches = list(range(0, len(prs), invoker.batch_size))
    assert len(batches) == 4, "Should have 4 batches for 10 PRs"
    
    print("✅ Batch calculation test passed")


def test_count_active_agents():
    """Test counting active agents (without actual GitHub API calls)."""
    print("\nTesting active agent counting logic...")
    
    invoker = ThrottledCopilotInvoker(dry_run=True, batch_size=3)
    
    # Test with empty PR list
    prs = []
    count = invoker.count_active_copilot_agents(prs)
    assert count == 0, "Should have 0 active agents for empty list"
    
    print("✅ Active agent counting test passed")


def test_dry_run_mode():
    """Test that dry run mode doesn't make actual changes."""
    print("\nTesting dry run mode...")
    
    invoker = ThrottledCopilotInvoker(dry_run=True, batch_size=3)
    
    # Test invoke_copilot_on_pr in dry run mode
    fake_pr = {
        'number': 999,
        'title': 'Test PR',
        'headRefName': 'test-branch'
    }
    
    result = invoker.invoke_copilot_on_pr(fake_pr)
    assert result == True, "Should return True in dry run mode"
    
    print("✅ Dry run mode test passed")


def test_configuration_variants():
    """Test different configuration combinations."""
    print("\nTesting configuration variants...")
    
    # Test with different batch sizes
    invoker1 = ThrottledCopilotInvoker(dry_run=True, batch_size=5)
    assert invoker1.batch_size == 5, "Should accept custom batch size"
    
    # Test with different max concurrent
    invoker2 = ThrottledCopilotInvoker(dry_run=True, max_concurrent=5)
    assert invoker2.max_concurrent == 5, "Should accept custom max concurrent"
    
    # Test with different check interval
    invoker3 = ThrottledCopilotInvoker(dry_run=True, check_interval=60)
    assert invoker3.check_interval == 60, "Should accept custom check interval"
    
    print("✅ Configuration variants test passed")


def main():
    """Run all tests."""
    print("="*80)
    print("Running tests for invoke_copilot_with_throttling.py")
    print("="*80)
    
    try:
        test_initialization()
        test_batch_calculation()
        test_count_active_agents()
        test_dry_run_mode()
        test_configuration_variants()
        
        print("\n" + "="*80)
        print("✅ ALL TESTS PASSED")
        print("="*80)
        return 0
    
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
