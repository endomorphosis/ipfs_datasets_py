#!/usr/bin/env python3
"""
Draft PR Monitor - Proper Copilot Invocation (VS Code Method)

This script monitors incomplete PRs and creates DRAFT PRs (not issues) to
trigger GitHub Copilot coding agents. This is the method VS Code uses.

How it works:
1. Monitors open draft PRs that need completion
2. For each incomplete PR, creates a NEW draft PR with task description
3. Copilot detects the draft PR and starts working on it
4. Copilot pushes commits to complete the work

This mimics the VS Code Copilot invocation method.
"""

import subprocess
import json
import sys
import logging
import argparse
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta


class DraftPRCopilotInvoker:
    """Monitor PRs and create issues for Copilot to work on."""
    
    def __init__(self, dry_run: bool = False, notification_user: str = None):
        self.dry_run = dry_run
        self.notification_user = notification_user
        self.logger = self._setup_logger()
    
    def _setup_logger(self) -> logging.Logger:
        """Set up logging."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        return logging.getLogger(__name__)
    
    def run_command(self, cmd: List[str], timeout: int = 30) -> Dict[str, Any]:
        """Run a command and return result."""
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
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_draft_prs(self) -> List[Dict[str, Any]]:
        """Get all open draft PRs."""
        self.logger.info("🔍 Fetching draft PRs...")
        
        result = self.run_command([
            'gh', 'pr', 'list',
            '--state', 'open',
            '--draft',
            '--limit', '100',
            '--json', 'number,title,body,author,url,headRefName,createdAt,updatedAt'
        ])
        
        if not result['success']:
            self.logger.error(f"Failed to get PRs: {result.get('error')}")
            return []
        
        try:
            return json.loads(result['stdout'])
        except json.JSONDecodeError:
            self.logger.error("Failed to parse PR data")
            return []
    
    def check_if_issue_exists(self, pr_number: int) -> bool:
        """Check if an issue already exists for this PR."""
        result = self.run_command([
            'gh', 'issue', 'list',
            '--search', f'"Complete draft PR #{pr_number}" in:title',
            '--state', 'all',
            '--limit', '5',
            '--json', 'number,title'
        ])
        
        if not result['success']:
            return False
        
        try:
            issues = json.loads(result['stdout'])
            return len(issues) > 0
        except:
            return False
    
    def check_if_stale(self, updated_at: str, threshold_hours: int = 24) -> bool:
        """Check if PR is stale (no updates for threshold hours)."""
        try:
            updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            threshold = datetime.now(updated.tzinfo) - timedelta(hours=threshold_hours)
            return updated < threshold
        except:
            return False
    
    def check_if_needs_work(self, pr: Dict[str, Any]) -> Optional[str]:
        """
        Check if PR needs work and return reason.
        
        Returns:
            String describing why PR needs work, or None if complete
        """
        reasons = []
        
        # Check if it's a draft
        # (Already filtered by get_draft_prs, but double-check)
        reasons.append("PR is marked as draft")
        
        # Check PR body for TODO items
        body = pr.get('body', '')
        if body:
            if 'TODO' in body or 'FIXME' in body or '[ ]' in body:
                reasons.append("PR contains TODO items or incomplete checkboxes")
        
        # Check if stale
        if self.check_if_stale(pr['updatedAt'], threshold_hours=24):
            reasons.append("PR has not been updated in 24+ hours")
        
        # Check if created by auto-fix system
        author = pr['author']['login']
        if author == 'app/github-actions':
            reasons.append("Auto-generated PR from workflow failure")
        
        if reasons:
            return " | ".join(reasons)
        return None
    
    def create_draft_pr_for_work(self, pr: Dict[str, Any], reason: str) -> bool:
        """
        Create a DRAFT PR for Copilot to work on (VS Code method).
        
        This mimics how VS Code invokes Copilot:
        1. Create a new branch
        2. Make initial commit
        3. Push branch
        4. Create draft PR
        5. Copilot detects draft PR and starts working
        
        Args:
            pr: Original PR data dictionary
            reason: Why this PR needs work
        
        Returns:
            True if draft PR created successfully
        """
        pr_number = pr['number']
        pr_title = pr['title']
        pr_body = pr.get('body', 'No description provided')
        pr_url = pr['url']
        author = pr['author']['login']
        
        # Create task title
        task_title = f"Complete draft PR #{pr_number}: {pr_title}"
        
        # Create task description - SIMPLE and CLEAR for Copilot
        task_description = f"""# Complete Draft PR #{pr_number}

## Original PR
- **Link**: {pr_url}
- **Title**: {pr_title}
- **Author**: @{author}
- **Why needs work**: {reason}

## Description
{pr_body}

## Task
Please complete the work from draft PR #{pr_number}:

1. Review the original PR and its current state
2. Identify what work remains to be done
3. Implement the required changes
4. Test that everything works correctly
5. Push commits to this branch

