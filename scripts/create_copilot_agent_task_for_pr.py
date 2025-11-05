#!/usr/bin/env python3
"""
Create Copilot Coding Agent Task for a PR

This script creates a proper Copilot Coding Agent task using gh agent-task create
for a given pull request, based on the task type.

Usage:
    python scripts/create_copilot_agent_task_for_pr.py --pr 123 --task fix --reason "workflow failure"
    python scripts/create_copilot_agent_task_for_pr.py --pr 123 --task implement --reason "draft PR needs implementation"
"""

import subprocess
import argparse
import sys
import json
from typing import Dict, Any, Optional


def run_gh_command(cmd: list, input_text: Optional[str] = None) -> Dict[str, Any]:
    """Run a gh CLI command and return the result."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            input=input_text,
            timeout=60
        )
        return {
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        }
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'error': 'Command timed out',
            'returncode': -1
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'returncode': -1
        }


def get_pr_details(pr_number: str, repo: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Get PR details from GitHub."""
    cmd = ['gh', 'pr', 'view', pr_number, '--json', 'title,body,number,author,isDraft,labels,state']
    if repo:
        cmd.extend(['--repo', repo])
    
    result = run_gh_command(cmd)
    if result['success']:
        try:
            return json.loads(result['stdout'])
        except json.JSONDecodeError:
            print(f"Error: Failed to parse PR details")
            return None
    else:
        print(f"Error getting PR details: {result['stderr']}")
        return None


def create_task_description(pr_details: Dict[str, Any], task_type: str, reason: str) -> str:
    """Create a comprehensive task description based on the task type."""
    pr_number = pr_details['number']
    pr_title = pr_details['title']
    pr_body = pr_details.get('body', '')
    
    # Truncate PR body if too long to avoid comment length limits
    max_body_length = 1000
    if len(pr_body) > max_body_length:
        pr_body = pr_body[:max_body_length] + "\n\n...(truncated)"
    
    base_desc = f"""Work on PR #{pr_number}: {pr_title}

Assignment Reason: {reason}

PR Body:
{pr_body if pr_body else 'No description provided'}
"""
    
    if task_type == "fix":
        return base_desc + """

Objective: Review this PR and implement the necessary fixes.

Focus areas:
- Analyze the problem described in the PR
- Implement minimal, surgical fixes
- Ensure all tests pass
- Follow existing code patterns in the repository
- Update documentation if needed

Instructions:
1. Review the PR description and linked issues thoroughly
2. Understand the specific problem being addressed
3. Implement the fix with minimal code changes
4. Validate that the fix doesn't break existing functionality
5. Add or update tests if appropriate
"""
    
    elif task_type == "implement":
        return base_desc + """

Objective: Implement the solution described in this draft PR.

Instructions:
1. Review the PR description and any linked issues
2. Understand the requirements and acceptance criteria
3. Implement the solution following repository patterns
4. Add or update tests as appropriate
5. Update documentation if directly related
6. Make surgical, minimal changes focused on the requirements

Important:
- Follow the existing code style
- Avoid modifying unrelated code
- Ensure all tests pass before completion
"""
    
    elif task_type == "review":
        return base_desc + """

Objective: Review this pull request and provide feedback or implement improvements.

Analysis areas:
- Code quality and best practices
- Test coverage and test quality
- Documentation completeness
- Potential issues or improvements
- Performance considerations

Instructions:
1. Thoroughly review all changes in the PR
2. Identify any issues or areas for improvement
3. Suggest or implement necessary changes
4. Ensure code follows repository standards
"""
    
    else:
        return base_desc + "\n\nPlease review and work on this PR according to the requirements described."


def create_agent_task(pr_number: str, pr_details: Dict[str, Any], task_type: str, 
                     reason: str, repo: Optional[str] = None, dry_run: bool = False) -> bool:
    """Create a Copilot Coding Agent task using gh agent-task create."""
    
    # Create task description
    task_description = create_task_description(pr_details, task_type, reason)
    
    print(f"📝 Task description (first 200 chars):")
    print(task_description[:200] + "...")
    print()
    
    if dry_run:
        print("🔍 DRY RUN: Would create agent task with the above description")
        return True
    
    # Try to create agent task
    print("🤖 Creating Copilot Coding Agent task using gh agent-task create...")
    
    cmd = ['gh', 'agent-task', 'create', '-F', '-']
    if repo:
        cmd.extend(['--repo', repo])
    
    result = run_gh_command(cmd, input_text=task_description)
    
    if result['success']:
        print(f"✅ Successfully created agent task for PR #{pr_number}")
        print(result['stdout'])
        return True
    else:
        print(f"❌ Failed to create agent task: {result['stderr']}")
        
        # Check if command not available
        if 'unknown command' in result['stderr'].lower() or 'not found' in result['stderr'].lower():
            print("\n⚠️  gh agent-task command not available")
            print("🔄 Attempting fallback: Creating PR comment with @copilot mention...")
            # Use fallback and return its result
            return create_copilot_comment_fallback(pr_number, task_description, repo)
        
        # For other errors, return False
        return False


def create_copilot_comment_fallback(pr_number: str, task_description: str, 
                                    repo: Optional[str] = None) -> bool:
    """Fallback method: Create a comment on the PR mentioning @copilot."""
    
    # Create a comment with @copilot mention and the task description
    comment_body = f"""@copilot please work on this PR.

{task_description}

---
*Note: This task was created using the fallback method because `gh agent-task` is not available.*
"""
    
    cmd = ['gh', 'pr', 'comment', pr_number, '--body', comment_body]
    if repo:
        cmd.extend(['--repo', repo])
    
    result = run_gh_command(cmd)
    
    if result['success']:
        print(f"✅ Successfully created PR comment with @copilot mention for PR #{pr_number}")
        print("Note: Using comment-based invocation instead of agent-task API")
        return True
    else:
        print(f"❌ Fallback also failed: {result['stderr']}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Create Copilot Coding Agent task for a PR'
    )
    parser.add_argument(
        '--pr',
        required=True,
        help='PR number'
    )
    parser.add_argument(
        '--task',
        required=True,
        choices=['fix', 'implement', 'review'],
        help='Task type: fix, implement, or review'
    )
    parser.add_argument(
        '--reason',
        required=True,
        help='Reason for assignment (e.g., "workflow failure", "draft PR needs implementation")'
    )
    parser.add_argument(
        '--repo',
        help='Repository in OWNER/REPO format (defaults to current repo)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    
    args = parser.parse_args()
    
    # Get PR details
    print(f"📋 Getting details for PR #{args.pr}...")
    pr_details = get_pr_details(args.pr, args.repo)
    
    if not pr_details:
        print("❌ Failed to get PR details")
        sys.exit(1)
    
    print(f"✅ Found PR: {pr_details['title']}")
    print(f"   Author: {pr_details['author']['login']}")
    print(f"   State: {pr_details['state']}")
    print(f"   Draft: {pr_details['isDraft']}")
    print()
    
    # Create agent task
    success = create_agent_task(
        args.pr,
        pr_details,
        args.task,
        args.reason,
        args.repo,
        args.dry_run
    )
    
    if success:
        print("\n✅ Agent task created successfully!")
        print(f"\nMonitor progress with:")
        print(f"  gh agent-task list{' --repo ' + args.repo if args.repo else ''}")
        sys.exit(0)
    else:
        print("\n❌ Failed to create agent task")
        sys.exit(1)


if __name__ == '__main__':
    main()
