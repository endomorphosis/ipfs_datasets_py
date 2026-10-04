#!/usr/bin/env python3
"""
⚠️⚠️⚠️ DEPRECATED - DO NOT USE ⚠️⚠️⚠️

This script is DEPRECATED and should NOT be used.

Reason: Targets `gh agent-task create`, which is not available in this environment
and is not the maintained existing-PR workflow for this repo

IRONY ALERT: Despite being named "proper_copilot_invoker", this script
uses a deprecated method for this repo's existing-PR automation.

The maintained repo path is the draft-PR/comment flow via
`invoke_copilot_on_pr.py`.

The correct method is the DUAL METHOD:
1. Create draft PR
2. Post @copilot trigger comment

Migration: Use scripts/invoke_copilot_on_pr.py (the ACTUAL proper method!)

Examples:
  # The REAL proper way
  python scripts/invoke_copilot_on_pr.py --pr 123 --instruction "Fix the issues"

See:
- DEPRECATED_SCRIPTS.md - Full deprecation documentation
- COPILOT_INVOCATION_GUIDE.md - The ACTUAL proper method (100% verified)
"""

import sys

print("=" * 80)
print("⚠️  ERROR: This script is DEPRECATED and should not be used!")
print("=" * 80)
print()
print("IRONY ALERT: Despite the name 'proper_copilot_invoker', this script")
print("uses an older agent-task-based method that is not available here.")
print()
print("✅ Use instead: scripts/invoke_copilot_on_pr.py")
print("   (The ACTUAL proper method - 100% verified)")
print()
print("📖 Documentation:")
print("   - DEPRECATED_SCRIPTS.md")
print("   - COPILOT_INVOCATION_GUIDE.md")
print()
print("=" * 80)
sys.exit(1)

# Original code below (disabled)
"""
Proper Copilot Agent Invocation Script

This script properly invokes GitHub Copilot agents on draft PRs by using
the GitHub CLI's agent-task command (gh agent-task create) when the local
environment supports that hosted task surface.

Based on GitHub's official documentation:
- https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent
- https://docs.github.com/en/copilot/concepts/agents/coding-agent/agent-management
"""

import subprocess
import json
import sys
import argparse
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path

# Try to import the copilot CLI utility
try:
    script_dir = Path(__file__).parent.parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    
    from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
    COPILOT_CLI_AVAILABLE = True
