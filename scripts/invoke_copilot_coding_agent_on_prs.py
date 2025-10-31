#!/usr/bin/env python3
"""
Invoke GitHub Copilot Coding Agent on Pull Requests

This script uses GitHub CLI and the new GitHub Copilot Coding Agent
to automatically assign Copilot to work on draft PRs.

Based on:
- https://github.blog/news-insights/company-news/welcome-home-agents/
- https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent
- https://docs.github.com/en/copilot/concepts/agents/code-review

Usage:
    python invoke_copilot_coding_agent_on_prs.py [--pr PR_NUMBER] [--dry-run]
"""

import subprocess
import json
import sys
import argparse
from typing import Dict, List, Any, Optional
from datetime import datetime


class CopilotCodingAgentInvoker:
    """Manages invocation of GitHub Copilot Coding Agent on PRs."""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        
    def run_command(self, cmd: List[str]) -> Dict[str, Any]:
        """Run a shell command and return the result."""
        try:
            result = subprocess.run(
                cmd,
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
    
    def get_pr_details(self, pr_number: int) -> Optional[Dict[str, Any]]:
        """Get detailed information about a PR."""
        result = self.run_command([
            'gh', 'pr', 'view', str(pr_number),
            '--json', 'number,title,body,isDraft,state,author,labels,comments,files'
        ])
        
        if not result['success']:
            print(f"❌ Failed to get PR #{pr_number}: {result.get('error')}")
            return None
        
        try:
            return json.loads(result['stdout'])
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse PR data: {e}")
            return None
    
    def check_copilot_already_invoked(self, pr_details: Dict[str, Any]) -> bool:
        """Check if Copilot has already been invoked on this PR."""
        comments = pr_details.get('comments', [])
        
        for comment in comments:
            body = comment.get('body', '')
            if '@copilot' in body.lower() or '@github-copilot' in body.lower():
                return True
        
        return False
    
    def analyze_pr_for_copilot_task(self, pr_details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a PR to determine what task Copilot should perform.
        
        Returns:
            Dict with 'should_invoke', 'task_type', 'priority', and 'reason'
        """
        pr_number = pr_details['number']
        title = pr_details['title']
        body = pr_details.get('body', '')
        is_draft = pr_details['isDraft']
        files = pr_details.get('files', [])
        
        analysis = {
            'should_invoke': False,
            'task_type': None,
            'priority': 'normal',
            'reason': []
        }
        
        # Check if it's an auto-fix PR
        if 'auto-fix' in title.lower():
            analysis['should_invoke'] = True
            analysis['task_type'] = 'implement_fix'
            analysis['priority'] = 'high'
            analysis['reason'].append("Auto-generated fix PR")
        
        # Check for workflow fixes
        if 'workflow' in title.lower() or any('workflow' in f.get('path', '') for f in files):
            analysis['should_invoke'] = True
            analysis['task_type'] = 'fix_workflow'
            analysis['priority'] = 'high'
            analysis['reason'].append("Workflow fix needed")
        
        # Check for permission errors
        if 'permission' in title.lower() or 'permission' in body.lower():
            analysis['should_invoke'] = True
            analysis['task_type'] = 'fix_permissions'
            analysis['priority'] = 'high'
            analysis['reason'].append("Permission error fix")
        
        # Check if it's a draft (general implementation)
        if is_draft and not analysis['should_invoke']:
            analysis['should_invoke'] = True
            analysis['task_type'] = 'implement_draft'
            analysis['priority'] = 'normal'
            analysis['reason'].append("Draft PR needing implementation")
        
        # Check for specific error types
        if 'unknown' in title.lower() or 'error' in title.lower():
            analysis['should_invoke'] = True
            analysis['task_type'] = 'debug_error'
            analysis['priority'] = 'high'
            analysis['reason'].append("Error investigation needed")
        
        return analysis
    
    def create_copilot_task_comment(self, pr_details: Dict[str, Any], analysis: Dict[str, Any]) -> str:
        """
        Create an appropriate comment to invoke Copilot Coding Agent.
        
        According to GitHub docs, we can use:
        - @copilot - General invocation
        - Specific instructions for the task
        """
        pr_number = pr_details['number']
        title = pr_details['title']
        task_type = analysis['task_type']
        priority = analysis['priority']
        reason = ', '.join(analysis['reason'])
        
        # Base template
        comment = f"@copilot "
        
        # Add task-specific instructions based on the Copilot Coding Agent capabilities
        if task_type == 'implement_fix':
            comment += f"""Please implement the auto-fix described in this PR.

**Context**: This PR was automatically created by the auto-healing workflow to fix a failed GitHub Actions workflow.

**Task**: 
1. Analyze the failure described in the PR description
2. Review the proposed fix
3. Implement the fix with minimal changes
4. Ensure the fix follows repository patterns and best practices
5. Run any relevant tests

**Priority**: {priority.upper()}
**Reason**: {reason}

Please proceed with implementing this fix."""

        elif task_type == 'fix_workflow':
            comment += f"""Please fix the workflow issue described in this PR.

**Context**: This PR addresses a GitHub Actions workflow failure.

**Task**:
1. Review the workflow file and error logs
2. Identify the root cause of the failure
3. Implement the fix following GitHub Actions best practices
4. Ensure the fix doesn't break existing functionality
5. Test the workflow configuration

**Priority**: {priority.upper()}
**Reason**: {reason}

Please implement the necessary workflow fixes."""

        elif task_type == 'fix_permissions':
            comment += f"""Please resolve the permission issues in this PR.

**Context**: This PR was created to fix permission errors in workflows or code.

**Task**:
1. Identify the permission errors
2. Review required permissions for the failing operations
3. Update permissions configuration appropriately
4. Ensure security best practices are maintained
5. Document any permission changes

**Priority**: {priority.upper()}
**Reason**: {reason}

Please fix the permission issues."""

        elif task_type == 'debug_error':
            comment += f"""Please investigate and fix the error described in this PR.

**Context**: This PR addresses an unknown or unspecified error.

**Task**:
1. Review error logs and stack traces
2. Identify the root cause
3. Implement a robust fix
4. Add error handling if appropriate
5. Update any relevant documentation

**Priority**: {priority.upper()}
**Reason**: {reason}

Please debug and fix this error."""

        elif task_type == 'implement_draft':
            comment += f"""Please help implement the changes described in this draft PR.

**Context**: This is a draft PR that needs implementation.

**Task**:
1. Review the PR description and requirements
2. Understand the intended changes
3. Implement the solution following repository patterns
4. Add or update tests as needed
5. Update documentation if directly related

**Priority**: {priority.upper()}
**Reason**: {reason}

Please implement the proposed changes."""

        else:
            # Generic task
            comment += f"""Please review and work on this pull request.

**Task**: Review the PR and implement any necessary changes.
**Priority**: {priority.upper()}
**Reason**: {reason}

Please proceed with the implementation."""
        
        return comment
    
    def invoke_copilot_on_pr(self, pr_number: int) -> bool:
        """
        Invoke GitHub Copilot Coding Agent on a specific PR.
        
        Returns:
            True if successful, False otherwise
        """
        print(f"\n{'='*80}")
        print(f"📋 Analyzing PR #{pr_number}")
        print(f"{'='*80}")
        
        # Get PR details
        pr_details = self.get_pr_details(pr_number)
        if not pr_details:
            return False
        
        print(f"📄 Title: {pr_details['title']}")
        print(f"📊 Draft: {pr_details['isDraft']}")
        print(f"👤 Author: {pr_details['author']['login']}")
        
        # Check if Copilot already invoked
        if self.check_copilot_already_invoked(pr_details):
            print(f"✅ Copilot already invoked on PR #{pr_number}")
            return True
        
        # Analyze what task Copilot should perform
        analysis = self.analyze_pr_for_copilot_task(pr_details)
        
        if not analysis['should_invoke']:
            print(f"⏭️  No Copilot invocation needed for PR #{pr_number}")
            return True
        
        print(f"🎯 Task: {analysis['task_type']}")
        print(f"⚡ Priority: {analysis['priority']}")
        print(f"📝 Reason: {', '.join(analysis['reason'])}")
        
        # Create the Copilot task comment
        comment = self.create_copilot_task_comment(pr_details, analysis)
        
        if self.dry_run:
            print(f"\n{'─'*80}")
            print(f"🔍 DRY RUN - Would post comment:")
            print(f"{'─'*80}")
            print(comment)
            print(f"{'─'*80}\n")
            return True
        
        # Post the comment to invoke Copilot
        result = self.run_command([
            'gh', 'pr', 'comment', str(pr_number),
            '--body', comment
        ])
        
        if result['success']:
            print(f"✅ Successfully invoked Copilot Coding Agent on PR #{pr_number}")
            return True
        else:
            print(f"❌ Failed to invoke Copilot: {result.get('error')}")
            return False
    
    def invoke_copilot_on_all_open_prs(self, limit: int = 100) -> Dict[str, int]:
        """
        Invoke Copilot on all open draft PRs.
        
        Returns:
            Statistics dictionary
        """
        print("🔍 Fetching open pull requests...")
        
        result = self.run_command([
            'gh', 'pr', 'list',
            '--state', 'open',
            '--limit', str(limit),
            '--json', 'number,title,isDraft,author'
        ])
        
        if not result['success']:
            print(f"❌ Failed to get PRs: {result.get('error')}")
            return {'total': 0, 'processed': 0, 'succeeded': 0, 'failed': 0, 'skipped': 0}
        
        try:
            prs = json.loads(result['stdout'])
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse PR list: {e}")
            return {'total': 0, 'processed': 0, 'succeeded': 0, 'failed': 0, 'skipped': 0}
        
        stats = {
            'total': len(prs),
            'processed': 0,
            'succeeded': 0,
            'failed': 0,
            'skipped': 0
        }
        
        print(f"📊 Found {stats['total']} open PRs\n")
        
        for pr in prs:
            pr_number = pr['number']
            stats['processed'] += 1
            
            if self.invoke_copilot_on_pr(pr_number):
                stats['succeeded'] += 1
            else:
                stats['failed'] += 1
        
        return stats
    
    def print_summary(self, stats: Dict[str, int]):
        """Print summary statistics."""
        print(f"\n{'='*80}")
        print(f"📊 Summary")
        print(f"{'='*80}")
        print(f"Total PRs:           {stats['total']}")
        print(f"Processed:           {stats['processed']}")
        print(f"Successfully invoked: {stats['succeeded']}")
        print(f"Failed:              {stats['failed']}")
        print(f"Skipped:             {stats['skipped']}")
        print(f"{'='*80}\n")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Invoke GitHub Copilot Coding Agent on Pull Requests'
    )
    parser.add_argument(
        '--pr',
        type=int,
        help='Specific PR number to process'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without actually doing it'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=100,
        help='Maximum number of PRs to process (default: 100)'
    )
    
    args = parser.parse_args()
    
    invoker = CopilotCodingAgentInvoker(dry_run=args.dry_run)
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - No actual changes will be made\n")
    
    if args.pr:
        # Process specific PR
        success = invoker.invoke_copilot_on_pr(args.pr)
        sys.exit(0 if success else 1)
    else:
        # Process all open PRs
        stats = invoker.invoke_copilot_on_all_open_prs(limit=args.limit)
        invoker.print_summary(stats)
        sys.exit(0 if stats['failed'] == 0 else 1)


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
