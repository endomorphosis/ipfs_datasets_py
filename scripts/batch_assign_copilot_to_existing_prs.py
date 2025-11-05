#!/usr/bin/env python3
"""
Batch Assign Copilot to Existing PRs

This script assigns GitHub Copilot to multiple existing PRs using PR comments.
It's specifically designed for existing PRs, unlike gh agent-task create which
creates NEW PRs.

This script:
- Takes a list of PR numbers
- Posts @github-copilot comments on each PR
- Includes appropriate instructions based on PR status
- Handles rate limiting and batch processing

Usage:
    # Assign Copilot to specific PRs
    python scripts/batch_assign_copilot_to_existing_prs.py --prs 123,124,125
    
    # Dry run
    python scripts/batch_assign_copilot_to_existing_prs.py --prs 123,124 --dry-run
    
    # With custom instruction
    python scripts/batch_assign_copilot_to_existing_prs.py --prs 123 --instruction "Fix the failing tests"
"""

# Instruction templates for different PR types
INSTRUCTION_TEMPLATES = {
    'draft': """@github-copilot /fix

This draft PR needs implementation. Please:

1. Review the PR description and any linked issues
2. Understand the requirements and acceptance criteria
3. Implement the solution following repository patterns and coding standards
4. Add or update tests as appropriate
5. Ensure all tests pass
6. Make minimal, surgical changes focused on the requirements

Follow the existing code style and avoid modifying unrelated code.""",
    
    'incomplete': """@github-copilot /fix

Please analyze this PR and implement any necessary improvements based on:
1. The PR description and objectives
2. Code review feedback (if any)
3. Test failures (if any)
4. Best practices and code quality

Focus on making minimal, surgical changes that directly address the issues."""
}

import argparse
import json
import logging
import subprocess
import sys
import time
from typing import Dict, List, Optional, Any
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


