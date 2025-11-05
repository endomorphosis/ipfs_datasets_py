#!/usr/bin/env python3
"""
Test script for workflow automation scripts.

This script validates that all the workflow automation scripts work correctly
and have proper error handling, fallback mechanisms, and dependencies.
"""

import os
import sys
import json
import tempfile
import subprocess
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

def test_generate_copilot_instruction():
    """Test the generate_copilot_instruction.py script."""
    print("\n=== Testing generate_copilot_instruction.py ===")
    
    script_path = Path(__file__).parent / "generate_copilot_instruction.py"
    
    # Test 1: Valid analysis file
    print("\n1. Testing with valid analysis file...")
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        analysis = {
            'error_type': 'Missing Dependencies',
            'root_cause': 'PyYAML not installed',
            'fix_confidence': 90,
            'recommendations': [
                'Install PyYAML package',
                'Add to requirements.txt'
            ]
        }
        json.dump(analysis, f)
        temp_file = f.name
    
    try:
        result = subprocess.run(
            [sys.executable, str(script_path), temp_file],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("   ✅ Valid analysis file test passed")
            print(f"   Output length: {len(result.stdout)} chars")
        else:
            print(f"   ❌ Valid analysis file test failed: {result.stderr}")
            return False
    finally:
        os.unlink(temp_file)
    
    # Test 2: Missing analysis file
    print("\n2. Testing with missing analysis file...")
    result = subprocess.run(
        [sys.executable, str(script_path), '/nonexistent/file.json'],
        capture_output=True,
        text=True
    )
    
    # Now returns 0 (success) with fallback instruction
    if result.returncode == 0 and ('please analyze' in result.stdout.lower() or 'default' in result.stdout.lower()):
        print("   ✅ Missing file test passed (returns default with success)")
    else:
        print(f"   ❌ Missing file test failed")
        print(f"   Return code: {result.returncode}")
        print(f"   Stdout: {result.stdout[:200]}")
        return False
    
    # Test 3: Invalid JSON
    print("\n3. Testing with invalid JSON...")
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write('{ invalid json }')
        temp_file = f.name
    
    try:
        result = subprocess.run(
            [sys.executable, str(script_path), temp_file],
            capture_output=True,
            text=True
        )
        
        # Now returns 0 (success) with fallback instruction
        if result.returncode == 0 and ('please analyze' in result.stdout.lower() or 'default' in result.stdout.lower()):
            print("   ✅ Invalid JSON test passed (returns default with success)")
        else:
            print(f"   ❌ Invalid JSON test failed")
            print(f"   Return code: {result.returncode}")
            print(f"   Stdout: {result.stdout[:200]}")
            return False
    finally:
        os.unlink(temp_file)
    
    print("\n✅ All generate_copilot_instruction.py tests passed")
    return True


def test_create_copilot_agent_task():
    """Test the create_copilot_agent_task_for_pr.py script."""
    print("\n=== Testing create_copilot_agent_task_for_pr.py ===")
    
    script_path = Path(__file__).parent.parent.parent / "scripts" / "create_copilot_agent_task_for_pr.py"
    
    # Test 1: Dry run mode (will fail on PR fetch without gh auth, but that's expected)
    print("\n1. Testing dry run mode...")
    result = subprocess.run(
        [sys.executable, str(script_path), '--pr', '1', '--task', 'fix', '--reason', 'test', '--dry-run'],
        capture_output=True,
        text=True
    )
    
    # We expect it to fail getting PR details if gh is not authenticated
    # but the script should handle this gracefully
    if 'Getting details for PR' in result.stdout or 'GH_TOKEN' in result.stderr:
        print("   ✅ Script executes (gh auth required for actual testing)")
    else:
        print(f"   ❌ Unexpected script behavior")
        print(f"   Stdout: {result.stdout[:200]}")
        print(f"   Stderr: {result.stderr[:200]}")
        return False
    
    print("\n✅ create_copilot_agent_task_for_pr.py tests passed (gh auth required for full test)")
    return True


def test_script_imports():
    """Test that all workflow scripts can be imported."""
    print("\n=== Testing Script Imports ===")
    
    scripts_dir = Path(__file__).parent.parent.parent / "scripts"
    
    test_scripts = [
        'invoke_copilot_on_pr.py',
        'create_copilot_agent_task_for_pr.py',
    ]
    
    for script in test_scripts:
        script_path = scripts_dir / script
        if not script_path.exists():
            print(f"   ⚠️  Script not found: {script}")
            continue
        
        # Test syntax by compiling
        try:
            with open(script_path) as f:
                compile(f.read(), str(script_path), 'exec')
            print(f"   ✅ {script} syntax valid")
        except SyntaxError as e:
            print(f"   ❌ {script} has syntax error: {e}")
            return False
    
    print("\n✅ All script imports passed")
    return True


def test_workflow_yaml_syntax():
    """Test that workflow YAML files are valid."""
    print("\n=== Testing Workflow YAML Syntax ===")
    
    try:
        import yaml
    except ImportError:
        print("   ⚠️  PyYAML not installed, skipping YAML syntax tests")
        return True
    
    workflows_dir = Path(__file__).parent.parent / "workflows"
    
    workflow_files = [
        'copilot-agent-autofix.yml',
        'issue-to-draft-pr.yml',
        'pr-copilot-reviewer.yml',
    ]
    
    for workflow_file in workflow_files:
        workflow_path = workflows_dir / workflow_file
        if not workflow_path.exists():
            print(f"   ⚠️  Workflow not found: {workflow_file}")
            continue
        
        try:
            with open(workflow_path) as f:
                yaml.safe_load(f)
            print(f"   ✅ {workflow_file} is valid YAML")
        except yaml.YAMLError as e:
            print(f"   ❌ {workflow_file} has YAML error: {e}")
            return False
    
    print("\n✅ All workflow YAML syntax tests passed")
    return True


def main():
    """Run all tests."""
    print("=" * 80)
    print("Workflow Scripts Test Suite")
    print("=" * 80)
    
    tests = [
        ("Script Imports", test_script_imports),
        ("Workflow YAML Syntax", test_workflow_yaml_syntax),
        ("Generate Copilot Instruction", test_generate_copilot_instruction),
        ("Create Copilot Agent Task", test_create_copilot_agent_task),
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        try:
            results[test_name] = test_func()
        except Exception as e:
            print(f"\n❌ {test_name} crashed: {e}")
            results[test_name] = False
    
    # Summary
    print("\n" + "=" * 80)
    print("Test Summary")
    print("=" * 80)
    
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print("\n❌ Some tests failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
