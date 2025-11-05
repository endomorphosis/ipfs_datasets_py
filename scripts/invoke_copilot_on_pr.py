#!/usr/bin/env python3
"""
Invoke GitHub Copilot on Pull Request using GitHub CLI

This script properly invokes GitHub Copilot on a PR by posting a comment
that triggers the Copilot coding agent, instead of just mentioning @copilot.

The script uses GitHub CLI to:
1. Post a properly formatted comment that triggers Copilot
2. Include specific instructions for what Copilot should do
3. Optionally wait for Copilot to respond

Usage:
    # Invoke Copilot with default fix instructions
    python scripts/invoke_copilot_on_pr.py --pr 123

    # Invoke with custom instructions
    python scripts/invoke_copilot_on_pr.py --pr 123 --instruction "Fix the linting errors"

    # Dry run (show what would be done)
    python scripts/invoke_copilot_on_pr.py --pr 123 --dry-run

Requirements:
    - GitHub CLI (gh) installed and authenticated
    - GITHUB_TOKEN or GH_TOKEN environment variable set
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional, Any

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CopilotPRInvoker:
    """Invoke GitHub Copilot on Pull Requests using GitHub CLI."""
    
    def __init__(self, dry_run: bool = False):
        """
        Initialize the invoker.
        
        Args:
            dry_run: If True, show what would be done without making changes
        """
        self.dry_run = dry_run
        self._verify_gh_cli()
    
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
            logger.error("❌ GitHub CLI not found. Please install it from https://cli.github.com/")
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
    
    def get_pr_info(self, pr_number: int, repo: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get PR information.
        
        Args:
            pr_number: Pull request number
            repo: Repository in format owner/repo (optional, uses current repo if not specified)
        
        Returns:
            Dictionary with PR information or None if failed
        """
        cmd = ['gh', 'pr', 'view', str(pr_number), '--json', 'number,title,body,isDraft,state,url']
        if repo:
            cmd.extend(['--repo', repo])
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to get PR info: {e.stderr}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse PR info: {e}")
            return None
    
    def invoke_copilot(
        self,
        pr_number: int,
        instruction: Optional[str] = None,
        repo: Optional[str] = None,
        use_slash_command: bool = True,
        max_retries: int = 3
    ) -> bool:
        """
        Invoke GitHub Copilot on a PR using gh CLI.
        
        Args:
            pr_number: Pull request number
            instruction: Custom instruction for Copilot (optional)
            repo: Repository in format owner/repo (optional)
            use_slash_command: Use /fix slash command format (recommended)
            max_retries: Maximum number of retry attempts (default: 3)
        
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"{'[DRY RUN] ' if self.dry_run else ''}Invoking Copilot on PR #{pr_number}...")
        
        # Get PR info first
        pr_info = self.get_pr_info(pr_number, repo)
        if not pr_info:
            logger.error(f"❌ Could not retrieve PR #{pr_number} information")
            return False
        
        logger.info(f"  PR Title: {pr_info['title']}")
        logger.info(f"  PR State: {pr_info['state']} {'(Draft)' if pr_info.get('isDraft') else ''}")
        logger.info(f"  PR URL: {pr_info['url']}")
        
        # Build the comment body that triggers Copilot
        if use_slash_command:
            # Use the /fix slash command which is the preferred way to invoke Copilot
            if instruction:
                comment_body = f"@github-copilot /fix\n\n{instruction}"
            else:
                # Default instruction for auto-fix scenarios
                comment_body = """@github-copilot /fix

Please analyze this PR and implement the necessary fixes based on:
1. The PR description and linked issue
2. Any workflow failure logs mentioned
3. Code review comments
4. Test failures

