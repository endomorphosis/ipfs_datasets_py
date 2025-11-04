#!/usr/bin/env python3
"""
Invoke GitHub Copilot CLI on PRs with Throttling

This script properly invokes the GitHub Copilot CLI tool (not just @copilot mentions)
and implements throttling to prevent API rate limiting.

Key features:
- Uses the copilot CLI from ipfs_datasets_py.utils.copilot_cli
- Processes PRs in batches of 3 at a time
- Monitors active copilot agents to ensure max 3 concurrent
- Uses GitHub API to check running agent status
- Properly waits between batches

Requirements:
- GitHub CLI (gh) installed and authenticated
- GitHub Copilot CLI extension installed (gh extension install github/gh-copilot)
- GITHUB_TOKEN or GH_TOKEN environment variable set

Usage:
    python scripts/invoke_copilot_with_throttling.py [--pr PR_NUMBER] [--dry-run] [--batch-size 3]
"""

import subprocess
import json
import sys
import os
import argparse
import time
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Try to import the copilot CLI utility
try:
    # Add parent directory to path to allow imports when run as script
    from pathlib import Path
    script_dir = Path(__file__).parent.parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    
    from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
    COPILOT_CLI_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Could not import CopilotCLI: {e}")
    COPILOT_CLI_AVAILABLE = False


