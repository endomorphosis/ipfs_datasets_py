#!/usr/bin/env python3
"""
Close Stale Auto-Generated Draft PRs

This script helps clean up the spam of draft PRs created by the auto-healing system.
It can be run manually to close all auto-generated draft PRs that are stale.

Usage:
    # Dry run - see what would be closed
    python scripts/close_stale_draft_prs.py --dry-run

    # Close draft PRs older than 24 hours
    python scripts/close_stale_draft_prs.py --max-age-hours 24

    # Close all auto-generated draft PRs regardless of age
    python scripts/close_stale_draft_prs.py --max-age-hours 0

    # Close specific PR numbers
    python scripts/close_stale_draft_prs.py --pr-numbers 123,124,125

Requirements:
    - GitHub CLI (gh) installed and authenticated
"""

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class StaleDraftPRCloser:
    """Close stale auto-generated draft PRs."""
    
    def __init__(self, dry_run: bool = False, max_age_hours: int = 48):
        """
        Initialize the closer.
        
        Args:
            dry_run: If True, show what would be done without making changes
            max_age_hours: Maximum age in hours before considering PR stale
        """
        self.dry_run = dry_run
        self.max_age_hours = max_age_hours
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
            version_line = result.stdout.strip().split('\n')[0]
            logger.info(f"✅ GitHub CLI: {version_line}")
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error("❌ GitHub CLI not found. Install from https://cli.github.com/")
            sys.exit(1)
    
    def run_command(self, cmd: List[str], timeout: int = 60) -> Dict[str, Any]:
        """Run a command and return structured result."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False
            )
            return {
                'success': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode
            }
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Command timed out'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_all_draft_prs(self) -> List[Dict[str, Any]]:
        """Get all open draft PRs."""
        logger.info("🔍 Fetching all draft PRs...")
        
        cmd = [
            'gh', 'pr', 'list',
            '--state', 'open',
            '--draft',
            '--limit', '500',
            '--json', 'number,title,author,createdAt,updatedAt,url,isDraft,headRefName'
        ]
        
        result = self.run_command(cmd)
        
        if not result['success']:
            logger.error(f"❌ Failed to get PRs: {result.get('error', result.get('stderr'))}")
            return []
        
        try:
            prs = json.loads(result['stdout'])
            logger.info(f"📊 Found {len(prs)} draft PRs")
            return prs
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse PR data: {e}")
            return []
    
    def filter_stale_prs(self, prs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter for stale auto-generated PRs."""
        logger.info(f"🔍 Filtering for stale PRs (older than {self.max_age_hours}h)...")
        
        if self.max_age_hours > 0:
            cutoff_time = datetime.utcnow() - timedelta(hours=self.max_age_hours)
        else:
            cutoff_time = datetime.utcnow() + timedelta(days=365)  # All PRs
        
        stale_prs = []
        
        for pr in prs:
            # Check if auto-generated (created by github-actions bot or copilot)
            author = pr['author']['login']
            if author not in ['github-actions[bot]', 'app/copilot-swe-agent']:
                continue
            
            # Check if PR title/branch indicates auto-generation
            title = pr['title'].lower()
            branch = pr.get('headRefName', '').lower()
            
            is_auto_generated = (
                'autofix' in title or 'auto-healing' in title or
                'fix:' in title or 'complete draft pr' in title or
                'autofix' in branch or 'issue-' in branch or
                'copilot/' in branch
            )
            
            if not is_auto_generated:
                continue
            
            # Check age
            updated_at_str = pr.get('updatedAt', pr.get('createdAt'))
            try:
                updated_at = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
                updated_at = updated_at.replace(tzinfo=None)
            except Exception as e:
                logger.warning(f"⚠️  Could not parse date for PR #{pr['number']}: {e}")
                continue
            
            if updated_at < cutoff_time:
                stale_prs.append(pr)
        
        logger.info(f"📋 Found {len(stale_prs)} stale auto-generated draft PRs")
        return stale_prs
    
    def close_pr(self, pr: Dict[str, Any]) -> bool:
        """Close a draft PR with explanatory comment."""
        pr_number = pr['number']
        pr_title = pr['title']
        author = pr['author']['login']
        
        logger.info(f"\nProcessing PR #{pr_number}")
        logger.info(f"  Title: {pr_title[:70]}...")
        logger.info(f"  Author: {author}")
        logger.info(f"  Last updated: {pr.get('updatedAt', pr.get('createdAt'))}")
        
        if self.dry_run:
            logger.info(f"  [DRY RUN] Would close PR #{pr_number}")
            return True
        
        # Create closing comment
        close_comment = f"""🤖 **Automatically Closing Stale Draft PR**

This draft PR has been automatically closed as part of cleanup.

**Details**:
- **Created by**: {author}
- **Age**: Over {self.max_age_hours} hours with no updates
- **Created**: {pr.get('createdAt', 'Unknown')}
- **Last Updated**: {pr.get('updatedAt', 'Unknown')}

### Why was this closed?

This PR was created by the auto-healing system but appears to be stale or abandoned:
- No commits or updates in over {self.max_age_hours} hours
- Part of cleanup to resolve the draft PR spam issue
- The auto-healing system created 100+ draft PRs overnight

### What should you do?

- ✅ **If work is done**: No action needed, this can be ignored
- 🔄 **If still needed**: You can reopen this PR
- 🆕 **If issue persists**: The auto-healing system will create a new fix attempt
- 📝 **Related issue**: Check if there's an associated issue that needs attention

---

🤖 *Automated cleanup to resolve draft PR spam*
*See issue about auto-healing creating 100+ PRs overnight*
"""
        
        # Post comment
        comment_cmd = [
            'gh', 'pr', 'comment', str(pr_number),
            '--body', close_comment
        ]
        
        comment_result = self.run_command(comment_cmd)
        
        if not comment_result['success']:
            logger.warning(f"  ⚠️  Failed to post comment: {comment_result.get('stderr', 'Unknown error')}")
        else:
            logger.info(f"  📝 Posted closing comment")
        
        # Close the PR
        close_cmd = [
            'gh', 'pr', 'close', str(pr_number),
            '--comment', f'Closing stale draft PR (part of auto-healing cleanup)'
        ]
        
        close_result = self.run_command(close_cmd)
        
        if close_result['success']:
            logger.info(f"  ✅ Successfully closed PR #{pr_number}")
            return True
        else:
            logger.error(f"  ❌ Failed to close PR #{pr_number}: {close_result.get('stderr', 'Unknown error')}")
            return False
    
    def close_specific_prs(self, pr_numbers: List[int]) -> Dict[str, int]:
        """Close specific PR numbers."""
        stats = {
            'total': len(pr_numbers),
            'closed': 0,
            'failed': 0
        }
        
        logger.info(f"\n{'='*80}")
        logger.info(f"Closing {len(pr_numbers)} specific PRs")
        logger.info(f"{'='*80}\n")
        
        for pr_number in pr_numbers:
            # Get PR details
            cmd = [
                'gh', 'pr', 'view', str(pr_number),
                '--json', 'number,title,author,createdAt,updatedAt,url,isDraft'
            ]
            
            result = self.run_command(cmd)
            
            if not result['success']:
                logger.error(f"❌ Could not get details for PR #{pr_number}")
                stats['failed'] += 1
                continue
            
            try:
                pr = json.loads(result['stdout'])
            except json.JSONDecodeError:
                logger.error(f"❌ Could not parse details for PR #{pr_number}")
                stats['failed'] += 1
                continue
            
            if self.close_pr(pr):
                stats['closed'] += 1
            else:
                stats['failed'] += 1
        
        return stats
    
    def close_all_stale_prs(self) -> Dict[str, int]:
        """Close all stale auto-generated draft PRs."""
        # Get all draft PRs
        all_prs = self.get_all_draft_prs()
        
        if not all_prs:
            logger.info("✅ No draft PRs found")
            return {'total': 0, 'closed': 0, 'failed': 0}
        
        # Filter for stale auto-generated PRs
        stale_prs = self.filter_stale_prs(all_prs)
        
        if not stale_prs:
            logger.info("✅ No stale draft PRs found")
            return {'total': 0, 'closed': 0, 'failed': 0}
        
        stats = {
            'total': len(stale_prs),
            'closed': 0,
            'failed': 0
        }
        
        logger.info(f"\n{'='*80}")
        logger.info(f"Processing {len(stale_prs)} stale draft PRs")
        logger.info(f"{'='*80}\n")
        
        for pr in stale_prs:
            if self.close_pr(pr):
                stats['closed'] += 1
            else:
                stats['failed'] += 1
        
        return stats
    
    def print_summary(self, stats: Dict[str, int]):
        """Print summary statistics."""
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 Closure Summary")
        logger.info(f"{'='*80}")
        logger.info(f"Total PRs processed:      {stats['total']}")
        logger.info(f"Successfully closed:      {stats['closed']}")
        logger.info(f"Failed to close:          {stats['failed']}")
        logger.info(f"{'='*80}")
        
        if self.dry_run:
            logger.info("\n💡 This was a DRY RUN - no PRs were actually closed")
            logger.info("   Run without --dry-run to close the PRs")
        elif stats['closed'] > 0:
            logger.info(f"\n✅ Successfully cleaned up {stats['closed']} stale draft PR(s)")


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(
        description='Close stale auto-generated draft PRs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to see what would be closed
  python scripts/close_stale_draft_prs.py --dry-run

  # Close PRs older than 24 hours
  python scripts/close_stale_draft_prs.py --max-age-hours 24

  # Close all auto-generated draft PRs (use with caution!)
  python scripts/close_stale_draft_prs.py --max-age-hours 0

  # Close specific PR numbers
  python scripts/close_stale_draft_prs.py --pr-numbers 123,124,125

Purpose:
  This script helps clean up the draft PR spam created by the auto-healing
  system. It only closes PRs created by github-actions[bot] or copilot that
  match auto-generation patterns.
"""
    )
    parser.add_argument(
        '--max-age-hours',
        type=int,
        default=48,
        help='Maximum age in hours before considering PR stale (default: 48, use 0 for all)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    parser.add_argument(
        '--pr-numbers',
        type=str,
        help='Comma-separated list of specific PR numbers to close'
    )
    
    args = parser.parse_args()
    
    closer = StaleDraftPRCloser(
        dry_run=args.dry_run,
        max_age_hours=args.max_age_hours
    )
    
    logger.info("="*80)
    logger.info("🧹 Stale Draft PR Cleanup Tool")
    logger.info("="*80)
    logger.info(f"Configuration:")
    logger.info(f"  - Max age: {args.max_age_hours} hours {'(all PRs)' if args.max_age_hours == 0 else ''}")
    logger.info(f"  - Dry run: {args.dry_run}")
    logger.info(f"  - Target: Auto-generated draft PRs only")
    logger.info("="*80)
    
    if args.dry_run:
        logger.info("\n🔍 DRY RUN MODE - No PRs will be closed\n")
    
    try:
        if args.pr_numbers:
            # Close specific PRs
            pr_numbers = [int(n.strip()) for n in args.pr_numbers.split(',')]
            stats = closer.close_specific_prs(pr_numbers)
        else:
            # Close all stale PRs
            stats = closer.close_all_stale_prs()
        
        closer.print_summary(stats)
        
        sys.exit(0 if stats['failed'] == 0 else 1)
        
    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n💥 Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
