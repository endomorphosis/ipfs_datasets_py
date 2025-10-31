#!/usr/bin/env python3
"""
Test script to validate the issue-to-draft-pr workflow
This script validates the workflow structure and logic without actually running it
"""

import yaml
from pathlib import Path

def validate_workflow():
    """Validate the issue-to-draft-pr workflow file"""
    
    workflow_path = Path('.github/workflows/issue-to-draft-pr.yml')
    
    print("🔍 Validating Issue-to-Draft-PR Workflow\n")
    
    # 1. Check file exists
    assert workflow_path.exists(), f"Workflow file not found: {workflow_path}"
    print(f"✅ Workflow file exists: {workflow_path}")
    
    # 2. Load and validate YAML
    with open(workflow_path, 'r') as f:
        content = f.read()
        # Handle 'on' keyword
        content_safe = content.replace('\non:', '\n"on":')
        workflow = yaml.safe_load(content_safe)
    
    print("✅ YAML syntax is valid")
    
    # 3. Validate workflow name
    assert workflow.get('name'), "Workflow must have a name"
    print(f"✅ Workflow name: {workflow['name']}")
    
    # 4. Validate triggers
    on_config = workflow.get('on', workflow.get(True))
    assert on_config, "Workflow must have triggers ('on' section)"
    
    # Check for issues trigger
    assert 'issues' in on_config, "Must trigger on 'issues' events"
    assert 'types' in on_config['issues'], "Issues trigger must specify types"
    
    issue_types = on_config['issues']['types']
    assert 'opened' in issue_types, "Must trigger on 'opened' issues"
    assert 'reopened' in issue_types, "Must trigger on 'reopened' issues"
    print(f"✅ Triggers on issue events: {issue_types}")
    
    # Check for manual trigger
    assert 'workflow_dispatch' in on_config, "Should support manual dispatch"
    print("✅ Supports manual workflow dispatch")
    
    # 5. Validate permissions
    permissions = workflow.get('permissions', {})
    required_permissions = ['contents', 'pull-requests', 'issues']
    
    for perm in required_permissions:
        assert perm in permissions, f"Missing required permission: {perm}"
        assert permissions[perm] == 'write', f"Permission {perm} must be 'write'"
    
    print(f"✅ Has required permissions: {required_permissions}")
    
    # 6. Validate job structure
    jobs = workflow.get('jobs', {})
    assert jobs, "Workflow must have at least one job"
    
    main_job = jobs.get('create-draft-pr-with-copilot')
    assert main_job, "Missing main job 'create-draft-pr-with-copilot'"
    print("✅ Has main job: create-draft-pr-with-copilot")
    
    # 7. Validate job configuration
    assert 'runs-on' in main_job, "Job must specify runs-on"
    assert 'steps' in main_job, "Job must have steps"
    print(f"✅ Job has {len(main_job['steps'])} steps")
    
    # 8. Validate critical steps
    step_names = [step.get('name', '') for step in main_job['steps']]
    
    critical_steps = [
        'Install GitHub CLI',
        'Checkout repository',
        'Get issue details',
        'Check for existing draft PR',
        'Create draft PR',
    ]
    
    for critical_step in critical_steps:
        found = any(critical_step.lower() in name.lower() for name in step_names)
        assert found, f"Missing critical step containing: {critical_step}"
    
    print(f"✅ All critical steps present")
    
    # 9. Validate Copilot mentions
    workflow_str = content.lower()
    copilot_mentions = workflow_str.count('@copilot')
    assert copilot_mentions >= 2, "Should mention @copilot at least twice (PR body and comment)"
    print(f"✅ Mentions @copilot {copilot_mentions} times")
    
    # 10. Validate issue linking
    assert 'Fixes #' in content, "Should use 'Fixes #' to link PR to issue"
    print("✅ Uses 'Fixes #' syntax for issue linking")
    
    # 11. Validate branch naming
    assert 'issue-' in content, "Should create branches with 'issue-' prefix"
    print("✅ Creates branches with 'issue-' prefix")
    
    # 12. Validate duplicate prevention
    assert 'check_existing' in content or 'duplicate' in workflow_str, "Should check for duplicates"
    print("✅ Includes duplicate prevention")
    
    # 13. Validate artifact upload
    assert any('upload-artifact' in step.get('uses', '') for step in main_job['steps']), \
        "Should upload artifacts for debugging"
    print("✅ Uploads artifacts")
    
    print("\n" + "="*50)
    print("✅ ALL VALIDATIONS PASSED")
    print("="*50)
    print("\n🎉 The issue-to-draft-pr workflow is properly configured!")
    print("\n📝 Next steps:")
    print("   1. Enable workflow permissions in repository settings")
    print("   2. Create a test issue to verify workflow runs")
    print("   3. Monitor the workflow run in Actions tab")
    print("   4. Verify branch and PR are created")
    print("   5. Check @copilot is mentioned in the PR")


def validate_documentation():
    """Validate that documentation files exist and are complete"""
    
    print("\n\n🔍 Validating Documentation\n")
    
    docs = [
        '.github/workflows/README-issue-to-draft-pr.md',
        '.github/workflows/QUICKSTART-issue-to-draft-pr.md',
    ]
    
    for doc_path in docs:
        path = Path(doc_path)
        assert path.exists(), f"Documentation file missing: {doc_path}"
        
        with open(path, 'r') as f:
            content = f.read()
        
        # Check minimum content length
        assert len(content) > 1000, f"{doc_path} seems incomplete (too short)"
        
        # Check for key sections
        if 'README' in doc_path:
            required_sections = ['Overview', 'How It Works', 'Usage', 'Troubleshooting']
        else:  # QUICKSTART
            required_sections = ['Quick Setup', 'Test It', 'Example']
        
        for section in required_sections:
            assert section.lower() in content.lower(), \
                f"{doc_path} missing section: {section}"
        
        print(f"✅ {doc_path} is complete")
    
    # Check main README is updated
    main_readme = Path('.github/workflows/README.md')
    assert main_readme.exists(), "Main workflows README missing"
    
    with open(main_readme, 'r') as f:
        content = f.read()
    
    assert 'issue-to-draft-pr' in content.lower(), \
        "Main README should mention issue-to-draft-pr workflow"
    assert 'issue-to-draft-pr.yml' in content, \
        "Main README should link to workflow file"
    
    print("✅ Main README is updated with new workflow")
    
    print("\n✅ ALL DOCUMENTATION VALIDATED")


def main():
    """Run all validations"""
    try:
        validate_workflow()
        validate_documentation()
        
        print("\n\n" + "🎊"*25)
        print("\n✅ ✅ ✅  ALL TESTS PASSED  ✅ ✅ ✅")
        print("\n" + "🎊"*25)
        print("\n")
        print("The issue-to-draft-pr workflow is ready to use!")
        print("\nTo enable it:")
        print("  1. Go to Settings → Actions → General → Workflow permissions")
        print("  2. Select 'Read and write permissions'")
        print("  3. Check 'Allow GitHub Actions to create and approve pull requests'")
        print("\nThen create an issue to test it!")
        
        return 0
        
    except AssertionError as e:
        print(f"\n❌ VALIDATION FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())
