#!/usr/bin/env python3
"""
Copilot Auto-Fix All Pull Requests

This script finds all open pull requests and uses the GitHub Copilot CLI tool
to invoke the Copilot coding agent to fix them automatically.

This unified script combines functionality from:
- ipfs_datasets_py/utils/copilot_cli.py
- scripts/invoke_copilot_coding_agent_on_prs.py
- scripts/copilot_cli_pr_worker.py
- scripts/copilot_pr_manager.py
- scripts/batch_assign_copilot_to_prs.py

Features:
- Find all open PRs in the repository
- Analyze each PR to determine the appropriate fix strategy
- Invoke GitHub Copilot agent with appropriate instructions
- Track progress and provide detailed reporting
- Support for dry-run mode to preview actions

Usage:
    # Fix all open PRs
    python scripts/copilot_auto_fix_all_prs.py

    # Dry run to see what would be done
    python scripts/copilot_auto_fix_all_prs.py --dry-run

    # Fix specific PR
    python scripts/copilot_auto_fix_all_prs.py --pr 123

    # Limit number of PRs to process
    python scripts/copilot_auto_fix_all_prs.py --limit 10

Requirements:
- GitHub CLI (gh) must be installed and authenticated
- GitHub Copilot CLI extension must be installed (gh extension install github/gh-copilot)
- Valid GitHub token must be set in environment (GITHUB_TOKEN or GH_TOKEN)
"""

