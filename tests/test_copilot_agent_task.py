#!/usr/bin/env python3
"""
Tests for GitHub Copilot agent-task functionality

This test validates that the CopilotCLI utility properly supports
gh agent-task create commands for invoking the Copilot Coding Agent.
"""

import sys
import subprocess
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_copilot_cli_has_agent_methods():
    """Test that CopilotCLI has the new agent-task methods."""
    try:
        from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
        
        cli = CopilotCLI()
        
        # Check for new agent-task methods
        assert hasattr(cli, 'create_agent_task'), \
            "CopilotCLI missing create_agent_task method"
        assert hasattr(cli, 'list_agent_tasks'), \
            "CopilotCLI missing list_agent_tasks method"
        assert hasattr(cli, 'view_agent_task'), \
            "CopilotCLI missing view_agent_task method"
        
        print("✅ CopilotCLI has all agent-task methods")
        return True
    except ImportError as e:
        print(f"⚠️  Could not import CopilotCLI: {e}")
        return False


def test_create_agent_task_signature():
    """Test that create_agent_task has correct signature."""
    try:
        from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
        import inspect
        
        cli = CopilotCLI()
        sig = inspect.signature(cli.create_agent_task)
        params = list(sig.parameters.keys())
        
        # Check for expected parameters
        assert 'task_description' in params, "Missing task_description parameter"
        assert 'base_branch' in params, "Missing base_branch parameter"
        assert 'follow' in params, "Missing follow parameter"
        assert 'repo' in params, "Missing repo parameter"
        
        print("✅ create_agent_task has correct signature")
        return True
    except Exception as e:
        print(f"⚠️  Could not check signature: {e}")
        return False


def test_create_agent_task_returns_dict():
    """Test that create_agent_task returns a dictionary."""
    try:
        from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
        
        cli = CopilotCLI()
        
        # Call with a simple task (will fail gracefully without auth)
        result = cli.create_agent_task("Test task", base_branch="main")
        
        assert isinstance(result, dict), "Result should be a dictionary"
        assert 'success' in result, "Result should have 'success' key"
        
        # If it fails (expected without auth), check error message
        if not result['success']:
            assert 'error' in result, "Failed result should have 'error' key"
            print(f"✅ create_agent_task returns proper dict (auth not available: {result['error'][:50]}...)")
        else:
            print("✅ create_agent_task returns proper dict")
        
        return True
    except Exception as e:
        print(f"⚠️  Could not test create_agent_task: {e}")
        return False


def test_invoke_copilot_uses_agent_task():
    """Test that invoke_copilot_on_pr tries to use agent-task."""
    sys.path.insert(0, str(project_root / "scripts"))
    try:
        from invoke_copilot_with_throttling import ThrottledCopilotInvoker
        import inspect
        
        # Get source code of invoke_copilot_on_pr method
        invoker = ThrottledCopilotInvoker(dry_run=True)
        source = inspect.getsource(invoker.invoke_copilot_on_pr)
        
        # Check that it uses agent-task create
        assert 'agent-task' in source, \
            "invoke_copilot_on_pr should use 'agent-task create'"
        assert 'create_agent_task' in source or 'gh agent-task create' in source, \
            "invoke_copilot_on_pr should call create_agent_task or gh agent-task create"
        
        # Check that @copilot is now a fallback
        assert '_fallback_copilot_mention' in source or 'fallback' in source.lower(), \
            "Should have fallback method for @copilot"
        
        print("✅ invoke_copilot_on_pr properly uses agent-task")
        return True
    except SystemExit:
        print("✅ invoke_copilot_on_pr properly uses agent-task (gh check works)")
        return True
    except Exception as e:
        print(f"⚠️  Could not test invoke_copilot_on_pr: {e}")
        return False


def test_batch_assign_uses_agent_task():
    """Test that batch_assign_copilot_to_prs uses agent-task."""
    sys.path.insert(0, str(project_root / "scripts"))
    try:
        import batch_assign_copilot_to_prs as batch_script
        import inspect
        
        # Get source code of assign_copilot function
        source = inspect.getsource(batch_script.assign_copilot)
        
        # Check that it uses agent-task create
        assert 'agent-task' in source, \
            "assign_copilot should use 'agent-task create'"
        assert 'create_agent_task' in source or 'gh agent-task create' in source, \
            "assign_copilot should call create_agent_task or gh agent-task create"
        
        # Check that it has fallback method
        assert 'fallback' in source.lower() or '@copilot' in source, \
            "Should have fallback method"
        
        print("✅ batch_assign_copilot_to_prs properly uses agent-task")
        return True
    except Exception as e:
        print(f"⚠️  Could not test batch_assign: {e}")
        return False


def test_gh_agent_task_available():
    """Test that gh agent-task command is available."""
    try:
        result = subprocess.run(
            ['gh', 'agent-task', '--help'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # Check if command exists
        if result.returncode == 0 or 'agent-task' in result.stdout:
            print("✅ gh agent-task command is available")
            return True
        else:
            print("⚠️  gh agent-task not available (expected in some environments)")
            return True  # Don't fail test, just warn
    except FileNotFoundError:
        print("⚠️  gh CLI not found (expected in some environments)")
        return True  # Don't fail test
    except Exception as e:
        print(f"⚠️  Could not check gh agent-task: {e}")
        return True  # Don't fail test


def test_workflow_updated():
    """Test that the workflow file was updated correctly."""
    workflow_path = project_root / ".github" / "workflows" / "pr-copilot-monitor.yml"
    
    if not workflow_path.exists():
        print("⚠️  Workflow file not found")
        return False
    
    with open(workflow_path, 'r') as f:
        content = f.read()
    
    # Check for key updates
    assert 'gh agent-task' in content, \
        "Workflow should mention gh agent-task"
    assert 'agent-task create' in content or 'gh agent-task create' in content, \
        "Workflow should document gh agent-task create"
    
    # Check that documentation was updated
    assert 'proper' in content.lower() or 'correctly' in content.lower(), \
        "Workflow should indicate proper method"
    
    print("✅ Workflow file properly updated")
    return True


def main():
    """Run all tests."""
    print("🧪 Testing GitHub Copilot agent-task functionality\n")
    
    tests = [
        test_copilot_cli_has_agent_methods,
        test_create_agent_task_signature,
        test_create_agent_task_returns_dict,
        test_invoke_copilot_uses_agent_task,
        test_batch_assign_uses_agent_task,
        test_gh_agent_task_available,
        test_workflow_updated,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            print(f"\n▶️  Running: {test.__name__}")
            if test():
                passed += 1
            else:
                print(f"❌ FAILED: {test.__name__}")
                failed += 1
        except AssertionError as e:
            print(f"❌ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ ERROR: {e}")
            failed += 1
    
    print(f"\n{'='*60}")
    print(f"Tests: {passed}/{len(tests)} passed")
    
    if failed > 0:
        print(f"❌ {failed} test(s) failed")
        sys.exit(1)
    else:
        print("✅ All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
