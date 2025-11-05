#!/usr/bin/env python3
"""
Invoke GitHub Copilot using gh agent-task create (Official Method)

This script uses the OFFICIAL GitHub Copilot Coding Agent method as documented at:
- https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent
- https://docs.github.com/en/copilot/concepts/agents/coding-agent/agent-management

This is the proper way to invoke GitHub Copilot, NOT:
❌ Commenting @copilot on PRs (unsupported)
❌ Creating draft PRs and mentioning @copilot (unsupported)

✅ Using gh agent-task create - The official GitHub CLI command
✅ Using CopilotCLI Python wrapper - Repository's wrapper utility

Requirements:
    - GitHub CLI (gh) installed and authenticated
    - GITHUB_TOKEN or GH_TOKEN environment variable set
    - gh agent-task extension (part of gh-copilot extension)
    
Installation:
    gh extension install github/gh-copilot
    gh extension upgrade gh-copilot

Usage:
    # Create agent task for a PR
    python scripts/invoke_copilot_agent_task.py --pr 123
    
    # Create with custom description
    python scripts/invoke_copilot_agent_task.py --pr 123 --description "Fix the failing tests"
    
    # Specify branch explicitly
    python scripts/invoke_copilot_agent_task.py --pr 123 --branch feature-xyz
    
    # Follow agent execution
    python scripts/invoke_copilot_agent_task.py --pr 123 --follow
    
    # Dry run
    python scripts/invoke_copilot_agent_task.py --pr 123 --dry-run
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Try to import the CopilotCLI utility
try:
    script_dir = Path(__file__).parent.parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    
    from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
    COPILOT_CLI_AVAILABLE = True
except ImportError:
    COPILOT_CLI_AVAILABLE = False
    logger.warning("⚠️  CopilotCLI utility not available, using direct gh commands")


class CopilotAgentTaskInvoker:
    """
    Invoke GitHub Copilot Coding Agent using gh agent-task create.
    
    This is the official method per GitHub's documentation.
    """
    
    def __init__(self, dry_run: bool = False, repo: Optional[str] = None):
        """
        Initialize the invoker.
        
        Args:
            dry_run: If True, show what would be done without making changes
            repo: Repository in format owner/repo (optional, uses current repo if not specified)
        """
        self.dry_run = dry_run
        self.repo = repo
        self._verify_gh_cli()
        self._verify_copilot_extension()
    
    def _verify_gh_cli(self):
        """Verify GitHub CLI is installed and authenticated."""
        try:
            result = subprocess.run(
                ['gh', '--version'],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"✅ GitHub CLI available: {result.stdout.strip().split()[0]}")
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error("❌ GitHub CLI not found. Install from https://cli.github.com/")
            sys.exit(1)
        
        # Verify authentication
        try:
            result = subprocess.run(
                ['gh', 'auth', 'status'],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                logger.error("❌ GitHub CLI not authenticated. Run 'gh auth login'")
                sys.exit(1)
            logger.info("✅ GitHub CLI authenticated")
        except Exception as e:
            logger.warning(f"⚠️  Could not verify gh auth status: {e}")
    
    def _verify_copilot_extension(self):
        """Verify gh-copilot extension is installed."""
        try:
            result = subprocess.run(
                ['gh', 'extension', 'list'],
                capture_output=True,
                text=True
            )
            if 'gh-copilot' not in result.stdout and 'github/gh-copilot' not in result.stdout:
                logger.warning("⚠️  gh-copilot extension not found")
                logger.info("💡 Install with: gh extension install github/gh-copilot")
                logger.info("📚 See: https://docs.github.com/en/copilot/using-github-copilot/using-github-copilot-in-the-cli")
                return False
            logger.info("✅ gh-copilot extension available")
            return True
        except Exception as e:
            logger.warning(f"⚠️  Could not verify gh-copilot extension: {e}")
            return False
    
    def run_command(self, cmd: List[str], timeout: int = 120) -> Dict[str, Any]:
        """Run a command and return the result."""
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
                'error': f'Command timed out after {timeout} seconds'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_pr_info(self, pr_number: int) -> Optional[Dict[str, Any]]:
        """Get PR information using gh CLI."""
        cmd = ['gh', 'pr', 'view', str(pr_number), '--json', 'number,title,body,isDraft,state,url,headRefName,baseRefName']
        if self.repo:
            cmd.extend(['--repo', self.repo])
        
        result = self.run_command(cmd, timeout=30)
        
        if not result['success']:
            logger.error(f"❌ Failed to get PR info: {result.get('error', result.get('stderr'))}")
            return None
        
        try:
            return json.loads(result['stdout'])
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse PR info: {e}")
            return None
    
    def check_existing_agent_task(self, pr_number: int) -> bool:
        """Check if an agent task already exists for this PR."""
        cmd = ['gh', 'agent-task', 'list', '--limit', '50']
        if self.repo:
            cmd.extend(['--repo', self.repo])
        
        result = self.run_command(cmd, timeout=30)
        
        if result['success']:
            # Check if there's a task for this PR
            if f"#{pr_number}" in result['stdout'] or f"pull/{pr_number}" in result['stdout']:
                return True
        
        return False
    
    def create_agent_task(
        self,
        pr_number: int,
        task_description: Optional[str] = None,
        follow: bool = False
    ) -> bool:
        """
        Create a GitHub Copilot agent task for a PR using gh agent-task create.
        
        This is the OFFICIAL method per GitHub documentation.
        
        Args:
            pr_number: Pull request number
            task_description: Custom task description (optional)
            follow: Follow agent execution (default: False)
        
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"{'[DRY RUN] ' if self.dry_run else ''}Creating agent task for PR #{pr_number}...")
        
        # Get PR info
        pr_info = self.get_pr_info(pr_number)
        if not pr_info:
            logger.error(f"❌ Could not retrieve PR #{pr_number} information")
            return False
        
        pr_title = pr_info['title']
        pr_body = pr_info.get('body', '')
        pr_branch = pr_info.get('headRefName', '')
        base_branch = pr_info.get('baseRefName', 'main')
        pr_url = pr_info['url']
        is_draft = pr_info.get('isDraft', False)
        
        logger.info(f"  PR Title: {pr_title}")
        logger.info(f"  Branch: {pr_branch} <- {base_branch}")
        logger.info(f"  Draft: {is_draft}")
        logger.info(f"  URL: {pr_url}")
        
        # Check if agent task already exists
        if self.check_existing_agent_task(pr_number):
            logger.warning(f"⚠️  Agent task already exists for PR #{pr_number}")
            logger.info("💡 Use --force to create another task")
            return True  # Not an error, task exists
        
        # Build task description
        if not task_description:
            # Generate comprehensive task description
            task_description = f"""Complete work on PR #{pr_number}: {pr_title}

**PR URL**: {pr_url}
**Branch**: {pr_branch}
**Base**: {base_branch}

**PR Description**:
{pr_body[:500] if pr_body else 'No description provided'}

**Task Instructions**:
1. Review the PR description and any linked issues
2. Analyze the current code changes
3. Identify what work remains to be done
4. Implement the required changes following repository patterns
5. Ensure all tests pass
6. Make minimal, surgical changes
7. Update documentation only if directly related to changes

**Focus Areas**:
- Fix any issues mentioned in the PR description
- Resolve failing tests or CI checks
- Follow existing code style and patterns
- Ensure backward compatibility
"""
        
        if self.dry_run:
            logger.info(f"\n[DRY RUN] Would create agent task:\n{'-'*80}")
            logger.info(f"Task: {task_description[:300]}...")
            logger.info(f"Branch: {pr_branch}")
            logger.info(f"Base: {base_branch}")
            logger.info(f"{'-'*80}\n")
            return True
        
        # Method 1: Try using CopilotCLI utility wrapper (preferred)
        if COPILOT_CLI_AVAILABLE:
            try:
                logger.info("  🔧 Attempting to use CopilotCLI utility wrapper...")
                copilot = CopilotCLI()
                result = copilot.create_agent_task(
                    task_description=task_description,
                    base_branch=pr_branch,  # Use PR branch as the working branch
                    follow=follow,
                    repo=self.repo
                )
                
                if result.get('success'):
                    logger.info(f"  ✅ Created agent task using CopilotCLI")
                    if result.get('stdout'):
                        logger.info(f"  Output: {result['stdout']}")
                    return True
                else:
                    logger.warning(f"  ⚠️  CopilotCLI failed: {result.get('error', 'Unknown error')}")
                    logger.info("  💡 Falling back to direct gh command...")
            except Exception as e:
                logger.warning(f"  ⚠️  CopilotCLI exception: {e}")
                logger.info("  💡 Falling back to direct gh command...")
        
        # Method 2: Direct gh agent-task create command
        logger.info("  🔧 Using gh agent-task create directly...")
        cmd = ['gh', 'agent-task', 'create', task_description, '--base', pr_branch]
        
        if follow:
            cmd.append('--follow')
        
        if self.repo:
            cmd.extend(['--repo', self.repo])
        
        result = self.run_command(cmd, timeout=120)
        
        if result['success']:
            logger.info(f"  ✅ Created agent task using gh agent-task create")
            if result['stdout']:
                logger.info(f"  Output: {result['stdout']}")
            return True
        else:
            error_msg = result.get('error', result.get('stderr', 'Unknown error'))
            
            # Provide helpful error messages
            if 'unknown command' in error_msg.lower() or 'not found' in error_msg.lower():
                logger.error(f"  ❌ gh agent-task command not available")
                logger.info("  💡 Install gh-copilot extension:")
                logger.info("     gh extension install github/gh-copilot")
                logger.info("     gh extension upgrade gh-copilot")
                logger.info("  📚 Documentation:")
                logger.info("     https://docs.github.com/en/copilot/concepts/agents/coding-agent/")
            else:
                logger.error(f"  ❌ Failed to create agent task: {error_msg}")
            
            return False
    
    def list_agent_tasks(self, limit: int = 30) -> bool:
        """List recent agent tasks."""
        cmd = ['gh', 'agent-task', 'list', '--limit', str(limit)]
        if self.repo:
            cmd.extend(['--repo', self.repo])
        
        result = self.run_command(cmd, timeout=30)
        
        if result['success']:
            logger.info(f"📊 Recent Agent Tasks:\n{result['stdout']}")
            return True
        else:
            logger.error(f"❌ Failed to list agent tasks: {result.get('error', result.get('stderr'))}")
            return False
    
    def view_agent_task(self, task_id: str) -> bool:
        """View details of a specific agent task."""
        cmd = ['gh', 'agent-task', 'view', task_id]
        if self.repo:
            cmd.extend(['--repo', self.repo])
        
        result = self.run_command(cmd, timeout=30)
        
        if result['success']:
            logger.info(f"📄 Agent Task Details:\n{result['stdout']}")
            return True
        else:
            logger.error(f"❌ Failed to view agent task: {result.get('error', result.get('stderr'))}")
            return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Invoke GitHub Copilot using gh agent-task create (Official Method)',
        epilog='''
Examples:
  # Create agent task for a PR
  %(prog)s --pr 123
  
  # Create with custom description
  %(prog)s --pr 123 --description "Fix the failing tests"
  
  # Follow agent execution
  %(prog)s --pr 123 --follow
  
  # List recent agent tasks
  %(prog)s --list
  
  # View specific agent task
  %(prog)s --view <task-id>

For more information, see:
  https://docs.github.com/en/copilot/concepts/agents/coding-agent/
        ''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--pr',
        type=int,
        help='Pull request number to create agent task for'
    )
    parser.add_argument(
        '--description',
        type=str,
        help='Custom task description (optional, auto-generated if not provided)'
    )
    parser.add_argument(
        '--follow',
        action='store_true',
        help='Follow agent execution after creating task'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List recent agent tasks'
    )
    parser.add_argument(
        '--view',
        type=str,
        metavar='TASK_ID',
        help='View specific agent task by ID'
    )
    parser.add_argument(
        '--repo',
        type=str,
        help='Repository in format owner/repo (optional, uses current repo if not specified)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if not any([args.pr, args.list, args.view]):
        parser.print_help()
        sys.exit(1)
    
    invoker = CopilotAgentTaskInvoker(dry_run=args.dry_run, repo=args.repo)
    
    if args.dry_run:
        logger.info("🔍 DRY RUN MODE - No changes will be made\n")
    
    # Print usage info
    logger.info("=" * 80)
    logger.info("🤖 GitHub Copilot Agent Task Invoker (Official Method)")
    logger.info("=" * 80)
    logger.info("✅ Using: gh agent-task create (official GitHub CLI command)")
    logger.info("✅ Using: CopilotCLI Python wrapper (repository utility)")
    logger.info("📚 Docs: https://docs.github.com/en/copilot/concepts/agents/coding-agent/")
    logger.info("")
    logger.info("❌ NOT using:")
    logger.info("   ❌ @copilot mentions in PR comments (unsupported)")
    logger.info("   ❌ Draft PR creation with @copilot (unsupported)")
    logger.info("=" * 80)
    logger.info("")
    
    success = False
    
    if args.list:
        success = invoker.list_agent_tasks()
    elif args.view:
        success = invoker.view_agent_task(args.view)
    elif args.pr:
        success = invoker.create_agent_task(
            pr_number=args.pr,
            task_description=args.description,
            follow=args.follow
        )
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