import subprocess
import json
import sys
import os
import argparse
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CopilotAutoFixAllPRs:
    """
    Comprehensive PR auto-fixer using GitHub Copilot CLI.
    
    This class provides functionality to:
    1. Find all open pull requests
    2. Analyze each PR to understand what needs fixing
    3. Invoke GitHub Copilot agent with appropriate instructions
    4. Track and report progress
    """
    
    def __init__(self, dry_run: bool = False, github_token: Optional[str] = None):
        """
        Initialize the auto-fixer.
        
        Args:
            dry_run: If True, show what would be done without making changes
            github_token: GitHub token for API access (optional, uses environment if not provided)
        """
        self.dry_run = dry_run
        self.github_token = github_token or os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
        
        # Verify prerequisites
        self._verify_prerequisites()
        
        # Statistics tracking
        self.stats = {
            'total_prs': 0,
            'processed': 0,
            'succeeded': 0,
            'failed': 0,
            'skipped': 0,
            'already_fixed': 0,
            'errors': []
        }
    
    def _verify_prerequisites(self):
        """Verify that all required tools are installed and configured."""
        logger.info("🔍 Verifying prerequisites...")
        
        # Check GitHub CLI
        try:
            result = subprocess.run(
                ['gh', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                logger.error("❌ GitHub CLI (gh) not found. Please install it first.")
                logger.error("   Visit: https://cli.github.com/")
                sys.exit(1)
            logger.info(f"✅ GitHub CLI: {result.stdout.strip().split()[2]}")
        except FileNotFoundError:
            logger.error("❌ GitHub CLI (gh) not found. Please install it first.")
            sys.exit(1)
        except Exception as e:
            logger.error(f"❌ Error checking GitHub CLI: {e}")
            sys.exit(1)
        
        # Check GitHub Copilot extension
        try:
            result = subprocess.run(
                ['gh', 'extension', 'list'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if 'gh-copilot' not in result.stdout:
                logger.warning("⚠️  GitHub Copilot CLI extension not found. Attempting to install...")
                install_result = subprocess.run(
                    ['gh', 'extension', 'install', 'github/gh-copilot'],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if install_result.returncode == 0:
                    logger.info("✅ Installed GitHub Copilot CLI extension")
                else:
                    logger.error("❌ Failed to install GitHub Copilot CLI extension")
                    logger.error(f"   Error: {install_result.stderr}")
                    sys.exit(1)
            else:
                logger.info("✅ GitHub Copilot CLI extension installed")
        except Exception as e:
            logger.error(f"❌ Error checking Copilot CLI extension: {e}")
            sys.exit(1)
        
        # Check GitHub authentication
        if not self.github_token:
            logger.warning("⚠️  No GitHub token found in environment (GITHUB_TOKEN or GH_TOKEN)")
            logger.info("   Attempting to use gh CLI authentication...")
        
        try:
            result = subprocess.run(
                ['gh', 'auth', 'status'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                logger.error("❌ GitHub CLI not authenticated. Please run: gh auth login")
                sys.exit(1)
            logger.info("✅ GitHub CLI authenticated")
        except Exception as e:
            logger.error(f"❌ Error checking GitHub authentication: {e}")
            sys.exit(1)
        
        logger.info("✅ All prerequisites verified\n")
    
    def run_command(self, cmd: List[str], timeout: int = 30, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Run a shell command and return the result.
        
        Args:
            cmd: Command to run as a list of strings
            timeout: Command timeout in seconds
            env: Optional environment variables
        
        Returns:
            Dictionary with success status and output
        """
        try:
            # Merge environment variables
            command_env = os.environ.copy()
            if env:
                command_env.update(env)
            
            # Add GitHub token to environment if available
            if self.github_token and 'GH_TOKEN' not in command_env:
                command_env['GH_TOKEN'] = self.github_token
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=command_env
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
                'error': f'Command timed out after {timeout} seconds',
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
    
    def get_all_open_prs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get all open pull requests from the repository.
        
        Args:
            limit: Maximum number of PRs to retrieve
        
        Returns:
            List of PR dictionaries
        """
        logger.info(f"🔍 Fetching open pull requests (limit: {limit})...")
        
        result = self.run_command([
            'gh', 'pr', 'list',
            '--state', 'open',
            '--limit', str(limit),
            '--json', 'number,title,body,isDraft,state,author,labels,comments,files,url,headRefName'
        ])
        
        if not result['success']:
            logger.error(f"❌ Failed to fetch PRs: {result.get('error', result.get('stderr'))}")
            return []
        
        try:
            prs = json.loads(result['stdout'])
            logger.info(f"✅ Found {len(prs)} open PRs\n")
            return prs
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse PR data: {e}")
            return []
    
    def get_pr_details(self, pr_number: int) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific PR.
        
        Args:
            pr_number: PR number
        
        Returns:
            PR details dictionary or None if failed
        """
        result = self.run_command([
            'gh', 'pr', 'view', str(pr_number),
            '--json', 'number,title,body,isDraft,state,author,labels,comments,files,url,headRefName'
        ])
        
        if not result['success']:
            logger.error(f"❌ Failed to get PR #{pr_number}: {result.get('error', result.get('stderr'))}")
            return None
        
        try:
            return json.loads(result['stdout'])
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse PR #{pr_number} data: {e}")
            return None
    
    def check_copilot_already_invoked(self, pr_details: Dict[str, Any]) -> bool:
        """
        Check if Copilot has already been invoked on this PR.
        
        Args:
            pr_details: PR details dictionary
        
        Returns:
            True if Copilot already invoked, False otherwise
        """
        comments = pr_details.get('comments', [])
        
        for comment in comments:
            body = comment.get('body', '').lower()
            if '@copilot' in body or '@github-copilot' in body:
                return True
        
        # Also check PR body
        pr_body = pr_details.get('body', '').lower()
        if '@copilot' in pr_body or '@github-copilot' in pr_body:
            return True
        
        return False
    
    def analyze_pr(self, pr_details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a PR to determine the appropriate fix strategy.
        
        Args:
            pr_details: PR details dictionary
        
        Returns:
            Analysis dictionary with fix strategy
        """
        pr_number = pr_details['number']
        title = pr_details['title'].lower()
        body = pr_details.get('body', '').lower()
        is_draft = pr_details['isDraft']
        files = pr_details.get('files', [])
        
        analysis = {
            'should_fix': False,
            'fix_type': 'general',
            'priority': 'normal',
            'reasons': [],
            'instructions': ''
        }
        
        # Check for auto-fix PRs (highest priority)
        if 'auto-fix' in title or 'autofix' in title or 'auto fix' in title:
            analysis['should_fix'] = True
            analysis['fix_type'] = 'auto-fix'
            analysis['priority'] = 'critical'
            analysis['reasons'].append("Auto-generated fix PR")
        
        # Check for workflow/CI failures
        if any(keyword in title for keyword in ['workflow', 'ci', 'github actions', 'action']):
            analysis['should_fix'] = True
            analysis['fix_type'] = 'workflow'
            analysis['priority'] = 'high'
            analysis['reasons'].append("Workflow/CI fix")
        
        # Check for permission errors
        if any(keyword in title or keyword in body for keyword in ['permission', 'denied', 'unauthorized']):
            analysis['should_fix'] = True
            analysis['fix_type'] = 'permissions'
            analysis['priority'] = 'high'
            analysis['reasons'].append("Permission error fix")
        
        # Check for syntax/compile errors
        if any(keyword in title or keyword in body for keyword in ['syntax', 'compile', 'build', 'error']):
            analysis['should_fix'] = True
            analysis['fix_type'] = 'syntax'
            analysis['priority'] = 'high'
            analysis['reasons'].append("Syntax/compilation fix")
        
        # Check for test failures
        if any(keyword in title for keyword in ['test', 'failing', 'failure']):
            analysis['should_fix'] = True
            analysis['fix_type'] = 'test'
            analysis['priority'] = 'medium'
            analysis['reasons'].append("Test failure fix")
        
        # Check for draft PRs needing implementation
        if is_draft and not analysis['should_fix']:
            analysis['should_fix'] = True
            analysis['fix_type'] = 'draft'
            analysis['priority'] = 'normal'
            analysis['reasons'].append("Draft PR needing implementation")
        
        # Check for bug fixes
        if any(keyword in title for keyword in ['bug', 'fix', 'issue']):
            analysis['should_fix'] = True
            analysis['fix_type'] = 'bugfix'
            analysis['priority'] = 'medium'
            analysis['reasons'].append("Bug fix")
        
        # If still no reason to fix but it's open, consider for review
        if not analysis['should_fix']:
            analysis['should_fix'] = True
            analysis['fix_type'] = 'review'
            analysis['priority'] = 'low'
            analysis['reasons'].append("General PR review")
        
        return analysis
    
    def create_copilot_instructions(self, pr_details: Dict[str, Any], analysis: Dict[str, Any]) -> str:
        """
        Create appropriate Copilot instructions based on PR analysis.
        
        Args:
            pr_details: PR details dictionary
            analysis: PR analysis dictionary
        
        Returns:
            Copilot instruction string
        """
        pr_number = pr_details['number']
        title = pr_details['title']
        fix_type = analysis['fix_type']
        priority = analysis['priority']
        reasons = ', '.join(analysis['reasons'])
        
        # Base instruction
        instruction = f"@copilot "
        
        # Add fix-type specific instructions
        if fix_type == 'auto-fix':
            instruction += f"""Please implement the auto-fix described in this PR.

**Context**: This PR was automatically created by the auto-healing workflow to fix a failed GitHub Actions workflow.

**Task**:
1. Review the PR description and understand the failure
2. Analyze any error logs or stack traces mentioned
3. Implement the fix with minimal, surgical changes
4. Follow the repository's coding patterns and best practices
5. Ensure all tests pass after the fix
6. Commit the changes with a clear message

**Priority**: {priority.upper()}
**Reason**: {reasons}

Please proceed with implementing this auto-fix."""
        
        elif fix_type == 'workflow':
            instruction += f"""Please fix the workflow/CI issue described in this PR.

**Task**:
1. Review the workflow configuration files
2. Identify the root cause of the failure
3. Implement the fix following GitHub Actions best practices
4. Ensure the workflow syntax is correct
5. Test the workflow configuration if possible
6. Document any significant changes

**Priority**: {priority.upper()}
**Reason**: {reasons}

Please implement the necessary workflow fixes."""
        
        elif fix_type == 'permissions':
            instruction += f"""Please resolve the permission issues in this PR.

**Task**:
1. Identify the specific permission errors
2. Review required permissions for the failing operations
3. Update permission configurations appropriately
4. Ensure security best practices are maintained
5. Test that the permission changes work correctly
6. Document the permission changes made

**Priority**: {priority.upper()}
**Reason**: {reasons}

Please fix the permission issues."""
        
        elif fix_type == 'syntax':
            instruction += f"""Please fix the syntax/compilation errors in this PR.

**Task**:
1. Review the error messages and identify syntax issues
2. Fix all syntax and compilation errors
3. Ensure the code follows language best practices
4. Run linters if available
5. Verify the code compiles/runs successfully
6. Make minimal changes to fix the issues

**Priority**: {priority.upper()}
**Reason**: {reasons}

Please fix the syntax/compilation errors."""
        
        elif fix_type == 'test':
            instruction += f"""Please fix the test failures described in this PR.

**Task**:
1. Identify which tests are failing and why
2. Fix the test failures (either fix tests or fix code)
3. Ensure all tests pass
4. Follow testing best practices
5. Add additional tests if needed
6. Verify test coverage is maintained

**Priority**: {priority.upper()}
**Reason**: {reasons}

Please fix the test failures."""
        
        elif fix_type == 'draft':
            instruction += f"""Please implement the changes described in this draft PR.

**Task**:
1. Review the PR description and understand requirements
2. Implement the solution following repository patterns
3. Add or update tests as appropriate
4. Update documentation if directly related
5. Ensure code quality and best practices
6. Make the PR ready for review

**Priority**: {priority.upper()}
**Reason**: {reasons}

Please implement the proposed changes."""
        
        elif fix_type == 'bugfix':
            instruction += f"""Please implement the bug fix described in this PR.

**Task**:
1. Understand the bug from the PR description
2. Implement a robust fix
3. Add tests to prevent regression
4. Verify the fix resolves the issue
5. Follow coding best practices
6. Update documentation if needed

**Priority**: {priority.upper()}
**Reason**: {reasons}

Please implement the bug fix."""
        
        else:  # review or general
            instruction += f"""Please review and work on this pull request.

**Task**:
1. Review the PR description and code changes
2. Identify any issues or improvements needed
3. Implement necessary changes following best practices
4. Ensure tests pass and code quality is maintained
5. Update documentation if needed
6. Prepare the PR for final review

**Priority**: {priority.upper()}
**Reason**: {reasons}

Please review and improve this PR."""
        
        return instruction
    
    def invoke_copilot_on_pr(self, pr_number: int) -> bool:
        """
        Invoke GitHub Copilot on a specific PR.
        
        Args:
            pr_number: PR number to fix
        
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"\n{'='*80}")
        logger.info(f"🔨 Processing PR #{pr_number}")
        logger.info(f"{'='*80}\n")
        
        # Get PR details
        pr_details = self.get_pr_details(pr_number)
        if not pr_details:
            self.stats['failed'] += 1
            return False
        
        logger.info(f"📄 Title: {pr_details['title']}")
        logger.info(f"📊 Status: {pr_details['state']} {'(Draft)' if pr_details['isDraft'] else ''}")
        logger.info(f"👤 Author: {pr_details['author']['login']}")
        logger.info(f"🔗 URL: {pr_details['url']}")
        
        # Check if Copilot already invoked
        if self.check_copilot_already_invoked(pr_details):
            logger.info(f"✅ Copilot already invoked on PR #{pr_number} - skipping")
            self.stats['already_fixed'] += 1
            self.stats['skipped'] += 1
            return True
        
        # Analyze the PR
        analysis = self.analyze_pr(pr_details)
        
        if not analysis['should_fix']:
            logger.info(f"⏭️  No fix needed for PR #{pr_number}")
            self.stats['skipped'] += 1
            return True
        
        logger.info(f"🎯 Fix Type: {analysis['fix_type']}")
        logger.info(f"⚡ Priority: {analysis['priority']}")
        logger.info(f"📝 Reasons: {', '.join(analysis['reasons'])}")
        
        # Create Copilot instructions
        instructions = self.create_copilot_instructions(pr_details, analysis)
        
        if self.dry_run:
            logger.info(f"\n{'─'*80}")
            logger.info("🔍 DRY RUN - Would post this comment:")
            logger.info(f"{'─'*80}")
            logger.info(instructions)
            logger.info(f"{'─'*80}\n")
            self.stats['succeeded'] += 1
            return True
        
        # Post the Copilot instruction comment
        logger.info("📤 Posting Copilot instructions...")
        result = self.run_command([
            'gh', 'pr', 'comment', str(pr_number),
            '--body', instructions
        ])
        
        if result['success']:
            logger.info(f"✅ Successfully invoked Copilot on PR #{pr_number}")
            logger.info(f"🔗 View PR: {pr_details['url']}")
            self.stats['succeeded'] += 1
            return True
        else:
            error_msg = result.get('error', result.get('stderr', 'Unknown error'))
            logger.error(f"❌ Failed to invoke Copilot on PR #{pr_number}: {error_msg}")
            self.stats['errors'].append({
                'pr': pr_number,
                'error': error_msg
            })
            self.stats['failed'] += 1
            return False
    
    def process_all_prs(self, limit: int = 100, pr_numbers: Optional[List[int]] = None):
        """
        Process all open PRs or specific PR numbers.
        
        Args:
            limit: Maximum number of PRs to process
            pr_numbers: Optional list of specific PR numbers to process
        """
        logger.info("🚀 Starting Copilot Auto-Fix for Pull Requests")
        logger.info("="*80)
        
        if self.dry_run:
            logger.info("🔍 DRY RUN MODE - No actual changes will be made\n")
        
        # Get PRs to process
        if pr_numbers:
            logger.info(f"📋 Processing specific PRs: {pr_numbers}")
            prs = []
            for pr_num in pr_numbers:
                pr_details = self.get_pr_details(pr_num)
                if pr_details:
                    prs.append(pr_details)
        else:
            prs = self.get_all_open_prs(limit=limit)
        
        if not prs:
            logger.warning("⚠️  No PRs to process")
            return
        
        self.stats['total_prs'] = len(prs)
        
        # Process each PR
        for idx, pr in enumerate(prs, 1):
            pr_number = pr['number']
            logger.info(f"\n[{idx}/{len(prs)}] Processing PR #{pr_number}...")
            
            self.stats['processed'] += 1
            self.invoke_copilot_on_pr(pr_number)
        
        # Print summary
        self.print_summary()
    
    def print_summary(self):
        """Print execution summary."""
        logger.info(f"\n{'='*80}")
        logger.info("📊 Execution Summary")
        logger.info(f"{'='*80}")
        logger.info(f"Total PRs found:          {self.stats['total_prs']}")
        logger.info(f"PRs processed:            {self.stats['processed']}")
        logger.info(f"Successfully invoked:     {self.stats['succeeded']}")
        logger.info(f"Already had Copilot:      {self.stats['already_fixed']}")
        logger.info(f"Skipped:                  {self.stats['skipped']}")
        logger.info(f"Failed:                   {self.stats['failed']}")
        
        if self.stats['errors']:
            logger.info(f"\n{'─'*80}")
            logger.info("Errors:")
            for error in self.stats['errors']:
                logger.info(f"  PR #{error['pr']}: {error['error']}")
        
        logger.info(f"{'='*80}\n")
        
        if self.stats['succeeded'] > 0:
            logger.info(f"✨ Successfully invoked Copilot on {self.stats['succeeded']} PR(s)!")
        
        if self.dry_run:
            logger.info("🔍 This was a DRY RUN - no actual changes were made")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Copilot Auto-Fix All Pull Requests',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fix all open PRs
  %(prog)s

  # Dry run to preview actions
  %(prog)s --dry-run

  # Fix specific PR
  %(prog)s --pr 123

  # Fix multiple specific PRs
  %(prog)s --pr 123 --pr 456 --pr 789

  # Limit number of PRs to process
  %(prog)s --limit 10

Environment Variables:
  GITHUB_TOKEN or GH_TOKEN - GitHub authentication token
        """
    )
    
    parser.add_argument(
        '--pr',
        type=int,
        action='append',
        dest='pr_numbers',
        help='Specific PR number to process (can be used multiple times)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=100,
        help='Maximum number of PRs to process (default: 100)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    parser.add_argument(
        '--token',
        type=str,
        help='GitHub token (defaults to GITHUB_TOKEN or GH_TOKEN environment variable)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create auto-fixer instance
    auto_fixer = CopilotAutoFixAllPRs(
        dry_run=args.dry_run,
        github_token=args.token
    )
    
    # Process PRs
    try:
        auto_fixer.process_all_prs(
            limit=args.limit,
            pr_numbers=args.pr_numbers
        )
        
        # Exit with appropriate code
        if auto_fixer.stats['failed'] > 0:
            sys.exit(1)
        else:
            sys.exit(0)
    
    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
