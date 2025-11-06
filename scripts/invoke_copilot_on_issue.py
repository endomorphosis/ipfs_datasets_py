#!/usr/bin/env python3
"""
Invoke GitHub Copilot Coding Agent on GitHub Issue

This script invokes the GitHub Copilot coding agent to work on a GitHub issue
using the CORRECT method: draft PR + @copilot trigger comment.

See COPILOT_INVOCATION_GUIDE.md for full documentation.

Usage:
    # Invoke Copilot on an issue
    python scripts/invoke_copilot_on_issue.py --issue 123

    # With custom task description
    python scripts/invoke_copilot_on_issue.py --issue 123 \\
        --task "Implement the feature described in the issue"

    # Dry run
    python scripts/invoke_copilot_on_issue.py --issue 123 --dry-run

Requirements:
    - GitHub CLI (gh) installed and authenticated
    - GITHUB_TOKEN or GH_TOKEN environment variable set
    - Access to repository with Copilot enabled
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict, Optional, Any

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CopilotIssueInvoker:
    """Invoke GitHub Copilot Coding Agent on issues using the PROPER method."""
    
    def __init__(self, dry_run: bool = False, repo: Optional[str] = None):
        """
        Initialize the Copilot issue invoker.
        
        Args:
            dry_run: If True, only show what would be done without making changes
            repo: Repository in owner/name format. If None, uses current repository.
        """
        self.dry_run = dry_run
        self.repo = repo or os.environ.get('GITHUB_REPOSITORY')
        
        if not self.repo:
            # Try to get from gh CLI
            result = self.run_command(['gh', 'repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner'])
            if result['success']:
                self.repo = result['stdout'].strip()
        
        self._verify_environment()
    
    def _verify_environment(self):
        """Verify required tools and authentication."""
        # Check gh CLI
        result = self.run_command(['gh', '--version'], timeout=10)
        if not result['success']:
            logger.error("❌ GitHub CLI (gh) not found. Please install it from https://cli.github.com/")
            sys.exit(1)
        
        logger.info(f"✅ GitHub CLI: {result['stdout'].split()[0]}")
        
        # Check authentication
        result = self.run_command(['gh', 'auth', 'status'], timeout=10)
        if not result['success']:
            logger.error("❌ GitHub CLI not authenticated. Run: gh auth login")
            sys.exit(1)
        
        logger.info("✅ GitHub CLI authenticated")
        
        if self.repo:
            logger.info(f"✅ Repository: {self.repo}")
        else:
            logger.warning("⚠️  Repository not specified, using current directory")
        
        if self.dry_run:
            logger.info("🔍 DRY RUN MODE - No changes will be made")
        
        logger.info("=" * 80)
        logger.info("💡 PROPER COPILOT INVOCATION METHOD")
        logger.info("=" * 80)
        logger.info("✅ Creates draft PR for Copilot to work on (VS Code method)")
        logger.info("✅ Posts @copilot trigger comment to activate agent")
        logger.info("❌ NOT: gh agent-task (doesn't exist)")
        logger.info("📚 Based on verified working method - see COPILOT_INVOCATION_GUIDE.md")
        logger.info("=" * 80)
        logger.info("")
    
    def run_command(self, cmd: list, timeout: int = 60) -> Dict[str, Any]:
        """
        Run a shell command and return result.
        
        Args:
            cmd: Command and arguments as list
            timeout: Timeout in seconds
        
        Returns:
            Dict with 'success', 'stdout', 'stderr', 'returncode'
        """
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
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
                'error': f'Command timed out after {timeout}s',
                'stdout': '',
                'stderr': ''
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'stdout': '',
                'stderr': ''
            }
    
    def get_issue_info(self, issue_number: int) -> Optional[Dict[str, Any]]:
        """Get information about an issue."""
        cmd = [
            'gh', 'issue', 'view', str(issue_number),
            '--repo', self.repo,
            '--json', 'number,title,body,state,url,author,labels'
        ]
        
        result = self.run_command(cmd)
        if result['success']:
            try:
                return json.loads(result['stdout'])
            except json.JSONDecodeError as e:
                logger.error(f"❌ Failed to parse issue info: {e}")
                return None
        else:
            logger.error(f"❌ Failed to get issue info: {result.get('stderr', result.get('error'))}")
            return None
    
    def invoke_copilot(
        self,
        issue_number: int,
        task_description: Optional[str] = None
    ) -> bool:
        """
        Invoke Copilot to work on an issue.
        
        Creates a draft PR and posts @copilot trigger comment.
        
        Args:
            issue_number: GitHub issue number
            task_description: Custom task description for Copilot
        
        Returns:
            True if successful
        """
        logger.info(f"{'[DRY RUN] ' if self.dry_run else ''}Invoking Copilot on Issue #{issue_number}...")
        
        # Get issue info
        issue_info = self.get_issue_info(issue_number)
        if not issue_info:
            return False
        
        issue_title = issue_info['title']
        issue_body = issue_info.get('body', 'No description')
        issue_url = issue_info['url']
        issue_state = issue_info['state']
        author = issue_info['author']['login']
        
        logger.info(f"  Issue: #{issue_number} - {issue_title}")
        logger.info(f"  Author: {author}")
        logger.info(f"  State: {issue_state}")
        
        if issue_state != 'OPEN':
            logger.warning(f"⚠️  Issue is {issue_state}, not OPEN")
        
        # Build task description
        if not task_description:
            task_description = f"""# Implement Solution for Issue #{issue_number}

## Issue
- **Link**: {issue_url}
- **Title**: {issue_title}
- **Author**: @{author}

## Description
{issue_body}

