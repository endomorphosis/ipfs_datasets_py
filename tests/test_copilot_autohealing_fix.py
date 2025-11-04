#!/usr/bin/env python3
"""
Tests for the Copilot auto-healing workflow improvements

This test validates that the updated workflow components work correctly:
1. generate_copilot_instruction.py script
2. invoke_copilot_with_queue.py fallback mechanism
3. Integration between components
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_generate_copilot_instruction_script_exists():
    """Test that the generate_copilot_instruction.py script exists and is executable."""
    script_path = project_root / ".github" / "scripts" / "generate_copilot_instruction.py"
    assert script_path.exists(), "Script file does not exist"
    assert os.access(script_path, os.X_OK), "Script is not executable"
    print("✅ generate_copilot_instruction.py exists and is executable")


def test_generate_copilot_instruction_help():
    """Test that --help works for generate_copilot_instruction.py."""
    result = subprocess.run(
        ["python3", ".github/scripts/generate_copilot_instruction.py", "--help"],
        capture_output=True,
        text=True,
        cwd=project_root
    )
    
    assert result.returncode == 0, "Help command failed"
    assert "usage:" in result.stdout.lower(), "Help output missing usage"
    assert "analysis_file" in result.stdout, "Help missing analysis_file argument"
    print("✅ generate_copilot_instruction.py --help works correctly")


def test_generate_copilot_instruction_with_analysis():
    """Test instruction generation with a sample failure analysis."""
    # Create a temporary failure analysis file
    analysis_data = {
        "error_type": "Test Failure",
        "root_cause": "Assertion error in test_example",
        "fix_confidence": 90,
        "recommendations": [
            "Update test assertions to match new behavior",
            "Check for race conditions in async tests",
            "Verify test data setup is correct"
        ]
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(analysis_data, f)
        temp_file = f.name
    
    try:
        result = subprocess.run(
            ["python3", ".github/scripts/generate_copilot_instruction.py", temp_file],
            capture_output=True,
            text=True,
            cwd=project_root
        )
        
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        
        output = result.stdout
        
        # Verify instruction contains key information
        assert "Test Failure" in output, "Missing error type"
        assert "Assertion error in test_example" in output, "Missing root cause"
        assert "90%" in output, "Missing confidence level"
        assert "Update test assertions" in output, "Missing first recommendation"
        assert "Error Analysis:" in output, "Missing error analysis section"
        assert "Recommended Actions:" in output, "Missing recommendations section"
        assert "Instructions:" in output, "Missing instructions section"
        
        print("✅ Instruction generation works with proper structure")
        
    finally:
        os.unlink(temp_file)


def test_generate_copilot_instruction_missing_file():
    """Test that script handles missing files gracefully."""
    result = subprocess.run(
        ["python3", ".github/scripts/generate_copilot_instruction.py", "/tmp/nonexistent.json"],
        capture_output=True,
        text=True,
        cwd=project_root
    )
    
    # Should return non-zero but provide default instruction
    assert result.returncode != 0, "Should fail with missing file"
    assert "Please analyze and fix" in result.stdout, "Missing fallback instruction"
    print("✅ Missing file handled gracefully with fallback instruction")


def test_invoke_copilot_with_queue_fallback():
    """Test that invoke_copilot_with_queue.py handles fallback mode."""
    result = subprocess.run(
        ["python3", "scripts/invoke_copilot_with_queue.py", "--status"],
        capture_output=True,
        text=True,
        cwd=project_root
    )
    
    # Should complete successfully (even if Copilot CLI not available)
    # and show fallback mode status
    output = result.stdout + result.stderr
    
    # Check for fallback indicators
    assert "Fallback" in output or "fallback" in output.lower(), \
        "Fallback mode not indicated in status"
    
    print("✅ invoke_copilot_with_queue.py shows fallback mode correctly")


def test_workflow_yaml_syntax():
    """Test that the workflow YAML is valid."""
    import yaml
    
    workflow_file = project_root / ".github" / "workflows" / "copilot-agent-autofix.yml"
    
    with open(workflow_file) as f:
        try:
            workflow_data = yaml.safe_load(f)
            assert workflow_data is not None, "Workflow YAML is empty"
            assert "name" in workflow_data, "Workflow missing name field"
            assert "jobs" in workflow_data, "Workflow missing jobs field"
            print("✅ Workflow YAML syntax is valid")
        except yaml.YAMLError as e:
            raise AssertionError(f"YAML syntax error: {e}")


def test_workflow_uses_correct_script():
    """Test that the workflow uses invoke_copilot_on_pr.py, not invoke_copilot_with_queue.py."""
    workflow_file = project_root / ".github" / "workflows" / "copilot-agent-autofix.yml"
    
    with open(workflow_file) as f:
        content = f.read()
    
    # Should use invoke_copilot_on_pr.py for reliability
    assert "invoke_copilot_on_pr.py" in content, \
        "Workflow should use invoke_copilot_on_pr.py"
    
    # Should also reference the new instruction generator
    assert "generate_copilot_instruction.py" in content, \
        "Workflow should use generate_copilot_instruction.py"
    
    print("✅ Workflow uses correct scripts (invoke_copilot_on_pr.py + generator)")


def main():
    """Run all tests."""
    print("🧪 Testing Copilot Auto-Healing Workflow Improvements\n")
    
    tests = [
        test_generate_copilot_instruction_script_exists,
        test_generate_copilot_instruction_help,
        test_generate_copilot_instruction_with_analysis,
        test_generate_copilot_instruction_missing_file,
        test_invoke_copilot_with_queue_fallback,
        test_workflow_yaml_syntax,
        test_workflow_uses_correct_script,
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
            import traceback
            traceback.print_exc()
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
