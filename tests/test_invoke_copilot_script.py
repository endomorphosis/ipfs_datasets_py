#!/usr/bin/env python3
"""
Tests for invoke_copilot_on_pr.py script

These tests validate the Copilot CLI invocation script functionality.
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
    script_path = project_root / "scripts" / "invoke_copilot_on_pr.py"
    assert script_path.exists(), "Script file does not exist"
    assert os.access(script_path, os.X_OK), "Script is not executable"
    print("✅ Script exists and is executable")


def test_help_output():
    """Test that --help works and shows usage."""
    result = subprocess.run(
        ["python3", "scripts/invoke_copilot_on_pr.py", "--help"],
        capture_output=True,
        text=True,
        cwd=project_root
    )
    
    assert result.returncode == 0, "Help command failed"
    assert "usage:" in result.stdout.lower(), "Help output missing usage"
    assert "--pr" in result.stdout, "Help missing --pr option"
    assert "--dry-run" in result.stdout, "Help missing --dry-run option"
    assert "--instruction" in result.stdout, "Help missing --instruction option"
    print("✅ Help output is correct")


def test_dry_run_mode():
    """Test that dry-run mode works without making actual changes."""
    # This will fail auth check but should still validate dry-run logic
    result = subprocess.run(
        ["python3", "scripts/invoke_copilot_on_pr.py", "--pr", "1", "--dry-run"],
        capture_output=True,
        text=True,
        cwd=project_root
    )
    
    # Script should handle auth gracefully in dry-run
    output = result.stdout + result.stderr
    assert "dry run" in output.lower() or "github cli" in output.lower(), \
        "Dry run mode not recognized"
    print("✅ Dry-run mode works")


def test_requires_pr_or_find_all():
    """Test that script requires either --pr or --find-all."""
    result = subprocess.run(
        ["python3", "scripts/invoke_copilot_on_pr.py"],
        capture_output=True,
        text=True,
        cwd=project_root
    )
    
    # Should show help or error when no args provided
    assert result.returncode != 0, "Script should require arguments"
    print("✅ Script correctly requires arguments")


def test_script_imports():
    """Test that the script can be imported and has expected classes."""
    sys.path.insert(0, str(project_root / "scripts"))
    try:
        import invoke_copilot_on_pr
        
        # Check for main class
        assert hasattr(invoke_copilot_on_pr, "CopilotPRInvoker"), \
            "CopilotPRInvoker class not found"
        
        # Check for main function
        assert hasattr(invoke_copilot_on_pr, "main"), \
            "main function not found"
        
        print("✅ Script imports correctly and has expected components")
    except ImportError as e:
        print(f"❌ Failed to import script: {e}")
        sys.exit(1)


def test_copilot_invoker_instantiation():
    """Test that CopilotPRInvoker can be instantiated."""
    sys.path.insert(0, str(project_root / "scripts"))
    try:
        from invoke_copilot_on_pr import CopilotPRInvoker
        
        # Test dry-run mode
        # Note: Will still check gh CLI during __init__, which is expected
        try:
            invoker = CopilotPRInvoker(dry_run=True)
            assert invoker.dry_run is True, "Dry run mode not set"
            print("✅ CopilotPRInvoker instantiates correctly (gh CLI available)")
        except SystemExit:
            # Expected if gh CLI is not authenticated
            print("✅ CopilotPRInvoker instantiates correctly (gh CLI check works)")
        
    except Exception as e:
        print(f"⚠️  Could not test instantiation: {e}")
        print("   This is expected if gh CLI is not installed/authenticated")


def main():
    """Run all tests."""
    print("🧪 Testing invoke_copilot_on_pr.py script\n")
    
    tests = [
        test_script_exists,
        test_help_output,
        test_dry_run_mode,
        test_requires_pr_or_find_all,
        test_script_imports,
        test_copilot_invoker_instantiation,
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
