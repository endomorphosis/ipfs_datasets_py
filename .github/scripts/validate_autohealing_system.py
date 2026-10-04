#!/usr/bin/env python3
"""
Auto-Healing System Validation Script

This script validates that the comprehensive auto-healing system is properly configured
and all components are in place.
"""

import sys
import yaml
from pathlib import Path

def validate_workflow_file(workflow_path):
    """Validate a workflow YAML file."""
    try:
        with open(workflow_path) as f:
            data = yaml.safe_load(f)
        
        # Check if data loaded properly
        if not isinstance(data, dict):
            return False, "Invalid YAML structure"
        
        # 'on' might be loaded as True (boolean) in Python, check for both
        required_keys = ['name', 'jobs']
        for key in required_keys:
            if key not in data:
                return False, f"Missing required key: {key}"
        
        # 'on' is a special key in YAML that might be interpreted as True
        triggers = data.get('on', data.get(True, {}))
        if isinstance(triggers, dict):
            trigger_keys = list(triggers.keys())
        else:
            trigger_keys = []
        
        return True, {
            'name': data.get('name'),
            'jobs': len(data.get('jobs', {})),
            'triggers': trigger_keys
        }
    except Exception as e:
        return False, str(e)

def validate_copilot_autofix_tracking():
    """Validate that new workflows are tracked by copilot-agent-autofix."""
    autofix_path = Path('.github/workflows/copilot-agent-autofix.yml')
    
    with open(autofix_path) as f:
        data = yaml.safe_load(f)
    
    # 'on' might be loaded as True (boolean) in YAML
    on_key = data.get('on', data.get(True, {}))
    monitored = on_key.get('workflow_run', {}).get('workflows', [])
    
    required_workflows = [
        "CLI Tools Error Monitoring",
        "JavaScript SDK Error Monitoring",
        "MCP Tools Error Monitoring"
    ]
    
    missing = []
    for workflow in required_workflows:
        if workflow not in monitored:
            missing.append(workflow)
    
    return len(missing) == 0, {
        'total_monitored': len(monitored),
        'required_found': len(required_workflows) - len(missing),
        'missing': missing
    }

def validate_error_reporting_infrastructure():
    """Validate error reporting Python modules."""
    required_modules = [
        'ipfs_datasets_py.error_reporting.cli_error_reporter',
        'ipfs_datasets_py.error_reporting.error_reporter',
        'ipfs_datasets_py.error_reporting.github_issue_client'
    ]
    
    results = {}
    all_available = True
    
    for module_name in required_modules:
        try:
            __import__(module_name)
            results[module_name] = 'Available'
        except ImportError as e:
            results[module_name] = f'Missing: {e}'
            all_available = False
    
    return all_available, results

def validate_javascript_files():
    """Validate JavaScript SDK and error reporter files exist."""
    required_files = [
        'ipfs_datasets_py/static/js/mcp-sdk.js',
        'ipfs_datasets_py/static/js/mcp-api-client.js',
        'ipfs_datasets_py/static/js/error-reporter.js'
    ]
    
    results = {}
    all_exist = True
    
    for file_path in required_files:
        path = Path(file_path)
        if path.exists():
            results[file_path] = f'Exists ({path.stat().st_size} bytes)'
        else:
            results[file_path] = 'Missing'
            all_exist = False
    
    return all_exist, results

def validate_documentation():
    """Validate documentation files exist."""
    required_docs = [
        '.github/workflows/AUTO_HEALING_COMPREHENSIVE_GUIDE.md',
        '.github/workflows/AUTO_HEALING_QUICK_REFERENCE.md'
    ]
    
    results = {}
    all_exist = True
    
    for doc_path in required_docs:
        path = Path(doc_path)
        if path.exists():
            size_kb = path.stat().st_size / 1024
            results[doc_path] = f'Exists ({size_kb:.1f} KB)'
        else:
            results[doc_path] = 'Missing'
            all_exist = False
    
    return all_exist, results

def main():
    """Run all validations."""
    print("=" * 70)
    print("Auto-Healing System Validation")
    print("=" * 70)
    print()
    
    all_passed = True
    
    # Validate new workflow files
    print("1. Validating New Workflow Files")
    print("-" * 70)
    
    new_workflows = [
        '.github/workflows/cli-error-monitoring.yml',
        '.github/workflows/javascript-sdk-monitoring.yml',
        '.github/workflows/mcp-tools-monitoring.yml'
    ]
    
    for workflow_path in new_workflows:
        success, result = validate_workflow_file(workflow_path)
        if success:
            print(f"✅ {Path(workflow_path).name}")
            print(f"   Name: {result['name']}")
            print(f"   Jobs: {result['jobs']}")
            print(f"   Triggers: {', '.join(result['triggers'])}")
        else:
            print(f"❌ {Path(workflow_path).name}: {result}")
            all_passed = False
    print()
    
    # Validate copilot-agent-autofix tracking
    print("2. Validating Auto-Healing Tracking")
    print("-" * 70)
    
    success, result = validate_copilot_autofix_tracking()
    if success:
        print(f"✅ All new workflows tracked by copilot-agent-autofix")
        print(f"   Total monitored workflows: {result['total_monitored']}")
        print(f"   New workflows found: {result['required_found']}/3")
    else:
        print(f"❌ Some workflows not tracked:")
        for missing in result['missing']:
            print(f"   - {missing}")
        all_passed = False
    print()
    
    # Validate error reporting infrastructure
    print("3. Validating Error Reporting Infrastructure")
    print("-" * 70)
    
    success, results = validate_error_reporting_infrastructure()
    for module, status in results.items():
        module_name = module.split('.')[-1]
        if 'Available' in status:
            print(f"✅ {module_name}: {status}")
        else:
            print(f"❌ {module_name}: {status}")
    if not success:
        print("⚠️  Some modules unavailable (may be expected if dependencies not installed)")
    print()
    
    # Validate JavaScript files
    print("4. Validating JavaScript SDK Files")
    print("-" * 70)
    
    success, results = validate_javascript_files()
    for file_path, status in results.items():
        file_name = Path(file_path).name
        if 'Exists' in status:
            print(f"✅ {file_name}: {status}")
        else:
            print(f"❌ {file_name}: {status}")
            all_passed = False
    print()
    
    # Validate documentation
    print("5. Validating Documentation")
    print("-" * 70)
    
    success, results = validate_documentation()
    for doc_path, status in results.items():
        doc_name = Path(doc_path).name
        if 'Exists' in status:
            print(f"✅ {doc_name}: {status}")
        else:
            print(f"❌ {doc_name}: {status}")
            all_passed = False
    print()
    
    # Summary
    print("=" * 70)
    if all_passed:
        print("✅ All validations passed!")
        print()
        print("Auto-healing system is properly configured and ready to use.")
        print()
        print("Next steps:")
        print("  1. Commit and push changes to trigger workflows")
        print("  2. Monitor workflow execution")
        print("  3. Test error detection by introducing intentional errors")
        print("  4. Verify issue and PR creation")
        print("  5. Validate Copilot integration")
    else:
        print("❌ Some validations failed!")
        print()
        print("Please review the errors above and fix them before proceeding.")
        return 1
    
    print("=" * 70)
    return 0

if __name__ == '__main__':
    sys.exit(main())