## Context
- This is to complete an unfinished draft PR
- Related PR: #{pr_number}
- Invoked: {datetime.now().isoformat()}
"""
        
        if self.dry_run:
            self.logger.info(f"\n{'─'*80}")
            self.logger.info(f"DRY RUN: Would create draft PR for original PR #{pr_number}")
            self.logger.info(f"Title: {task_title}")
            self.logger.info(f"Reason: {reason}")
            self.logger.info(f"{'─'*80}\n")
            return True
        
        # Use the draft PR invoker script
        result = self.run_command([
            'python3', 'scripts/invoke_copilot_via_draft_pr.py',
            '--title', task_title,
            '--description', task_description,
            '--repo', 'endomorphosis/ipfs_datasets_py',
            '--base', 'main',
            '--branch-prefix', f'copilot/complete-pr-{pr_number}'
        ], timeout=60)
        
        if result['success']:
            self.logger.info(f"✅ Created draft PR for original PR #{pr_number}")
            return True
        else:
            self.logger.error(f"❌ Failed to create draft PR for PR #{pr_number}: {result.get('stderr')}")
            return False
    
    def monitor_prs(self, max_drafts: int = 5) -> Dict[str, int]:
        """
        Monitor PRs and create draft PRs for Copilot to work on (VS Code method).
        
        Args:
            max_drafts: Maximum number of draft PRs to create per run
        
        Returns:
            Statistics dictionary
        """
        stats = {
            'total_prs': 0,
            'needs_work': 0,
            'draft_prs_created': 0,
            'already_has_draft': 0,
            'skipped_copilot_prs': 0,
            'errors': 0
        }
        
        # Get draft PRs
        draft_prs = self.get_draft_prs()
        stats['total_prs'] = len(draft_prs)
        
        self.logger.info(f"📊 Found {len(draft_prs)} draft PRs\n")
        
        if len(draft_prs) == 0:
            self.logger.info("✅ No draft PRs found")
            return stats
        
        draft_prs_created = 0
        
        for pr in draft_prs:
            pr_number = pr['number']
            title = pr['title']
            author = pr['author']['login']
            
            self.logger.info(f"📋 PR #{pr_number}: {title[:60]}...")
            
            # Skip PRs already created by Copilot
            if author == 'app/copilot-swe-agent':
                self.logger.info(f"   ⏭️  Skipping - created by Copilot")
                stats['skipped_copilot_prs'] += 1
                continue
            
            # Check if PR needs work
            reason = self.check_if_needs_work(pr)
            if not reason:
                self.logger.info(f"   ✅ PR appears complete")
                continue
            
            stats['needs_work'] += 1
            self.logger.info(f"   ⚠️  Needs work: {reason}")
            
            # Check if we've already created a draft PR for this
            if self.check_if_issue_exists(pr_number):
                self.logger.info(f"   ⏭️  Draft PR already created")
                stats['already_has_draft'] += 1
                continue
            
            # Check if we've reached max drafts for this run
            if draft_prs_created >= max_drafts:
                self.logger.info(f"   ⏸️  Reached max drafts ({max_drafts})")
                break
            
            # Create draft PR for Copilot
            success = self.create_draft_pr_for_work(pr, reason)
            
            if success:
                stats['draft_prs_created'] += 1
                draft_prs_created += 1
            else:
                stats['errors'] += 1
        
        return stats
    
    def print_summary(self, stats: Dict[str, int]):
        """Print summary statistics."""
        self.logger.info(f"\n{'='*80}")
        self.logger.info(f"📊 Draft PR Copilot Invoker Summary")
        self.logger.info(f"{'='*80}")
        self.logger.info(f"Total draft PRs:          {stats['total_prs']}")
        self.logger.info(f"PRs needing work:         {stats['needs_work']}")
        self.logger.info(f"Draft PRs created:        {stats['draft_prs_created']}")
        self.logger.info(f"Already have drafts:      {stats['already_has_draft']}")
        self.logger.info(f"Skipped (Copilot PRs):    {stats['skipped_copilot_prs']}")
        self.logger.info(f"Errors:                   {stats['errors']}")
        self.logger.info(f"{'='*80}")
        
        if stats['draft_prs_created'] > 0:
            self.logger.info(f"\n✅ Created {stats['draft_prs_created']} draft PR(s) for Copilot")
            self.logger.info(f"💡 GitHub Copilot will automatically detect and work on these PRs")
        elif stats['needs_work'] == 0:
            self.logger.info(f"\n✅ All draft PRs appear complete")
        elif stats['already_has_draft'] > 0:
            self.logger.info(f"\n⏳ {stats['already_has_draft']} PR(s) already have draft PRs - waiting for Copilot")


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(
        description='Monitor PRs and create draft PRs for Copilot (VS Code method)'
    )
    parser.add_argument(
        '--max-drafts',
        type=int,
        default=5,
        help='Maximum number of draft PRs to create per run (default: 5)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    parser.add_argument(
        '--notification-user',
        type=str,
        help='GitHub username to notify for manual review'
    )
    
    args = parser.parse_args()
    
    monitor = DraftPRCopilotInvoker(
        dry_run=args.dry_run,
        notification_user=args.notification_user
    )
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - No actual changes will be made\n")
    
    print("💡 VS CODE COPILOT INVOCATION METHOD:")
    print("   ✅ Create draft PRs for Copilot to work on")
    print("   ✅ Copilot automatically detects and implements changes")
    print("   ❌ NOT: Commenting @copilot on existing PRs")
    print("   ❌ NOT: Creating issues (old method)\n")
    
    try:
        stats = monitor.monitor_prs(max_drafts=args.max_drafts)
        monitor.print_summary(stats)
        
        sys.exit(0 if stats['errors'] == 0 else 1)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
