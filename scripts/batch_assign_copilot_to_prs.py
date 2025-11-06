#!/usr/bin/env python3
"""
⚠️⚠️⚠️ DEPRECATED - DO NOT USE ⚠️⚠️⚠️

This script is DEPRECATED and should NOT be used.

Reason: Uses `gh agent-task create` which DOES NOT EXIST

This script claims to use "Official GitHub CLI command" but gh agent-task
has NEVER existed. All workflows using this had 0% success rate.

The correct method is the DUAL METHOD:
1. Create draft PR
2. Post @copilot trigger comment

Migration: Use scripts/invoke_copilot_on_pr.py instead

Examples:
  # Single PR
  python scripts/invoke_copilot_on_pr.py --pr 123 --instruction "Fix the issues"
  
  # Batch processing (loop)
  gh pr list --state open --json number --jq '.[].number' | while read pr; do
    python scripts/invoke_copilot_on_pr.py --pr $pr
  done

See:
- DEPRECATED_SCRIPTS.md - Full deprecation documentation
- COPILOT_INVOCATION_GUIDE.md - Verified working method
"""

import sys

print("=" * 80)
print("⚠️  ERROR: This script is DEPRECATED and should not be used!")
print("=" * 80)
print()
print("This script uses 'gh agent-task create' which DOES NOT EXIST.")
print("This command has NEVER been part of GitHub CLI.")
print()
print("✅ Use instead: scripts/invoke_copilot_on_pr.py")
print()
print("📖 Documentation:")
print("   - DEPRECATED_SCRIPTS.md")
print("   - COPILOT_INVOCATION_GUIDE.md")
print()
print("=" * 80)
sys.exit(1)

# Original code below (disabled)
"""
Batch process all open PRs and assign Copilot where appropriate.

This script analyzes all open pull requests and automatically assigns
GitHub Copilot Coding Agent to work on them using the OFFICIAL method:
gh agent-task create

Per GitHub's official documentation:
- https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent
- https://docs.github.com/en/copilot/concepts/agents/coding-agent/agent-management

This script uses:
✅ gh agent-task create - Official GitHub CLI command for Copilot Coding Agent
✅ CopilotCLI utility wrapper - Python wrapper for gh commands

This script does NOT use:
❌ @copilot mentions in PR comments - NOT supported by GitHub
"""

import subprocess
import json
import sys
import re
from typing import Dict, List, Any, Optional
from pathlib import Path

# Try to import the copilot CLI utility
try:
    script_dir = Path(__file__).parent.parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    
    from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
    COPILOT_CLI_AVAILABLE = True
except ImportError:
    COPILOT_CLI_AVAILABLE = False
    print("⚠️  CopilotCLI utility not available, using direct gh commands")