Focus on making minimal, surgical changes that directly address the problem."""
        else:
            # Alternative: Direct mention format
            if instruction:
                comment_body = f"@github-copilot {instruction}"
            else:
                comment_body = "@github-copilot Please implement the fixes described in this PR."
        
        if self.dry_run:
            logger.info(f"\n[DRY RUN] Would post comment:\n{'-'*80}\n{comment_body}\n{'-'*80}\n")
            return True
        
        # Post the comment using gh CLI with retry logic
        cmd = ['gh', 'pr', 'comment', str(pr_number), '--body', comment_body]
        if repo:
            cmd.extend(['--repo', repo])
        
        # Retry logic with exponential backoff
        for attempt in range(1, max_retries + 1):
            try:
                result = subprocess.run(
                    cmd, 
                    capture_output=True, 
                    text=True, 
                    check=True,
                    timeout=60
                )
                logger.info(f"✅ Successfully invoked Copilot on PR #{pr_number}")
                logger.info(f"  Comment URL: {result.stdout.strip()}")
                return True
            except subprocess.TimeoutExpired:
                logger.warning(f"⚠️  Attempt {attempt}/{max_retries}: Command timed out")
                if attempt < max_retries:
                    wait_time = 2 ** attempt  # Exponential backoff: 2, 4, 8 seconds
                    logger.info(f"  Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"❌ Failed after {max_retries} attempts: Command timed out")
                    return False
            except subprocess.CalledProcessError as e:
                error_msg = e.stderr.strip() if e.stderr else str(e)
                logger.warning(f"⚠️  Attempt {attempt}/{max_retries}: {error_msg}")
                
                # Check if error is retryable
                retryable_errors = ['timeout', 'network', 'connection', 'temporary']
                is_retryable = any(err in error_msg.lower() for err in retryable_errors)
                
                if attempt < max_retries and is_retryable:
                    wait_time = 2 ** attempt
                    logger.info(f"  Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"❌ Failed to post comment: {error_msg}")
                    return False
            except Exception as e:
                logger.error(f"❌ Unexpected error on attempt {attempt}/{max_retries}: {e}")
                if attempt >= max_retries:
                    return False
                time.sleep(2 ** attempt)
        
        return False
    
    def invoke_copilot_batch(
        self,
        pr_numbers: List[int],
        instruction: Optional[str] = None,
        repo: Optional[str] = None
    ) -> Dict[str, int]:
        """
        Invoke Copilot on multiple PRs.
        
        Args:
            pr_numbers: List of PR numbers
            instruction: Custom instruction for Copilot
            repo: Repository in format owner/repo
        
        Returns:
            Dictionary with statistics
        """
        stats = {
            'total': len(pr_numbers),
            'succeeded': 0,
            'failed': 0
        }
        
        for pr_number in pr_numbers:
            logger.info(f"\n{'='*80}")
            if self.invoke_copilot(pr_number, instruction, repo):
                stats['succeeded'] += 1
            else:
                stats['failed'] += 1
            logger.info(f"{'='*80}\n")
        
        return stats
    
    def find_prs_needing_copilot(
        self,
        repo: Optional[str] = None,
        label: Optional[str] = "copilot-ready"
    ) -> List[int]:
        """
        Find PRs that need Copilot invocation.
        
        Args:
            repo: Repository in format owner/repo
            label: Label to filter PRs (default: copilot-ready)
        
        Returns:
            List of PR numbers
        """
        cmd = ['gh', 'pr', 'list', '--state', 'open', '--json', 'number,labels']
        if repo:
            cmd.extend(['--repo', repo])
        if label:
            cmd.extend(['--label', label])
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            prs = json.loads(result.stdout)
            pr_numbers = [pr['number'] for pr in prs]
            logger.info(f"Found {len(pr_numbers)} PRs needing Copilot: {pr_numbers}")
            return pr_numbers
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to list PRs: {e.stderr}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse PR list: {e}")
            return []


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Invoke GitHub Copilot on Pull Requests using GitHub CLI'
    )
    parser.add_argument(
        '--pr',
        type=int,
        help='Pull request number to invoke Copilot on'
    )
    parser.add_argument(
        '--repo',
        type=str,
        help='Repository in format owner/repo (optional, uses current repo if not specified)'
    )
    parser.add_argument(
        '--instruction',
        type=str,
        help='Custom instruction for Copilot (optional)'
    )
    parser.add_argument(
        '--find-all',
        action='store_true',
        help='Find and invoke Copilot on all PRs with copilot-ready label'
    )
    parser.add_argument(
        '--label',
        type=str,
        default='copilot-ready',
        help='Label to filter PRs when using --find-all (default: copilot-ready)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    parser.add_argument(
        '--no-slash-command',
        action='store_true',
        help='Use direct mention format instead of /fix slash command'
    )
    
    args = parser.parse_args()
    
    if not args.pr and not args.find_all:
        parser.print_help()
        sys.exit(1)
    
    invoker = CopilotPRInvoker(dry_run=args.dry_run)
    
    if args.dry_run:
        logger.info("🔍 DRY RUN MODE - No changes will be made\n")
    
    if args.find_all:
        # Find all PRs needing Copilot
        pr_numbers = invoker.find_prs_needing_copilot(repo=args.repo, label=args.label)
        if not pr_numbers:
            logger.info("No PRs found needing Copilot")
            return
        
        # Invoke on all found PRs
        stats = invoker.invoke_copilot_batch(pr_numbers, args.instruction, args.repo)
        logger.info(f"\n📊 Summary: {stats['succeeded']}/{stats['total']} PRs processed successfully")
        sys.exit(0 if stats['failed'] == 0 else 1)
    else:
        # Invoke on specific PR
        success = invoker.invoke_copilot(
            args.pr,
            args.instruction,
            args.repo,
            use_slash_command=not args.no_slash_command
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
