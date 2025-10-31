#!/usr/bin/env python3
"""
Batch process all open PRs and assign Copilot where appropriate.

This script analyzes all open pull requests and automatically assigns
GitHub Copilot to work on them based on specific criteria.
"""

import subprocess
import json
import sys
import re
from typing import Dict, List, Any, Optional


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


def assign_copilot(pr_number: int, task: str, reason: str, pr_title: str) -> bool:
    """Assign Copilot to a PR with appropriate task."""
    # Create task-specific comment
    if task == 'fix':
        comment = f"""@copilot /fix

Please review this PR and implement the necessary fixes.

**Reason**: {reason}

**Focus areas**:
- Analyze the problem described
- Implement minimal, surgical fixes
- Ensure tests pass
- Follow existing code patterns
- Update documentation if needed

**PR**: #{pr_number} - {pr_title}"""
    
    elif task == 'implement':
        comment = f"""@copilot Please implement the solution described in this PR.

**Reason**: {reason}

**Instructions**:
1. Review the PR description and any linked issues
2. Understand the requirements
3. Implement the solution following repository patterns
4. Add or update tests as appropriate
5. Update documentation if directly related

**PR**: #{pr_number} - {pr_title}"""
    
    else:  # review
        comment = f"""@copilot /review

Please review this pull request and provide feedback.

**Reason**: {reason}

Please analyze:
- Code quality and best practices
- Test coverage
- Documentation completeness
- Potential issues or improvements

**PR**: #{pr_number} - {pr_title}"""
    
    # Post comment
    result = run_gh_command([
        'pr', 'comment', str(pr_number),
        '--body', comment
    ])
    
    return result['success']


def main():
    """Main execution function."""
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
        
        # Assign Copilot
        if assign_copilot(pr_number, task, reason, pr_title):
            print(f"   ✅ Successfully assigned Copilot")
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