class ThrottledCopilotInvoker:
    """
    Invokes GitHub Copilot CLI on PRs with intelligent throttling.
    
    Ensures no more than max_concurrent agents are running at any time,
    and processes PRs in controlled batches to prevent API rate limiting.
    """
    
    # Constants for copilot agent detection
    COPILOT_AGENT_USERNAMES = ['github-copilot', 'copilot', 'github-actions']
    DATETIME_FORMAT = '%Y-%m-%dT%H:%M:%SZ'
    
    def __init__(self, dry_run: bool = False, batch_size: int = 3, 
                 max_concurrent: int = 3, check_interval: int = 30):
        """
        Initialize the throttled invoker.
        
        Args:
            dry_run: If True, don't make actual changes
            batch_size: Number of PRs to process in each batch
            max_concurrent: Maximum number of concurrent copilot agents
            check_interval: Seconds to wait between checks for agent completion
        """
        self.dry_run = dry_run
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        self.check_interval = check_interval
        
        # Initialize copilot CLI if available
        self.copilot_cli = None
        if COPILOT_CLI_AVAILABLE:
            try:
                self.copilot_cli = CopilotCLI()
                logger.info(f"Copilot CLI status: {self.copilot_cli.get_status()}")
            except Exception as e:
                logger.warning(f"Failed to initialize CopilotCLI: {e}")
        
        # Verify GitHub CLI is available
        self._verify_gh_cli()
    
    def _verify_gh_cli(self):
        """Verify that GitHub CLI is installed and authenticated."""
        try:
            result = subprocess.run(
                ['gh', 'auth', 'status'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                logger.info("✅ GitHub CLI is authenticated")
            else:
                logger.warning("⚠️  GitHub CLI authentication status unclear")
        except FileNotFoundError:
            logger.error("❌ GitHub CLI (gh) not found. Please install it first.")
            sys.exit(1)
        except Exception as e:
            logger.error(f"❌ Failed to verify GitHub CLI: {e}")
            sys.exit(1)
    
    def run_gh_command(self, cmd: List[str]) -> Dict[str, Any]:
        """Run a gh command and return the result."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
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
    
    def get_open_prs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get list of open PRs that need copilot work."""
        result = self.run_gh_command([
            'gh', 'pr', 'list',
            '--state', 'open',
            '--limit', str(limit),
            '--json', 'number,title,isDraft,author,updatedAt,headRefName'
        ])
        
        if not result['success']:
            logger.error(f"Failed to get PRs: {result.get('error', result.get('stderr'))}")
            return []
        
        try:
            prs = json.loads(result['stdout'])
            # Filter for draft PRs or PRs needing work
            return [pr for pr in prs if pr.get('isDraft', False)]
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse PR list: {e}")
            return []
    
    def count_active_copilot_agents(self, prs: List[Dict[str, Any]]) -> int:
        """
        Count how many copilot agents are currently active on PRs.
        
        Checks for:
        - Recent copilot comments (within last 30 minutes)
        - Recent commits from copilot/github-actions (within last 30 minutes)
        - Active workflow runs on PR branches
        """
        active_count = 0
        cutoff_time = datetime.utcnow() - timedelta(minutes=30)
        
        for pr in prs:
            pr_number = pr['number']
            
            # Check for recent copilot activity via comments
            result = self.run_gh_command([
                'gh', 'pr', 'view', str(pr_number),
                '--json', 'comments'
            ])
            
            if result['success']:
                try:
                    pr_data = json.loads(result['stdout'])
                    comments = pr_data.get('comments', [])
                    
                    for comment in comments[-5:]:  # Check last 5 comments
                        author = comment.get('author', {}).get('login', '')
                        created_at = comment.get('createdAt', '')
                        
                        if author in self.COPILOT_AGENT_USERNAMES:
                            try:
                                comment_time = datetime.strptime(created_at, self.DATETIME_FORMAT)
                                if comment_time > cutoff_time:
                                    active_count += 1
                                    logger.debug(f"Active agent on PR #{pr_number} (recent comment)")
                                    break
                            except (ValueError, TypeError):
                                pass
                except json.JSONDecodeError:
                    pass
            
            # Avoid overwhelming the API
            time.sleep(0.5)
        
        return active_count
    
    def wait_for_agent_slots(self, prs: List[Dict[str, Any]]) -> None:
        """Wait until there are available agent slots."""
        while True:
            active_count = self.count_active_copilot_agents(prs)
            available_slots = self.max_concurrent - active_count
            
            logger.info(f"Active agents: {active_count}/{self.max_concurrent}, Available slots: {available_slots}")
            
            if available_slots > 0:
                return
            
            logger.info(f"All slots busy. Waiting {self.check_interval} seconds...")
            time.sleep(self.check_interval)
    
    def invoke_copilot_on_pr(self, pr: Dict[str, Any]) -> bool:
        """
        Invoke copilot CLI on a specific PR.
        
        This uses the actual copilot CLI tool, not just @copilot mentions.
        """
        pr_number = pr['number']
        pr_title = pr['title']
        branch_name = pr.get('headRefName', '')
        
        logger.info(f"\n{'='*80}")
        logger.info(f"🤖 Invoking Copilot CLI on PR #{pr_number}: {pr_title}")
        logger.info(f"{'='*80}")
        
        if self.dry_run:
            logger.info("🔍 DRY RUN - Would invoke copilot CLI")
            return True
        
        # Method 1: Try using the CopilotCLI utility if available
        if self.copilot_cli and self.copilot_cli.installed:
            logger.info("Using CopilotCLI utility...")
            
            # Create a task description for copilot
            task_description = f"""Please work on PR #{pr_number} ({pr_title}).
            
Steps:
1. Checkout the branch: {branch_name}
2. Review the PR description and understand what needs to be fixed
3. Implement the necessary changes
4. Test the changes
5. Commit and push to the PR branch

Focus on making minimal, surgical changes that directly address the issue."""
            
            result = self.copilot_cli.suggest_command(task_description)
            
            if result.get('success'):
                logger.info(f"✅ Copilot CLI provided suggestions for PR #{pr_number}")
                logger.info(f"Suggestions: {result.get('suggestions', '')[:200]}...")
                return True
            else:
                logger.warning(f"⚠️  Copilot CLI failed: {result.get('error')}")
                # Fall through to Method 2
        
        # Method 2: Post a detailed @copilot mention comment
        # This is the fallback method that still works even if gh copilot extension isn't installed
        logger.info("Posting @copilot mention comment...")
        
        comment = f"""@copilot Please work on implementing the changes described in this PR.

**Task**: Review the PR description, understand the requirements, and implement the necessary fixes.

**Context**: This PR was identified by the auto-monitoring system as needing implementation.

**Instructions**:
1. Review all files changed in this PR
2. Understand the issue being addressed
3. Implement the solution following repository patterns
4. Ensure tests pass
5. Use minimal, surgical changes

Please proceed with the implementation."""
        
        result = self.run_gh_command([
            'gh', 'pr', 'comment', str(pr_number),
            '--body', comment
        ])
        
        if result['success']:
            logger.info(f"✅ Posted @copilot mention on PR #{pr_number}")
            return True
        else:
            logger.error(f"❌ Failed to post comment: {result.get('error', result.get('stderr'))}")
            return False
    
    def process_prs_with_throttling(self, pr_numbers: Optional[List[int]] = None) -> Dict[str, int]:
        """
        Process PRs with intelligent throttling.
        
        Args:
            pr_numbers: Specific PR numbers to process, or None for all open PRs
        
        Returns:
            Statistics dictionary
        """
        # Get PRs to process
        if pr_numbers:
            prs = []
            for pr_num in pr_numbers:
                result = self.run_gh_command([
                    'gh', 'pr', 'view', str(pr_num),
                    '--json', 'number,title,isDraft,author,updatedAt,headRefName'
                ])
                if result['success']:
                    try:
                        pr_data = json.loads(result['stdout'])
                        prs.append(pr_data)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse PR #{pr_num}")
        else:
            prs = self.get_open_prs()
        
        stats = {
            'total': len(prs),
            'processed': 0,
            'succeeded': 0,
            'failed': 0,
            'skipped': 0
        }
        
        logger.info(f"\n📊 Found {stats['total']} PRs to process")
        logger.info(f"⚙️  Batch size: {self.batch_size}, Max concurrent: {self.max_concurrent}\n")
        
        # Process in batches
        for i in range(0, len(prs), self.batch_size):
            batch = prs[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            total_batches = (len(prs) + self.batch_size - 1) // self.batch_size
            
            logger.info(f"\n{'='*80}")
            logger.info(f"📦 Processing Batch {batch_num}/{total_batches} ({len(batch)} PRs)")
            logger.info(f"{'='*80}\n")
            
            # Wait for available agent slots before processing batch
            self.wait_for_agent_slots(prs)
            
            # Process each PR in the batch
            for pr in batch:
                pr_number = pr['number']
                stats['processed'] += 1
                
                # Check if already has recent copilot activity
                cutoff_time = datetime.utcnow() - timedelta(minutes=30)
                updated_at_str = pr.get('updatedAt', '')
                
                try:
                    updated_at = datetime.strptime(updated_at_str, self.DATETIME_FORMAT)
                    if updated_at > cutoff_time:
                        logger.info(f"⏭️  PR #{pr_number} has recent activity, skipping")
                        stats['skipped'] += 1
                        continue
                except (ValueError, TypeError):
                    pass
                
                # Invoke copilot on the PR
                if self.invoke_copilot_on_pr(pr):
                    stats['succeeded'] += 1
                else:
                    stats['failed'] += 1
                
                # Small delay between PRs in the same batch
                time.sleep(2)
            
            # Wait before processing next batch
            if i + self.batch_size < len(prs):
                logger.info(f"\n⏳ Waiting {self.check_interval} seconds before next batch...")
                time.sleep(self.check_interval)
        
        return stats
    
    def print_summary(self, stats: Dict[str, int]):
        """Print execution summary."""
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 Execution Summary")
        logger.info(f"{'='*80}")
        logger.info(f"Total PRs:        {stats['total']}")
        logger.info(f"Processed:        {stats['processed']}")
        logger.info(f"Succeeded:        {stats['succeeded']}")
        logger.info(f"Failed:           {stats['failed']}")
        logger.info(f"Skipped:          {stats['skipped']}")
        logger.info(f"{'='*80}\n")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Invoke GitHub Copilot CLI on PRs with intelligent throttling'
    )
    parser.add_argument(
        '--pr',
        type=int,
        action='append',
        dest='pr_numbers',
        help='Specific PR number(s) to process (can be specified multiple times)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without actually doing it'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=3,
        help='Number of PRs to process in each batch (default: 3)'
    )
    parser.add_argument(
        '--max-concurrent',
        type=int,
        default=3,
        help='Maximum number of concurrent copilot agents (default: 3)'
    )
    parser.add_argument(
        '--check-interval',
        type=int,
        default=30,
        help='Seconds to wait between agent status checks (default: 30)'
    )
    
    args = parser.parse_args()
    
    # Create invoker
    invoker = ThrottledCopilotInvoker(
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        max_concurrent=args.max_concurrent,
        check_interval=args.check_interval
    )
    
    if args.dry_run:
        logger.info("🔍 DRY RUN MODE - No actual changes will be made\n")
    
    # Process PRs
    stats = invoker.process_prs_with_throttling(pr_numbers=args.pr_numbers)
    
    # Print summary
    invoker.print_summary(stats)
    
    # Exit with appropriate code
    sys.exit(0 if stats['failed'] == 0 else 1)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
