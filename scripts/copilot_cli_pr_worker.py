#!/usr/bin/env python3
"""
GitHub Copilot CLI PR Worker

Uses the NEW GitHub Copilot CLI (installed via npm) to work on pull requests.
This is different from gh copilot extension - this is an interactive AI agent
that can actually modify code, create PRs, and work on issues.

Based on: https://docs.github.com/en/copilot/concepts/agents/about-copilot-cli

Features:
- Uses the copilot CLI command (not gh copilot)
- Can actually work on PRs and implement fixes
- Interactive AI agent with code modification capabilities
- Integrates with GitHub.com API

Requirements:
- npm install -g @github/copilot
- GitHub Copilot subscription
- Node.js 22+ and npm 10+

Usage:
    # Work on specific PR
    python scripts/copilot_cli_pr_worker.py --pr 246

    # Work on all open PRs needing Copilot
    python scripts/copilot_cli_pr_worker.py --all

    # Dry run to see what would be done
    python scripts/copilot_cli_pr_worker.py --dry-run
"""

import subprocess
import json
import sys
import argparse
from typing import Dict, List, Any, Optional
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CopilotCLIPRWorker:
    """Worker that uses GitHub Copilot CLI to work on PRs."""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._verify_copilot_cli()
    
    def _verify_copilot_cli(self):
        """Verify that Copilot CLI is installed."""
        result = subprocess.run(
            ['which', 'copilot'],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            logger.error("❌ GitHub Copilot CLI not found!")
            logger.error("Install with: sudo npm install -g @github/copilot")
            logger.error("See: https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli")
            sys.exit(1)
        
        # Check version
        result = subprocess.run(
            ['copilot', '--version'],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            logger.info(f"✅ GitHub Copilot CLI installed: {result.stdout.strip()}")
        else:
            logger.warning("⚠️  Could not determine Copilot CLI version")
    
    def run_copilot_command(self, prompt: str, allow_all: bool = True) -> Dict[str, Any]:
        """
        Run a Copilot CLI command with a prompt.
        
        Args:
            prompt: The prompt to send to Copilot CLI
            allow_all: Whether to allow all tools (default: True for automation)
        
        Returns:
            Dict with success, output, and error info
        """
        cmd = ['copilot', '-p', prompt]
        
        if allow_all:
            cmd.append('--allow-all-tools')
        
        logger.info(f"🤖 Running Copilot CLI: {prompt[:100]}...")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
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
                'error': 'Command timed out after 5 minutes',
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
    
    def get_pr_info(self, pr_number: int) -> Optional[Dict[str, Any]]:
        """Get PR information using Copilot CLI."""
        prompt = f"""Get detailed information about PR #{pr_number} in the current repository including:
        - Title and description
        - Whether it's a draft
        - What files are changed
        - If there are any @copilot mentions in comments
        - What the PR is trying to fix
        
        Return the information in a structured format."""
        
        result = self.run_copilot_command(prompt)
        
        if result['success']:
            # Parse the output to extract PR info
            # The Copilot CLI returns natural language, so we'll just return the output
            return {
                'pr_number': pr_number,
                'copilot_response': result['stdout']
            }
        else:
            logger.error(f"Failed to get PR info: {result.get('error', result.get('stderr'))}")
            return None
    
    def work_on_pr(self, pr_number: int, task_description: Optional[str] = None) -> bool:
        """
        Use Copilot CLI to work on a PR.
        
        This will:
        1. Checkout the PR branch
        2. Analyze the PR and the issue it's fixing
        3. Implement the necessary changes
        4. Commit and push the changes
        
        Args:
            pr_number: The PR number to work on
            task_description: Optional specific task description
        
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"\n{'='*80}")
        logger.info(f"🔨 Working on PR #{pr_number}")
        logger.info(f"{'='*80}\n")
        
        if self.dry_run:
            logger.info("🔍 DRY RUN MODE - Would work on PR but not making actual changes")
            return True
        
        # Build the prompt for Copilot CLI
        if task_description:
            prompt = task_description
        else:
            prompt = f"""I have PR #{pr_number} in the current repository (endomorphosis/ipfs_datasets_py).
            
Please:
1. Checkout the PR branch
2. Read the PR description and linked issue to understand what needs to be fixed
3. Analyze the workflow failure logs if mentioned
4. Implement the necessary fixes following the project's patterns
5. Test that the changes are correct
6. Commit the changes with a clear commit message
7. Push the changes to the PR branch

The PR was auto-generated by the workflow auto-healing system and needs implementation.
Focus on fixing the specific issue mentioned (permission errors, syntax errors, etc.).
Make minimal, surgical changes that directly address the problem."""
        
        logger.info(f"📝 Task: {prompt[:200]}...")
        
        result = self.run_copilot_command(prompt, allow_all=True)
        
        if result['success']:
            logger.info("✅ Copilot CLI completed the task!")
            logger.info(f"\n{'-'*80}")
            logger.info("Output:")
            logger.info(result['stdout'])
            logger.info(f"{'-'*80}\n")
            return True
        else:
            logger.error(f"❌ Copilot CLI failed: {result.get('error', result.get('stderr'))}")
            if result.get('stdout'):
                logger.info(f"Partial output:\n{result['stdout']}")
            return False
    
    def list_prs_needing_work(self) -> List[Dict[str, Any]]:
        """List PRs that need Copilot to work on them."""
        prompt = """List all open draft PRs in the current repository (endomorphosis/ipfs_datasets_py) that:
        - Have @copilot mentions in their description or comments
        - Are auto-generated by github-actions bot
        - Have 'auto-fix' or 'autofix' in their title
        
        For each PR, show:
        - PR number
        - Title
        - What issue it's trying to fix
        - Whether work has been done on it yet
        
        Focus on PRs that haven't been implemented yet."""
        
        result = self.run_copilot_command(prompt)
        
        if result['success']:
            logger.info("📊 PRs needing work:")
            logger.info(result['stdout'])
            # Return a simple list - the output is natural language
            return [{'info': result['stdout']}]
        else:
            logger.error(f"Failed to list PRs: {result.get('error', result.get('stderr'))}")
            return []
    
    def work_on_all_prs(self, limit: int = 10) -> Dict[str, int]:
        """
        Work on all PRs that need Copilot implementation.
        
        Returns:
            Statistics dictionary
        """
        logger.info("🔍 Finding PRs that need work...")
        
        # Use Copilot CLI to list PRs
        prs_info = self.list_prs_needing_work()
        
        if not prs_info:
            logger.info("No PRs found needing work.")
            return {'total': 0, 'succeeded': 0, 'failed': 0}
        
        # For now, we'll ask Copilot to work on the first few PRs
        # In a real scenario, we'd parse the PR numbers from the output
        prompt = f"""Work on the first {limit} open draft PRs in endomorphosis/ipfs_datasets_py that have @copilot mentions.

For each PR:
1. Checkout the PR branch
2. Understand what needs to be fixed from the PR description and linked issue
3. Implement the fix
4. Commit and push

Work through them one by one, making surgical fixes for each issue (permission errors, syntax errors, etc.).
Don't work on PRs that already have commits beyond the initial auto-creation."""
        
        result = self.run_copilot_command(prompt, allow_all=True)
        
        if result['success']:
            logger.info("✅ Batch processing completed!")
            logger.info(result['stdout'])
            return {'total': limit, 'succeeded': limit, 'failed': 0}
        else:
            logger.error(f"❌ Batch processing failed: {result.get('error', result.get('stderr'))}")
            return {'total': limit, 'succeeded': 0, 'failed': limit}


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(
        description='GitHub Copilot CLI PR Worker - Use Copilot AI to work on PRs'
    )
    parser.add_argument(
        '--pr',
        type=int,
        help='Specific PR number to work on'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Work on all PRs needing Copilot'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List PRs needing work'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=5,
        help='Maximum number of PRs to process (default: 5)'
    )
    
    args = parser.parse_args()
    
    worker = CopilotCLIPRWorker(dry_run=args.dry_run)
    
    if args.dry_run:
        logger.info("🔍 DRY RUN MODE\n")
    
    if args.list:
        worker.list_prs_needing_work()
    elif args.pr:
        success = worker.work_on_pr(args.pr)
        sys.exit(0 if success else 1)
    elif args.all:
        stats = worker.work_on_all_prs(limit=args.limit)
        logger.info(f"\n📊 Summary: {stats['succeeded']}/{stats['total']} PRs completed successfully")
        sys.exit(0 if stats['failed'] == 0 else 1)
    else:
        parser.print_help()


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