## Task for Copilot
Please analyze Issue #{issue_number} and implement the solution:

1. Review the issue description and requirements
2. Understand the acceptance criteria
3. Implement the solution following repository patterns
4. Add tests as appropriate
5. Update documentation if relevant
6. Make surgical, minimal changes

## Context
- This is a Copilot coding agent task for an issue
- Related issue: #{issue_number}
- Invoked: {datetime.now().isoformat()}
"""
        
        # Create unique branch name
        timestamp = int(time.time())
        branch_prefix = f"copilot/issue-{issue_number}"
        draft_pr_title = f"🤖 Copilot: Implement Issue #{issue_number} - {issue_title[:60]}"
        
        if self.dry_run:
            logger.info(f"\\n[DRY RUN] Would create draft PR and trigger Copilot:")
            logger.info(f"  Branch prefix: {branch_prefix}")
            logger.info(f"  Title: {draft_pr_title}")
            logger.info(f"  Task:\\n{'-'*80}\\n{task_description}\\n{'-'*80}")
            logger.info(f"  Would post: @copilot /fix comment to trigger agent")
            logger.info("")
            logger.info("✅ [DRY RUN] Would successfully invoke Copilot")
            return True
        
        # Step 1: Create draft PR
        logger.info("  Step 1: Creating draft PR...")
        cmd = [
            'python3', 'scripts/invoke_copilot_via_draft_pr.py',
            '--title', draft_pr_title,
            '--description', task_description,
            '--repo', self.repo,
            '--base', 'main',
            '--branch-prefix', branch_prefix
        ]
        
        result = self.run_command(cmd, timeout=120)
        
        if not result['success']:
            logger.error(f"❌ Failed to create draft PR: {result.get('stderr', result.get('error'))}")
            return False
        
        logger.info(f"✅ Draft PR created successfully")
        
        # Step 2: Find the newly created PR
        time.sleep(2)  # Wait for PR to be fully created
        
        logger.info("  Step 2: Finding created draft PR...")
        list_cmd = [
            'gh', 'pr', 'list',
            '--repo', self.repo,
            '--state', 'open',
            '--json', 'number,title,createdAt',
            '--limit', '5'
        ]
        
        list_result = self.run_command(list_cmd)
        if list_result['success']:
            try:
                prs = json.loads(list_result['stdout'])
                draft_pr_number = None
                for pr in prs:
                    if f"Issue #{issue_number}" in pr['title']:
                        draft_pr_number = pr['number']
                        break
                
                if draft_pr_number:
                    logger.info(f"✅ Found draft PR #{draft_pr_number}")
                    
                    # Step 3: Post @copilot trigger comment
                    logger.info("  Step 3: Triggering Copilot agent with comment...")
                    trigger_comment = f"""@copilot /fix

{task_description}

Please implement the necessary changes to resolve this issue."""
                    
                    comment_cmd = [
                        'gh', 'pr', 'comment', str(draft_pr_number),
                        '--repo', self.repo,
                        '--body', trigger_comment
                    ]
                    
                    comment_result = self.run_command(comment_cmd, timeout=60)
                    
                    if comment_result['success']:
                        logger.info(f"✅ Successfully triggered Copilot on draft PR #{draft_pr_number}")
                        logger.info(f"   Copilot will analyze and implement the solution")
                        logger.info("")
                        logger.info(f"✅ Successfully invoked Copilot coding agent on Issue #{issue_number}")
                        logger.info(f"💡 Copilot will create an implementation PR automatically")
                        logger.info(f"📊 Monitor: gh pr list --author app/copilot-swe-agent")
                        logger.info(f"🔗 Draft PR: https://github.com/{self.repo}/pull/{draft_pr_number}")
                        return True
                    else:
                        logger.warning(f"⚠️  Draft PR created but failed to post trigger comment")
                        logger.warning(f"   You may need to manually comment '@copilot /fix' on PR #{draft_pr_number}")
                        return True
                else:
                    logger.warning(f"⚠️  Could not find the created draft PR")
                    logger.warning(f"   Check recent PRs manually: gh pr list")
                    return True
                    
            except json.JSONDecodeError as e:
                logger.error(f"❌ Failed to parse PR list: {e}")
                return True
        else:
            logger.warning(f"⚠️  Could not list PRs to find draft PR number")
            return True


def main():
    parser = argparse.ArgumentParser(
        description='Invoke GitHub Copilot Coding Agent on an issue',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Basic invocation
    python scripts/invoke_copilot_on_issue.py --issue 123
    
    # With custom task
    python scripts/invoke_copilot_on_issue.py --issue 123 \\
        --task "Implement the feature with proper tests"
    
    # Dry run
    python scripts/invoke_copilot_on_issue.py --issue 123 --dry-run
    
    # Specific repository
    python scripts/invoke_copilot_on_issue.py --issue 123 \\
        --repo owner/repo

For full documentation, see COPILOT_INVOCATION_GUIDE.md
        """
    )
    
    parser.add_argument(
        '--issue',
        type=int,
        required=True,
        help='GitHub issue number to work on'
    )
    
    parser.add_argument(
        '--task',
        type=str,
        help='Custom task description for Copilot (optional)'
    )
    
    parser.add_argument(
        '--repo',
        type=str,
        help='Repository in owner/name format (optional, uses current repo if not specified)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    
    args = parser.parse_args()
    
    try:
        invoker = CopilotIssueInvoker(
            dry_run=args.dry_run,
            repo=args.repo
        )
        
        success = invoker.invoke_copilot(
            issue_number=args.issue,
            task_description=args.task
        )
        
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        logger.info("\\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
