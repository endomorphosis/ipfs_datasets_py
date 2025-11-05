#!/usr/bin/env python3
"""
Issue-Based PR Monitor - Proper Copilot Invocation

This script monitors incomplete PRs and creates ISSUES (not PR comments) to
trigger GitHub Copilot coding agents. This is the CORRECT method based on evidence:

✅ WORKING: Issue #339 → Copilot created PR #382  
❌ NOT WORKING: @copilot comments on PRs → No response

The script:
1. Monitors open draft PRs
2. Analyzes PR completion status
3. Creates issues describing the work needed
4. Copilot automatically creates PRs to fix issues
"""

import subprocess
import json
import sys
import logging
import argparse
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta


class IssueBasedPRMonitor:
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
    
    def create_issue_for_pr(self, pr: Dict[str, Any], reason: str) -> bool:
        """
        Create an issue that Copilot will automatically create a PR for.
        
        Args:
            pr: PR data dictionary
            reason: Why this PR needs work
        
        Returns:
            True if issue created successfully
        """
        pr_number = pr['number']
        pr_title = pr['title']
        pr_body = pr.get('body', 'No description provided')
        pr_url = pr['url']
        branch = pr['headRefName']
        author = pr['author']['login']
        
        # Create issue title
        issue_title = f"Complete draft PR #{pr_number}: {pr_title}"
        
        # Create issue body - SIMPLE and CLEAR for Copilot
        issue_body = f"""# Complete Draft PR #{pr_number}

## Original PR
- **Link**: {pr_url}
- **Title**: {pr_title}
- **Branch**: `{branch}`
- **Author**: @{author}
- **Why needs work**: {reason}

## Description
{pr_body}

## Task
Please review draft PR #{pr_number} and complete the necessary work:

1. Analyze the current changes in the PR
2. Identify what work remains to be done
3. Implement the required changes
4. Test that everything works correctly
5. Update the PR or create a new PR with the implementation

## Context
- This is an incomplete draft PR that needs to be finished
- Related PR: #{pr_number}
- Auto-generated: {datetime.now().isoformat()}
"""
        
        if self.dry_run:
            self.logger.info(f"\n{'─'*80}")
            self.logger.info(f"DRY RUN: Would create issue for PR #{pr_number}")
            self.logger.info(f"Title: {issue_title}")
            self.logger.info(f"Reason: {reason}")
            self.logger.info(f"{'─'*80}\n")
            return True
        
        # Create the issue (without labels to avoid rate limits)
        result = self.run_command([
            'gh', 'issue', 'create',
            '--title', issue_title,
            '--body', issue_body
        ])
        
        if result['success']:
            output = result['stdout'].strip()
            self.logger.info(f"✅ Created issue for PR #{pr_number}: {output}")
            return True
        else:
            self.logger.error(f"❌ Failed to create issue for PR #{pr_number}: {result.get('stderr')}")
            return False
    
    def monitor_prs(self, max_issues: int = 5) -> Dict[str, int]:
        """
        Monitor PRs and create issues for incomplete ones.
        
        Args:
            max_issues: Maximum number of issues to create per run
        
        Returns:
            Statistics dictionary
        """
        stats = {
            'total_prs': 0,
            'needs_work': 0,
            'issues_created': 0,
            'already_has_issue': 0,
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
        
        issues_created = 0
        
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
            
            # Check if we've already created an issue
            if self.check_if_issue_exists(pr_number):
                self.logger.info(f"   ⏭️  Issue already exists")
                stats['already_has_issue'] += 1
                continue
            
            # Check if we've reached max issues for this run
            if issues_created >= max_issues:
                self.logger.info(f"   ⏸️  Reached max issues ({max_issues})")
                break
            
            # Create issue
            success = self.create_issue_for_pr(pr, reason)
            
            if success:
                stats['issues_created'] += 1
                issues_created += 1
            else:
                stats['errors'] += 1
        
        return stats
    
    def print_summary(self, stats: Dict[str, int]):
        """Print summary statistics."""
        self.logger.info(f"\n{'='*80}")
        self.logger.info(f"📊 Issue-Based PR Monitor Summary")
        self.logger.info(f"{'='*80}")
        self.logger.info(f"Total draft PRs:          {stats['total_prs']}")
        self.logger.info(f"PRs needing work:         {stats['needs_work']}")
        self.logger.info(f"Issues created:           {stats['issues_created']}")
        self.logger.info(f"Already have issues:      {stats['already_has_issue']}")
        self.logger.info(f"Skipped (Copilot PRs):    {stats['skipped_copilot_prs']}")
        self.logger.info(f"Errors:                   {stats['errors']}")
        self.logger.info(f"{'='*80}")
        
        if stats['issues_created'] > 0:
            self.logger.info(f"\n✅ Created {stats['issues_created']} issue(s)")
            self.logger.info(f"💡 GitHub Copilot will automatically create PRs to fix these issues")
        elif stats['needs_work'] == 0:
            self.logger.info(f"\n✅ All draft PRs appear complete")
        elif stats['already_has_issue'] > 0:
            self.logger.info(f"\n⏳ {stats['already_has_issue']} PR(s) already have issues - waiting for Copilot")


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(
        description='Monitor PRs and create issues for Copilot (correct invocation method)'
    )
    parser.add_argument(
        '--max-issues',
        type=int,
        default=5,
        help='Maximum number of issues to create per run (default: 5)'
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
    
    monitor = IssueBasedPRMonitor(
        dry_run=args.dry_run,
        notification_user=args.notification_user
    )
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - No actual changes will be made\n")
    
    print("💡 PROPER COPILOT INVOCATION METHOD:")
    print("   ✅ Create issues describing work needed")
    print("   ✅ Copilot automatically creates PRs to fix issues")
    print("   ❌ NOT: Commenting @copilot on existing PRs\n")
    
    try:
        stats = monitor.monitor_prs(max_issues=args.max_issues)
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