def run_gh_command(cmd: List[str]) -> Dict[str, Any]:
    """Run a GitHub CLI command and return the result."""
    try:
        result = subprocess.run(
            ['gh'] + cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30
        )
        return {
            'success': True,
            'stdout': result.stdout,
            'stderr': result.stderr
        }
    except subprocess.CalledProcessError as e:
        return {
            'success': False,
            'error': str(e),
            'stdout': e.stdout,
            'stderr': e.stderr
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def get_all_prs(state: str = 'open', limit: int = 100) -> List[Dict[str, Any]]:
    """Get all PRs matching the criteria."""
    result = run_gh_command([
        'pr', 'list',
        '--state', state,
        '--limit', str(limit),
        '--json', 'number,title,isDraft,author,labels,state,body'
    ])
    
    if not result['success']:
        print(f"❌ Failed to get PRs: {result.get('error')}")
        return []
    
    try:
        prs = json.loads(result['stdout'])
        return prs
    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse PR data: {e}")
        return []


def check_copilot_assigned(pr_number: int) -> bool:
    """Check if Copilot has already been assigned to a PR."""
    # Check for recent agent tasks
    result = run_gh_command([
        'agent-task', 'list', '--limit', '50'
    ])
    
    if result['success']:
        # Check if there's an active task for this PR
        if f"#{pr_number}" in result['stdout'] or f"pull/{pr_number}" in result['stdout']:
            return True
    
    # Also check for @copilot mentions as fallback
    result = run_gh_command([
        'pr', 'view', str(pr_number),
        '--json', 'comments',
        '--jq', '.comments[].body'
    ])
    
    if not result['success']:
        return False
    
    comments = result['stdout']
    return '@copilot' in comments


def analyze_pr(pr: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze a PR to determine if Copilot should be assigned."""
    pr_number = pr['number']
    pr_title = pr['title']
    is_draft = pr['isDraft']
    pr_body = pr.get('body', '')
    
    analysis = {
        'should_assign': False,
        'assignment_reason': [],
        'copilot_task': 'review',
        'confidence': 0
    }
    
    # Check if auto-generated
    if 'auto-generated' in pr_body.lower() or 'automated' in pr_title.lower():
        analysis['should_assign'] = True
        analysis['assignment_reason'].append("auto-generated PR")
        analysis['confidence'] += 30
    
    # Check if workflow fix
    if 'workflow' in pr_title.lower() or 'auto-fix' in pr_title.lower():
        analysis['should_assign'] = True
        analysis['assignment_reason'].append("workflow fix")
        analysis['copilot_task'] = 'fix'
        analysis['confidence'] += 40
    
    # Check if issue resolution
    issue_pattern = r'#\d+|fixes|closes|resolves'
    if re.search(issue_pattern, pr_body.lower() + pr_title.lower()):
        analysis['should_assign'] = True
        analysis['assignment_reason'].append("resolves issue")
        analysis['confidence'] += 25
    
    # Check if draft needing implementation
    if is_draft and len(pr_body) > 100:
        analysis['should_assign'] = True
        analysis['assignment_reason'].append("draft needing implementation")
        analysis['copilot_task'] = 'implement'
        analysis['confidence'] += 35
    
    # If draft but no clear reason, still consider for review
    if is_draft and not analysis['should_assign']:
        analysis['should_assign'] = True
        analysis['assignment_reason'].append("draft for review")
        analysis['confidence'] += 15
    
    return analysis


def assign_copilot(pr_number: int, task: str, reason: str, pr_title: str, pr_body: str = "", branch_name: str = "") -> bool:
    """
    Assign Copilot Coding Agent to a PR using gh agent-task create.
    
    This is the OFFICIAL method per GitHub documentation:
    https://docs.github.com/en/copilot/concepts/agents/coding-agent/agent-management
    """
    
    # Get branch name if not provided
    if not branch_name:
        result = run_gh_command([
            'pr', 'view', str(pr_number),
            '--json', 'headRefName',
            '--jq', '.headRefName'
        ])
        if result['success']:
            branch_name = result['stdout'].strip()
    
    # Create comprehensive task description
    if task == 'fix':
        task_description = f"""Fix issues in PR #{pr_number}: {pr_title}

**Reason**: {reason}
**Branch**: {branch_name}

**Context**:
{pr_body[:400] if pr_body else 'No additional context provided'}

**Focus areas**:
- Analyze the problem described in the PR
- Implement minimal, surgical fixes
- Ensure all tests pass
- Follow existing code patterns and style
- Update documentation only if directly related

**Instructions**:
1. Review the PR description and any linked issues
2. Understand the root cause of the issue
3. Implement the fix with minimal changes
4. Run tests to validate the fix
5. Ensure no regressions are introduced"""
    
    elif task == 'implement':
        task_description = f"""Implement solution for PR #{pr_number}: {pr_title}

**Reason**: {reason}
**Branch**: {branch_name}

**Context**:
{pr_body[:400] if pr_body else 'No additional context provided'}

**Instructions**:
1. Review the PR description and any linked issues
2. Understand the requirements and acceptance criteria
3. Implement the solution following repository patterns
4. Add or update tests as appropriate
5. Update documentation if directly related to changes
6. Use minimal, focused changes"""
    
    else:  # review
        task_description = f"""Review PR #{pr_number}: {pr_title}

**Reason**: {reason}
**Branch**: {branch_name}

**Context**:
{pr_body[:400] if pr_body else 'No additional context provided'}

**Review focus**:
- Code quality and best practices
- Test coverage and correctness
- Documentation completeness
- Potential issues or improvements
- Security considerations

Please provide feedback and suggestions for improvement."""
    
    # Method 1: Try using CopilotCLI utility (preferred)
    if COPILOT_CLI_AVAILABLE:
        try:
            copilot = CopilotCLI()
            result = copilot.create_agent_task(
                task_description=task_description,
                base_branch=branch_name
            )
            
            if result.get('success'):
                print(f"   ✅ Created agent task using CopilotCLI")
                return True
            else:
                print(f"   ⚠️  CopilotCLI failed: {result.get('error', 'Unknown error')}")
        except Exception as e:
            print(f"   ⚠️  CopilotCLI exception: {e}")
    
    # Method 2: Direct gh agent-task create command
    result = run_gh_command([
        'agent-task', 'create',
        task_description,
        '--base', branch_name
    ])
    
    if result['success']:
        print(f"   ✅ Created agent task using gh agent-task")
        return True
    else:
        error_msg = result.get('error', result.get('stderr', ''))
        
        # Check if gh agent-task is not available
        if 'unknown command' in error_msg.lower() or 'not found' in error_msg.lower():
            print(f"   ❌ gh agent-task command not available on this system")
            print(f"   💡 Install/update GitHub CLI extension: gh extension install github/gh-copilot")
            print(f"   📚 See: https://docs.github.com/en/copilot/concepts/agents/coding-agent/")
        else:
            print(f"   ❌ Failed to create agent task: {error_msg}")
        
        return False


def main():
    """Main execution function."""
    print("=" * 80)
    print("🤖 GitHub Copilot Batch Assignment Tool")
    print("=" * 80)
    print()
    print("💡 Using OFFICIAL GitHub Copilot invocation method:")
    print("   ✅ gh agent-task create (GitHub CLI)")
    print("   ✅ CopilotCLI utility wrapper")
    print("   📚 https://docs.github.com/en/copilot/concepts/agents/coding-agent/")
    print()
    print("❌ NOT using:")
    print("   ❌ @copilot mentions in PR comments (unsupported)")
    print("=" * 80)
    print()
    
    print("🔍 Scanning open pull requests...")
    print("=" * 80)
    
    # Get all open PRs
    prs = get_all_prs(state='open', limit=100)
    
    if not prs:
        print("No open PRs found.")
        return
    
    print(f"Found {len(prs)} open PRs\n")
    
    # Track statistics
    stats = {
        'total': len(prs),
        'analyzed': 0,
        'already_assigned': 0,
        'newly_assigned': 0,
        'skipped': 0,
        'errors': 0
    }
    
    # Process each PR
    for pr in prs:
        pr_number = pr['number']
        pr_title = pr['title']
        is_draft = pr['isDraft']
        pr_body = pr.get('body', '')
        
        print(f"\n📄 PR #{pr_number}: {pr_title}")
        print(f"   Draft: {is_draft}")
        
        stats['analyzed'] += 1
        
        # Check if Copilot already assigned
        if check_copilot_assigned(pr_number):
            print(f"   ✅ Copilot already assigned - skipping")
            stats['already_assigned'] += 1
            continue
        
        # Analyze PR
        analysis = analyze_pr(pr)
        
        if not analysis['should_assign']:
            print(f"   ⏭️  No assignment needed")
            stats['skipped'] += 1
            continue
        
        reason = ', '.join(analysis['assignment_reason'])
        task = analysis['copilot_task']
        confidence = analysis['confidence']
        
        print(f"   🎯 Should assign: {task} (confidence: {confidence}%)")
        print(f"   📝 Reason: {reason}")
        
        # Get branch name for the PR
        branch_result = run_gh_command([
            'pr', 'view', str(pr_number),
            '--json', 'headRefName',
            '--jq', '.headRefName'
        ])
        branch_name = branch_result['stdout'].strip() if branch_result['success'] else ""
        
        # Assign Copilot using gh agent-task create
        if assign_copilot(pr_number, task, reason, pr_title, pr_body, branch_name):
            print(f"   ✅ Successfully assigned Copilot Coding Agent")
            stats['newly_assigned'] += 1
        else:
            print(f"   ❌ Failed to assign Copilot")
            stats['errors'] += 1
    
    # Print summary
    print("\n" + "=" * 80)
    print("📊 Summary:")
    print(f"   Total PRs:          {stats['total']}")
    print(f"   Analyzed:           {stats['analyzed']}")
    print(f"   Already assigned:   {stats['already_assigned']}")
    print(f"   Newly assigned:     {stats['newly_assigned']}")
    print(f"   Skipped:            {stats['skipped']}")
    print(f"   Errors:             {stats['errors']}")
    print("=" * 80)
    
    if stats['newly_assigned'] > 0:
        print(f"\n✨ Successfully assigned Copilot to {stats['newly_assigned']} PR(s)!")
    else:
        print(f"\nℹ️  No new assignments made.")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
