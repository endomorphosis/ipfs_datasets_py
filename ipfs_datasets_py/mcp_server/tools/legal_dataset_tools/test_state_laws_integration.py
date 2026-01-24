#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Integration test for state laws scraping functionality.

Tests:
1. State laws scraper import and basic functions
2. Scheduler functionality
3. CLI tool availability

Usage:
    # From repository root:
    python ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/test_state_laws_integration.py
    
    # From this directory:
    cd ipfs_datasets_py/mcp_server/tools/legal_dataset_tools
    PYTHONPATH=/path/to/repo python test_state_laws_integration.py
"""

import anyio
import os
import sys
import tempfile
from pathlib import Path

# Add repository root to path if not already there
repo_root = Path(__file__).parent.parent.parent.parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


def test_imports():
    """Test that all required modules can be imported."""
    print("Testing imports...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import (
            scrape_state_laws,
            list_state_jurisdictions,
            create_schedule,
            list_schedules,
            remove_schedule,
            enable_disable_schedule,
            run_schedule_now
        )
        print("  ✓ All imports successful")
        return True
    except ImportError as e:
        print(f"  ✗ Import failed: {e}")
        print(f"  Note: Run from repository root or set PYTHONPATH")
        return False


async def test_jurisdictions():
    """Test listing state jurisdictions."""
    print("\nTesting list_state_jurisdictions...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import list_state_jurisdictions
        
        result = await list_state_jurisdictions()
        
        assert result["status"] == "success", "Status should be success"
        assert result["count"] == 51, "Should have 51 jurisdictions (50 states + DC)"
        assert "states" in result, "Should have states dict"
        
        print(f"  ✓ Found {result['count']} jurisdictions")
        return True
    except Exception as e:
        print(f"  ✗ Test failed: {e}")
        return False


async def test_scraper_with_mock():
    """Test scraper with mocked/limited data."""
    print("\nTesting scrape_state_laws...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import scrape_state_laws
        
        # Test with limited states
        result = await scrape_state_laws(
            states=['CA'],
            max_statutes=5,
            rate_limit_delay=0.5
        )
        
        assert result["status"] in ["success", "partial_success", "error"], "Should have valid status"
        assert "metadata" in result, "Should have metadata"
        assert "data" in result, "Should have data"
        
        print(f"  ✓ Scraper returned status: {result['status']}")
        if result.get('metadata'):
            print(f"    States attempted: {result['metadata'].get('states_count', 0)}")
        
        return True
    except Exception as e:
        print(f"  ✗ Test failed: {e}")
        return False


async def test_scheduler():
    """Test scheduler functionality."""
    print("\nTesting scheduler...")
    
    temp_dir = None
    try:
        # Import scheduler module using importlib for cleaner import
        import importlib.util
        
        scheduler_path = Path(__file__).parent / 'state_laws_scheduler.py'
        spec = importlib.util.spec_from_file_location("state_laws_scheduler", scheduler_path)
        state_laws_scheduler = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(state_laws_scheduler)
        
        # Use TemporaryDirectory context manager for automatic cleanup
        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = state_laws_scheduler.StateLawsUpdateScheduler(output_dir=temp_dir)
            
            # Test adding schedule
            schedule = scheduler.add_schedule(
                schedule_id='test_schedule',
                states=['CA'],
                interval_hours=24,
                enabled=True
            )
            assert schedule["schedule_id"] == 'test_schedule', "Schedule ID should match"
            print("  ✓ Schedule creation")
            
            # Test listing
            schedules = scheduler.list_schedules()
            assert len(schedules) == 1, "Should have 1 schedule"
            print("  ✓ Schedule listing")
            
            # Test enable/disable
            success = scheduler.enable_schedule('test_schedule', enabled=False)
            assert success, "Should disable successfully"
            schedules = scheduler.list_schedules()
            assert not schedules[0]["enabled"], "Schedule should be disabled"
            print("  ✓ Schedule enable/disable")
            
            # Test removal
            success = scheduler.remove_schedule('test_schedule')
            assert success, "Should remove successfully"
            schedules = scheduler.list_schedules()
            assert len(schedules) == 0, "Should have 0 schedules"
            print("  ✓ Schedule removal")
        
        return True
    except Exception as e:
        print(f"  ✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_async_api():
    """Test async API functions."""
    print("\nTesting async API functions...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import (
            create_schedule,
            list_schedules,
            enable_disable_schedule,
            remove_schedule
        )
        
        # Create schedule
        schedule = await create_schedule(
            schedule_id='test_api_schedule',
            states=['NY'],
            interval_hours=24
        )
        assert "schedule_id" in schedule, "Should have schedule_id"
        print("  ✓ create_schedule()")
        
        # List schedules
        result = await list_schedules()
        assert result["status"] == "success", "Should succeed"
        # Note: May have multiple schedules from different tests
        print(f"  ✓ list_schedules() - found {result['count']} schedules")
        
        # Disable schedule
        result = await enable_disable_schedule('test_api_schedule', enabled=False)
        assert result["status"] == "success", "Should succeed"
        print("  ✓ enable_disable_schedule()")
        
        # Remove schedule
        result = await remove_schedule('test_api_schedule')
        assert result["status"] == "success", "Should succeed"
        print("  ✓ remove_schedule()")
        
        return True
    except Exception as e:
        print(f"  ✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_cli_tool_exists():
    """Test that CLI tool exists and is executable."""
    print("\nTesting CLI tool...")
    
    try:
        cli_path = Path(__file__).parent / 'state_laws_cron.py'
        
        assert cli_path.exists(), f"CLI tool should exist at {cli_path}"
        print(f"  ✓ CLI tool exists: {cli_path}")
        
        # Check if executable (on Unix systems)
        import os
        if hasattr(os, 'access'):
            is_executable = os.access(str(cli_path), os.X_OK)
            if is_executable:
                print("  ✓ CLI tool is executable")
            else:
                print("  ⚠ CLI tool is not executable (may need chmod +x)")
        
        return True
    except Exception as e:
        print(f"  ✗ Test failed: {e}")
        return False


async def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("State Laws Scraping Integration Tests")
    print("=" * 60)
    
    results = []
    
    # Synchronous tests
    results.append(("Imports", test_imports()))
    results.append(("CLI Tool", test_cli_tool_exists()))
    
    # Async tests
    results.append(("Jurisdictions", await test_jurisdictions()))
    results.append(("Scraper", await test_scraper_with_mock()))
    results.append(("Scheduler", await test_scheduler()))
    results.append(("Async API", await test_async_api()))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠ {total - passed} test(s) failed")
        return 1


if __name__ == '__main__':
    try:
        exit_code = anyio.run(run_all_tests())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nTests interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\nTests failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