class BatchCopilotAssigner:
    """Assign Copilot to multiple existing PRs using comments."""
    
    def __init__(self, dry_run: bool = False, batch_delay: int = 5):
        """
        Initialize the batch assigner.
        
        Args:
            dry_run: If True, show what would be done without making changes
            batch_delay: Seconds to wait between PR assignments (rate limiting)
        """
        self.dry_run = dry_run
        self.batch_delay = batch_delay
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
            repo: Repository in format owner/repo (optional)
        
        Returns:
            Dictionary with PR information or None if failed
        """
        cmd = ['gh', 'pr', 'view', str(pr_number), 
               '--json', 'number,title,body,isDraft,state,headRefName,author']
        if repo:
            cmd.extend(['--repo', repo])
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to get PR info for #{pr_number}: {e.stderr}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse PR info for #{pr_number}: {e}")
            return None
    
    def assign_copilot_to_pr(
        self,
        pr_number: int,
        instruction: Optional[str] = None,
        repo: Optional[str] = None
    ) -> bool:
        """
        Assign Copilot to an existing PR via comment.
        
        Args:
            pr_number: Pull request number
            instruction: Custom instruction for Copilot
            repo: Repository in format owner/repo
        
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"{'='*80}")
        logger.info(f"🤖 Assigning Copilot to PR #{pr_number}")
        logger.info(f"{'='*80}")
        
        # Get PR info
        pr_info = self.get_pr_info(pr_number, repo)
        if not pr_info:
            return False
        
        logger.info(f"  Title: {pr_info['title']}")
        logger.info(f"  Draft: {pr_info.get('isDraft', False)}")
        logger.info(f"  State: {pr_info['state']}")
        
        # Build instruction based on PR characteristics
        if instruction:
            comment_body = f"@github-copilot /fix\n\n{instruction}"
        else:
            # Use appropriate template based on PR status
            if pr_info.get('isDraft'):
                comment_body = INSTRUCTION_TEMPLATES['draft']
            else:
                comment_body = INSTRUCTION_TEMPLATES['incomplete']
        
        if self.dry_run:
            logger.info(f"\n[DRY RUN] Would post comment on PR #{pr_number}:")
            logger.info(f"{'-'*80}")
            logger.info(comment_body)
            logger.info(f"{'-'*80}\n")
            return True
        
        # Post the comment
        cmd = ['gh', 'pr', 'comment', str(pr_number), '--body', comment_body]
        if repo:
            cmd.extend(['--repo', repo])
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.info(f"✅ Successfully assigned Copilot to PR #{pr_number}")
            logger.info(f"   Comment URL: {result.stdout.strip()}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to post comment on PR #{pr_number}: {e.stderr}")
            return False
    
    def assign_batch(
        self,
        pr_numbers: List[int],
        instruction: Optional[str] = None,
        repo: Optional[str] = None
    ) -> Dict[str, int]:
        """
        Assign Copilot to multiple PRs.
        
        Args:
            pr_numbers: List of PR numbers
            instruction: Custom instruction for all PRs
            repo: Repository in format owner/repo
        
        Returns:
            Dictionary with statistics
        """
        stats = {
            'total': len(pr_numbers),
            'succeeded': 0,
            'failed': 0
        }
        
        logger.info(f"📋 Processing {len(pr_numbers)} PRs...")
        logger.info(f"⏱️  Batch delay: {self.batch_delay} seconds between PRs")
        logger.info("")
        
        for i, pr_number in enumerate(pr_numbers, 1):
            logger.info(f"Processing PR {i}/{len(pr_numbers)}: #{pr_number}")
            
            success = self.assign_copilot_to_pr(pr_number, instruction, repo)
            
            if success:
                stats['succeeded'] += 1
            else:
                stats['failed'] += 1
            
            # Rate limiting: wait between assignments (except for last one)
            if i < len(pr_numbers):
                logger.info(f"⏱️  Waiting {self.batch_delay} seconds before next PR...")
                if not self.dry_run:
                    time.sleep(self.batch_delay)
                logger.info("")
        
        # Print summary
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 Batch Assignment Complete")
        logger.info(f"{'='*80}")
        logger.info(f"Total PRs: {stats['total']}")
        logger.info(f"✅ Succeeded: {stats['succeeded']}")
        logger.info(f"❌ Failed: {stats['failed']}")
        logger.info(f"{'='*80}\n")
        
        return stats


def main():
    parser = argparse.ArgumentParser(
        description='Batch assign Copilot to existing PRs'
    )
    parser.add_argument(
        '--prs',
        required=True,
        help='Comma-separated list of PR numbers (e.g., "123,124,125")'
    )
    parser.add_argument(
        '--instruction',
        help='Custom instruction for Copilot'
    )
    parser.add_argument(
        '--repo',
        help='Repository in OWNER/REPO format (defaults to current repo)'
    )
    parser.add_argument(
        '--batch-delay',
        type=int,
        default=5,
        help='Seconds to wait between PR assignments (default: 5)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    
    args = parser.parse_args()
    
    # Parse PR numbers with better error messages
    try:
        pr_list = [pr.strip() for pr in args.prs.split(',') if pr.strip()]
        pr_numbers = []
        for pr_str in pr_list:
            try:
                pr_num = int(pr_str)
                if pr_num <= 0:
                    raise ValueError(f"PR number must be positive, got: {pr_num}")
                pr_numbers.append(pr_num)
            except ValueError as e:
                logger.error(f"❌ Invalid PR number '{pr_str}': {e}")
                sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Failed to parse PR numbers: {e}")
        sys.exit(1)
    
    if not pr_numbers:
        logger.error("❌ No PR numbers provided")
        sys.exit(1)
    
    # Create assigner and process PRs
    assigner = BatchCopilotAssigner(
        dry_run=args.dry_run,
        batch_delay=args.batch_delay
    )
    
    stats = assigner.assign_batch(
        pr_numbers=pr_numbers,
        instruction=args.instruction,
        repo=args.repo
    )
    
    # Exit with appropriate code
    sys.exit(0 if stats['failed'] == 0 else 1)


if __name__ == '__main__':
    main()
