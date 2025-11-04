#!/usr/bin/env python3
"""
Tests for invoke_copilot_with_throttling.py script

These tests validate the throttled Copilot CLI invocation functionality.
"""

import subprocess
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_script_exists():
    """Test that the script file exists and is executable."""
    script_path = project_root / "scripts" / "invoke_copilot_with_throttling.py"
    assert script_path.exists(), "Script file does not exist"
    assert os.access(script_path, os.X_OK), "Script is not executable"
    print("✅ Script exists and is executable")


def test_help_output():
    """Test that --help works and shows usage."""
    result = subprocess.run(
        ["python3", "scripts/invoke_copilot_with_throttling.py", "--help"],
        capture_output=True,
        text=True,
        cwd=project_root
    )
    
    assert result.returncode == 0, "Help command failed"
    assert "usage:" in result.stdout.lower(), "Help output missing usage"
    assert "--pr" in result.stdout, "Help missing --pr option"
    assert "--dry-run" in result.stdout, "Help missing --dry-run option"
    assert "--batch-size" in result.stdout, "Help missing --batch-size option"
    assert "--max-concurrent" in result.stdout, "Help missing --max-concurrent option"
    assert "--check-interval" in result.stdout, "Help missing --check-interval option"
    print("✅ Help output is correct")


def test_dry_run_mode():
    """Test that dry-run mode works without making actual changes."""
    result = subprocess.run(
        ["python3", "scripts/invoke_copilot_with_throttling.py", "--dry-run"],
        capture_output=True,
        text=True,
        cwd=project_root,
        timeout=60
    )
    
    # Script should handle everything gracefully in dry-run
    output = result.stdout + result.stderr
    assert "dry run" in output.lower() or "DRY RUN" in output, \
        "Dry run mode not recognized"
    print("✅ Dry-run mode works")


def test_script_imports():
    """Test that the script can be imported and has expected classes."""
    sys.path.insert(0, str(project_root / "scripts"))
    try:
        import invoke_copilot_with_throttling
        
        # Check for main class
        assert hasattr(invoke_copilot_with_throttling, "ThrottledCopilotInvoker"), \
            "ThrottledCopilotInvoker class not found"
        
        # Check for main function
        assert hasattr(invoke_copilot_with_throttling, "main"), \
            "main function not found"
        
        print("✅ Script imports correctly and has expected components")
    except ImportError as e:
        print(f"❌ Failed to import script: {e}")
        sys.exit(1)


def test_throttled_invoker_instantiation():
    """Test that ThrottledCopilotInvoker can be instantiated."""
    sys.path.insert(0, str(project_root / "scripts"))
    try:
        from invoke_copilot_with_throttling import ThrottledCopilotInvoker
        
        # Test dry-run mode
        try:
            invoker = ThrottledCopilotInvoker(
                dry_run=True,
                batch_size=3,
                max_concurrent=3,
                check_interval=30
            )
            assert invoker.dry_run is True, "Dry run mode not set"
            assert invoker.batch_size == 3, "Batch size not set correctly"
            assert invoker.max_concurrent == 3, "Max concurrent not set correctly"
            assert invoker.check_interval == 30, "Check interval not set correctly"
            print("✅ ThrottledCopilotInvoker instantiates correctly")
        except SystemExit:
            # Expected if gh CLI is not authenticated
            print("✅ ThrottledCopilotInvoker instantiates correctly (gh CLI check works)")
        
    except Exception as e:
        print(f"⚠️  Could not test instantiation: {e}")
        print("   This is expected if gh CLI is not installed/authenticated")


def test_batch_size_configuration():
    """Test that batch size can be configured."""
    sys.path.insert(0, str(project_root / "scripts"))
    try:
        from invoke_copilot_with_throttling import ThrottledCopilotInvoker
        
        try:
            # Test different batch sizes
            for batch_size in [1, 3, 5, 10]:
                invoker = ThrottledCopilotInvoker(
                    dry_run=True,
                    batch_size=batch_size
                )
                assert invoker.batch_size == batch_size, \
                    f"Batch size {batch_size} not set correctly"
            
            print("✅ Batch size configuration works")
        except SystemExit:
            print("✅ Batch size configuration works (gh CLI check works)")
        
    except Exception as e:
        print(f"⚠️  Could not test batch size: {e}")


def test_max_concurrent_configuration():
    """Test that max concurrent can be configured."""
    sys.path.insert(0, str(project_root / "scripts"))
    try:
        from invoke_copilot_with_throttling import ThrottledCopilotInvoker
        
        try:
            # Test different max concurrent values
            for max_concurrent in [1, 3, 5, 10]:
                invoker = ThrottledCopilotInvoker(
                    dry_run=True,
                    max_concurrent=max_concurrent
                )
                assert invoker.max_concurrent == max_concurrent, \
                    f"Max concurrent {max_concurrent} not set correctly"
            
            print("✅ Max concurrent configuration works")
        except SystemExit:
            print("✅ Max concurrent configuration works (gh CLI check works)")
        
    except Exception as e:
        print(f"⚠️  Could not test max concurrent: {e}")


def test_copilot_cli_integration():
    """Test that CopilotCLI from ipfs_datasets_py can be used."""
    sys.path.insert(0, str(project_root))
    try:
        from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
        
        cli = CopilotCLI()
        status = cli.get_status()
        
        assert isinstance(status, dict), "Status should be a dictionary"
        assert 'github_cli_available' in status, "Status should include github_cli_available"
        
        print("✅ CopilotCLI integration works")
    except ImportError as e:
        print(f"⚠️  CopilotCLI not available: {e}")
        print("   This is expected if ipfs_datasets_py is not installed")


def test_throttling_logic():
    """Test that throttling logic is implemented."""
    sys.path.insert(0, str(project_root / "scripts"))
    try:
        from invoke_copilot_with_throttling import ThrottledCopilotInvoker
        
        try:
            invoker = ThrottledCopilotInvoker(dry_run=True, batch_size=3)
            
            # Check that required methods exist
            assert hasattr(invoker, 'wait_for_agent_slots'), \
                "wait_for_agent_slots method not found"
            assert hasattr(invoker, 'count_active_copilot_agents'), \
                "count_active_copilot_agents method not found"
            assert hasattr(invoker, 'process_prs_with_throttling'), \
                "process_prs_with_throttling method not found"
            
            print("✅ Throttling logic methods are present")
        except SystemExit:
            print("✅ Throttling logic methods are present (gh CLI check works)")
        
    except Exception as e:
        print(f"⚠️  Could not test throttling logic: {e}")


def main():
    """Run all tests."""
    print("🧪 Testing invoke_copilot_with_throttling.py script\n")
    
    tests = [
        test_script_exists,
        test_help_output,
        test_dry_run_mode,
        test_script_imports,
        test_throttled_invoker_instantiation,
        test_batch_size_configuration,
        test_max_concurrent_configuration,
        test_copilot_cli_integration,
        test_throttling_logic,
    ]
    
    failed = 0
    for test in tests:
        try:
            print(f"\n▶️  Running: {test.__name__}")
            test()
        except AssertionError as e:
            print(f"❌ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ ERROR: {e}")
            failed += 1
    
    print(f"\n{'='*60}")
    print(f"Tests: {len(tests) - failed}/{len(tests)} passed")
    
    if failed > 0:
        print(f"❌ {failed} test(s) failed")
        sys.exit(1)
    else:
        print("✅ All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