except ImportError:
    COPILOT_CLI_AVAILABLE = False
    import logging
    logging.warning("⚠️  CopilotCLI utility not available, using direct gh commands")


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
    
    def check_if_copilot_already_assigned(self, pr_number: int) -> bool:
        """
        Check if Copilot agent task already exists for this PR.
        
        Uses gh agent-task list to check for existing tasks.
        """
        # Check for agent tasks related to this PR
        result = self.run_command([
            'gh', 'agent-task', 'list',
            '--limit', '50'
        ])
        
        if result['success']:
            # Check if there's a task mentioning this PR number
            stdout = result['stdout']
            if f"#{pr_number}" in stdout or f"PR #{pr_number}" in stdout or f"pull/{pr_number}" in stdout:
                return True
        
        return False
    
    def get_pr_details(self, pr_number: int) -> Optional[Dict[str, Any]]:
        """Get detailed information about a PR."""
        result = self.run_command([
            'gh', 'pr', 'view', str(pr_number),
            '--json', 'number,title,body,headRefName,baseRefName,author'
        ])
        
        if not result['success']:
            print(f"   ❌ Failed to get PR details: {result.get('stderr')}")
            return None
        
        try:
            return json.loads(result['stdout'])
        except json.JSONDecodeError:
            print(f"   ❌ Failed to parse PR details")
            return None
    
    def invoke_copilot_agent(self, pr_number: int, pr_title: str, pr_body: str, 
                            head_branch: str, base_branch: str = "main") -> bool:
        """
        Invoke GitHub Copilot Coding Agent using gh agent-task create.
        
        This is the OFFICIAL and CORRECT method per GitHub documentation:
        https://docs.github.com/en/copilot/concepts/agents/coding-agent/agent-management
        
        Args:
            pr_number: PR number to work on
            pr_title: PR title
            pr_body: PR body/description
            head_branch: Head branch name
            base_branch: Base branch name
        
        Returns:
            True if agent task created successfully
        """
        print(f"🚀 Creating GitHub Copilot agent task for PR #{pr_number}...")
        
        if self.dry_run:
            print(f"   DRY RUN: Would create agent task for PR #{pr_number}")
            return True
        
        # Create comprehensive task description for the agent
        task_description = f"""Complete the work in PR #{pr_number}: {pr_title}

**PR Details**:
- Number: #{pr_number}
- Branch: {head_branch} → {base_branch}
- Status: Draft PR needing implementation

**Description**:
{pr_body[:500] if pr_body else 'No description provided'}

**Instructions**:
1. Review the PR description and understand the requirements
2. Analyze the current state of the branch
3. Implement the necessary changes with minimal, surgical modifications
4. Ensure all tests pass
5. Follow existing code patterns and repository conventions
6. Update documentation only if directly related to changes
7. Push commits to the branch when complete

**Invoked by**: Automated PR monitor system
**Timestamp**: {datetime.now().isoformat()}
"""
        
        # Method 1: Try using CopilotCLI utility (preferred)
        if COPILOT_CLI_AVAILABLE:
            try:
                copilot = CopilotCLI()
                # Note: base_branch should be the target branch (usually main), not the PR's head branch
                result = copilot.create_agent_task(
                    task_description=task_description,
                    base_branch=base_branch,  # Use the PR's base branch (target)
                    follow=False
                )
                
                if result.get('success'):
                    print(f"   ✅ Created agent task using CopilotCLI utility")
                    print(f"   📝 Task: {task_description[:100]}...")
                    if result.get('stdout'):
                        print(f"   📋 Output: {result['stdout'].strip()[:200]}")
                    return True
                else:
                    print(f"   ⚠️  CopilotCLI failed: {result.get('error', 'Unknown error')}")
                    # Fall through to direct gh command
            except Exception as e:
                print(f"   ⚠️  CopilotCLI exception: {e}")
                # Fall through to direct gh command
        
        # Method 2: Direct gh agent-task create command
        # Note: Use base_branch (target branch) not head_branch (source branch)
        result = self.run_command([
            'gh', 'agent-task', 'create',
            task_description,
            '--base', base_branch
        ], timeout=60)
        
        if result['success']:
            print(f"   ✅ Created agent task using gh agent-task command")
            print(f"   📝 Task: {task_description[:100]}...")
            if result.get('stdout'):
                print(f"   📋 Output: {result['stdout'].strip()[:200]}")
            return True
        else:
            error_msg = result.get('stderr', result.get('error', 'Unknown error'))
            print(f"   ❌ Failed to create agent task: {error_msg}")
            
            # Check if gh agent-task is not available
            if 'unknown command' in error_msg.lower() or 'not found' in error_msg.lower():
                print(f"   ⚠️  gh agent-task command not available on this system")
                print(f"   💡 Use scripts/invoke_copilot_on_pr.py for existing PRs in this repo")
            
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
            
            # Check if agent task already exists
            if self.check_if_copilot_already_assigned(pr_number):
                print(f"   ✅ Agent task already exists for this PR")
                stats['already_assigned'] += 1
                continue
            
            # Get detailed PR information
            pr_details = self.get_pr_details(pr_number)
            if not pr_details:
                print(f"   ❌ Failed to get PR details")
                stats['failed'] += 1
                continue
            
            # Check if we've reached max assignments
            if assigned_count >= max_assignments:
                print(f"   ⏸️  Reached max assignments ({max_assignments})")
                break
            
            # Invoke Copilot using proper method (gh agent-task create)
            success = self.invoke_copilot_agent(
                pr_number=pr_number,
                pr_title=pr_details['title'],
                pr_body=pr_details.get('body', ''),
                head_branch=pr_details.get('headRefName', 'main'),
                base_branch=pr_details.get('baseRefName', 'main')
            )
            
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
            print(f"💡 GitHub Copilot Coding Agent will now work on these PRs")
            print(f"📋 Agent tasks created using: gh agent-task create")
        elif stats['already_assigned'] > 0:
            print(f"\n✅ All draft PRs already have Copilot agent tasks")
        else:
            print(f"\n⚠️  No new assignments made")


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(
        description='Invoke GitHub Copilot agents on draft PRs using gh agent-task create (official method)'
    )
    parser.add_argument(
        '--max-agents',
        type=int,
        default=3,
        help='Maximum number of new Copilot agent tasks to create (default: 3)'
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
    
    print("💡 OFFICIAL GITHUB COPILOT INVOCATION METHOD:")
    print("   ✅ Uses: gh agent-task create (GitHub CLI)")
    print("   ✅ Creates proper agent tasks for Copilot Coding Agent")
    print("   ✅ Per GitHub documentation: https://docs.github.com/en/copilot/concepts/agents/coding-agent/")
    print("   ❌ NOT: @copilot mentions in comments (unsupported)")
    print("   ❌ NOT: Draft PR creation method")
    print()
    
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