#!/usr/bin/env python3
"""
Proper Copilot Agent Invocation Script

This script properly invokes GitHub Copilot agents on draft PRs by using
the repository's existing workflows and the copilot-agent-autofix system.

Based on analysis of the working system.
"""

import subprocess
import json
import sys
import argparse
from typing import Dict, List, Any
from datetime import datetime


class ProperCopilotInvoker:
    """Properly invoke GitHub Copilot agents using the correct method."""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
    
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
    
    def get_draft_prs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all draft PRs that need Copilot work."""
        print(f"🔍 Fetching draft PRs...")
        
        result = self.run_command([
            'gh', 'pr', 'list',
            '--state', 'open',
            '--draft',
            '--limit', str(limit),
            '--json', 'number,title,author,updatedAt,comments,isDraft'
        ])
        
        if not result['success']:
            print(f"❌ Failed to get PRs: {result.get('error')}")
            return []
        
        try:
            prs = json.loads(result['stdout'])
            return prs
        except json.JSONDecodeError:
            print(f"❌ Failed to parse PR data")
            return []
    
    def check_if_copilot_already_mentioned(self, pr: Dict[str, Any]) -> bool:
        """Check if @copilot has already been mentioned in the PR."""
        comments = pr.get('comments', [])
        
        for comment in comments:
            body = comment.get('body', '')
            if '@copilot' in body.lower():
                return True
        
        return False
    
    def trigger_copilot_via_autofix_workflow(self, pr_number: int) -> bool:
        """
        Trigger Copilot by manually running the copilot-agent-autofix workflow.
        
        This is the proper way - use the existing workflow infrastructure.
        """
        print(f"🚀 Triggering copilot-agent-autofix workflow for PR #{pr_number}...")
        
        if self.dry_run:
            print(f"   DRY RUN: Would trigger workflow for PR #{pr_number}")
            return True
        
        # The workflow monitors PRs, so we just need to make sure it sees this PR
        # We can do this by adding a comment that will trigger the system
        
        comment = f"""@copilot

This PR needs implementation work. Please analyze the requirements and implement the necessary changes.

**Triggered by:** Automated queue management system
**Timestamp:** {datetime.now().isoformat()}
**PR:** #{pr_number}

Please proceed with the implementation."""
        
        result = self.run_command([
            'gh', 'pr', 'comment', str(pr_number),
            '--body', comment
        ])
        
        if result['success']:
            print(f"✅ Posted @copilot comment to PR #{pr_number}")
            return True
        else:
            print(f"❌ Failed to post comment: {result.get('stderr')}")
            return False
    
    def invoke_copilot_on_draft_prs(self, max_assignments: int = 3) -> Dict[str, int]:
        """
        Invoke Copilot on draft PRs that need work.
        
        Args:
            max_assignments: Maximum number of new assignments to make
        
        Returns:
            Statistics dictionary
        """
        stats = {
            'total_draft_prs': 0,
            'already_assigned': 0,
            'newly_assigned': 0,
            'failed': 0,
            'skipped': 0
        }
        
        # Get draft PRs
        draft_prs = self.get_draft_prs()
        stats['total_draft_prs'] = len(draft_prs)
        
        print(f"\n📊 Found {len(draft_prs)} draft PRs")
        
        if len(draft_prs) == 0:
            print("✅ No draft PRs found - queue is clear!")
            return stats
        
        assigned_count = 0
        
        for pr in draft_prs:
            pr_number = pr['number']
            title = pr['title']
            author = pr['author']['login']
            
            print(f"\n📋 PR #{pr_number}: {title[:60]}...")
            print(f"   Author: {author}")
            
            # Skip PRs already created by copilot-swe-agent
            if author == 'app/copilot-swe-agent':
                print(f"   ⏭️  Skipping - already created by Copilot")
                stats['skipped'] += 1
                continue
            
            # Check if already has @copilot mention
            if self.check_if_copilot_already_mentioned(pr):
                print(f"   ✅ Already has @copilot mention")
                stats['already_assigned'] += 1
                continue
            
            # Check if we've reached max assignments
            if assigned_count >= max_assignments:
                print(f"   ⏸️  Reached max assignments ({max_assignments})")
                break
            
            # Invoke Copilot
            success = self.trigger_copilot_via_autofix_workflow(pr_number)
            
            if success:
                stats['newly_assigned'] += 1
                assigned_count += 1
                print(f"   ✅ Assigned Copilot to PR #{pr_number}")
            else:
                stats['failed'] += 1
                print(f"   ❌ Failed to assign Copilot to PR #{pr_number}")
        
        return stats
    
    def print_summary(self, stats: Dict[str, int]):
        """Print summary statistics."""
        print(f"\n{'='*80}")
        print(f"📊 Copilot Assignment Summary")
        print(f"{'='*80}")
        print(f"Total draft PRs:        {stats['total_draft_prs']}")
        print(f"Already assigned:       {stats['already_assigned']}")
        print(f"Newly assigned:         {stats['newly_assigned']}")
        print(f"Failed:                 {stats['failed']}")
        print(f"Skipped:                {stats['skipped']}")
        print(f"{'='*80}")
        
        if stats['newly_assigned'] > 0:
            print(f"\n✅ Successfully assigned Copilot to {stats['newly_assigned']} PR(s)")
            print(f"💡 Copilot agents will now work on these PRs")
        elif stats['already_assigned'] > 0:
            print(f"\n✅ All draft PRs already have Copilot assigned")
        else:
            print(f"\n⚠️  No new assignments made")


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(
        description='Properly invoke GitHub Copilot agents on draft PRs'
    )
    parser.add_argument(
        '--max-agents',
        type=int,
        default=3,
        help='Maximum number of new Copilot assignments (default: 3)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run mode - show what would be done'
    )
    
    args = parser.parse_args()
    
    invoker = ProperCopilotInvoker(dry_run=args.dry_run)
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - No actual changes will be made\n")
    
    try:
        stats = invoker.invoke_copilot_on_draft_prs(max_assignments=args.max_agents)
        invoker.print_summary(stats)
        
        sys.exit(0 if stats['failed'] == 0 else 1)
        
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