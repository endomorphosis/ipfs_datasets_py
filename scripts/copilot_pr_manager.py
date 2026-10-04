#!/usr/bin/env python3
"""
⚠️⚠️⚠️ DEPRECATED - DO NOT USE ⚠️⚠️⚠️

This script is DEPRECATED and should NOT be used.

Reason: Interactive manager, not for CI/CD automation

This is a manual interactive tool, not suitable for automated workflows.
For automation, use the verified dual method scripts.

The correct method for automation is the DUAL METHOD:
1. Create draft PR
2. Post @copilot trigger comment

Migration: Use scripts/invoke_copilot_on_pr.py for automation

Examples:
  # Automated PR processing
  python scripts/invoke_copilot_on_pr.py --pr 123 --instruction "Fix the issues"
  
  # List PRs needing work (use gh CLI directly)
  gh pr list --state open --draft --json number,title
  
  # Check Copilot progress (check for Copilot's PR)
  gh pr list --author copilot

See:
- DEPRECATED_SCRIPTS.md - Full deprecation documentation
- COPILOT_INVOCATION_GUIDE.md - Verified working method
"""

import sys

print("=" * 80)
print("⚠️  ERROR: This script is DEPRECATED and should not be used!")
print("=" * 80)
print()
print("This is an interactive manager, not for CI/CD automation.")
print()
print("✅ For automation, use: scripts/invoke_copilot_on_pr.py")
print("✅ For manual PR management, use: gh pr list / gh pr view")
print()
print("📖 Documentation:")
print("   - DEPRECATED_SCRIPTS.md")
print("   - COPILOT_INVOCATION_GUIDE.md")
print()
print("=" * 80)
sys.exit(1)

# Original code below (disabled)
"""
GitHub Copilot Coding Agent - Interactive PR Manager

This script provides an interactive interface to manage GitHub Copilot
Coding Agent assignments on pull requests, leveraging both gh CLI and
the GitHub Copilot CLI extension.

Features:
- List all open PRs with Copilot assignment status
- Invoke Copilot on specific PRs with custom instructions
- Check Copilot progress on assigned PRs
- Use GitHub Copilot CLI for code suggestions and explanations
- Interactive mode for manual PR management

Based on:
- https://github.blog/news-insights/company-news/welcome-home-agents/
- https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent
"""

import subprocess
import json
import sys
import argparse
from typing import Dict, List, Any, Optional


class GitHubCopilotPRManager:
    """Interactive manager for GitHub Copilot Coding Agent on PRs."""
    
    def __init__(self):
        self.verify_tools()
    
    def verify_tools(self):
        """Verify that required tools are installed."""
        # Check gh CLI
        result = subprocess.run(['gh', '--version'], capture_output=True)
        if result.returncode != 0:
            print("❌ GitHub CLI (gh) not found. Please install it first.")
            sys.exit(1)
        
        # Check gh copilot extension
        result = subprocess.run(['gh', 'extension', 'list'], capture_output=True, text=True)
        if 'gh-copilot' not in result.stdout:
            print("⚠️  GitHub Copilot extension not found. Installing...")
            subprocess.run(['gh', 'extension', 'install', 'github/gh-copilot'])
            print("✅ Installed gh-copilot extension")
    
    def run_command(self, cmd: List[str], timeout: int = 30) -> Dict[str, Any]:
        """Run a command and return the result."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout
            )
            return {
                'success': True,
                'stdout': result.stdout,
                'stderr': result.stderr
            }
        except subprocess.CalledProcessError as e:
            return {
                'success': False,
                'error': str(e),
                'stdout': e.stdout,
                'stderr': e.stderr
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def list_prs_with_copilot_status(self, limit: int = 30):
        """List all open PRs and show their Copilot assignment status."""
        print("🔍 Fetching pull requests...\n")
        
        result = self.run_command([
            'gh', 'pr', 'list',
            '--state', 'open',
            '--limit', str(limit),
            '--json', 'number,title,isDraft,author,updatedAt,url'
        ])
        
        if not result['success']:
            print(f"❌ Failed to get PRs: {result.get('error')}")
            return
        
        try:
            prs = json.loads(result['stdout'])
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse PR data: {e}")
            return
        
        if not prs:
            print("No open PRs found.")
            return
        
        print(f"{'#':<6} {'Title':<50} {'Draft':<7} {'Author':<20} {'Copilot'}")
        print("=" * 120)
        
        for pr in prs:
            pr_number = pr['number']
            title = pr['title'][:47] + '...' if len(pr['title']) > 50 else pr['title']
            is_draft = '✓' if pr['isDraft'] else ''
            author = pr['author']['login'][:17] + '...' if len(pr['author']['login']) > 20 else pr['author']['login']
            
            # Check if Copilot is assigned
            copilot_status = self.check_copilot_on_pr(pr_number)
            
            print(f"{pr_number:<6} {title:<50} {is_draft:<7} {author:<20} {copilot_status}")
    
    def check_copilot_on_pr(self, pr_number: int) -> str:
        """Check if Copilot has been assigned to a PR."""
        result = self.run_command([
            'gh', 'pr', 'view', str(pr_number),
            '--json', 'comments'
        ])
        
        if not result['success']:
            return '❓'
        
        try:
            data = json.loads(result['stdout'])
            comments = data.get('comments', [])
            
            for comment in comments:
                body = comment.get('body', '').lower()
                if '@copilot' in body or '@github-copilot' in body:
                    return '✅'
            
            return '❌'
        except:
            return '❓'
    
    def show_pr_details(self, pr_number: int):
        """Show detailed information about a PR."""
        result = self.run_command([
            'gh', 'pr', 'view', str(pr_number),
            '--json', 'number,title,body,isDraft,state,author,labels,comments,files,url'
        ])
        
        if not result['success']:
            print(f"❌ Failed to get PR #{pr_number}: {result.get('error')}")
            return
        
        try:
            pr = json.loads(result['stdout'])
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse PR data: {e}")
            return
        
        print(f"\n{'='*80}")
        print(f"PR #{pr['number']}: {pr['title']}")
        print(f"{'='*80}")
        print(f"📊 Status: {pr['state']} {'(Draft)' if pr['isDraft'] else ''}")
        print(f"👤 Author: {pr['author']['login']}")
        print(f"🔗 URL: {pr['url']}")
        print(f"\n📝 Description:")
        print(pr['body'] if pr['body'] else "(No description)")
        
        # Show files changed
        files = pr.get('files', [])
        if files:
            print(f"\n📁 Files Changed ({len(files)}):")
            for f in files[:10]:  # Show first 10 files
                print(f"  - {f['path']}")
            if len(files) > 10:
                print(f"  ... and {len(files) - 10} more files")
        
        # Show Copilot comments
        comments = pr.get('comments', [])
        copilot_comments = [c for c in comments if '@copilot' in c.get('body', '').lower()]
        
        if copilot_comments:
            print(f"\n🤖 Copilot Invocations ({len(copilot_comments)}):")
            for c in copilot_comments:
                print(f"  📅 {c['createdAt']}")
                print(f"  💬 {c['body'][:200]}...")
                print()
        else:
            print("\n🤖 Copilot: Not yet assigned")
        
        print(f"{'='*80}\n")
    
    def invoke_copilot_interactive(self, pr_number: int):
        """Interactively invoke Copilot on a PR."""
        print(f"\n🤖 Invoking GitHub Copilot Coding Agent on PR #{pr_number}")
        print("=" * 80)
        
        # Show PR details
        self.show_pr_details(pr_number)
        
        # Ask for task type
        print("Select task type:")
        print("1. Auto-fix implementation (workflow/error fixes)")
        print("2. Draft PR implementation")
        print("3. Code review and suggestions")
        print("4. Debug and troubleshoot")
        print("5. Custom instructions")
        
        choice = input("\nEnter choice (1-5): ").strip()
        
        task_templates = {
            '1': """@copilot Please implement the auto-fix described in this PR.

**Task**:
1. Analyze the failure described in the PR description
2. Review the proposed fix
3. Implement the fix with minimal changes
4. Ensure the fix follows repository patterns
5. Run relevant tests

Please proceed with implementing this fix.""",
            
            '2': """@copilot Please implement the changes described in this draft PR.

**Task**:
1. Review the PR description and requirements
2. Implement the solution following repository patterns
3. Add or update tests as needed
4. Update documentation if directly related

Please implement the proposed changes.""",
            
            '3': """@copilot /review

Please review this pull request and provide feedback on:
- Code quality and best practices
- Test coverage
- Documentation completeness
- Potential issues or improvements

Please provide a comprehensive review.""",
            
            '4': """@copilot Please debug and fix the issues in this PR.

**Task**:
1. Review error logs and stack traces
2. Identify the root cause
3. Implement a robust fix
4. Add error handling if appropriate
5. Update relevant documentation

Please debug and fix these issues.""",
            
            '5': None  # Custom
        }
        
        if choice in task_templates:
            if choice == '5':
                print("\nEnter your custom instructions for Copilot:")
                print("(Type your message, then press Enter twice to finish)")
                lines = []
                while True:
                    line = input()
                    if line == '' and lines and lines[-1] == '':
                        break
                    lines.append(line)
                comment = '@copilot ' + '\n'.join(lines[:-1])
            else:
                comment = task_templates[choice]
            
            print(f"\n{'─'*80}")
            print("Will post this comment:")
            print(f"{'─'*80}")
            print(comment)
            print(f"{'─'*80}\n")
            
            confirm = input("Post this comment? (y/n): ").strip().lower()
            
            if confirm == 'y':
                result = self.run_command([
                    'gh', 'pr', 'comment', str(pr_number),
                    '--body', comment
                ])
                
                if result['success']:
                    print(f"\n✅ Successfully invoked Copilot on PR #{pr_number}")
                    print(f"🔗 View PR: https://github.com/endomorphosis/ipfs_datasets_py/pull/{pr_number}")
                else:
                    print(f"\n❌ Failed to post comment: {result.get('error')}")
            else:
                print("\n⏭️  Cancelled")
        else:
            print("\n❌ Invalid choice")
    
    def interactive_mode(self):
        """Run in interactive mode."""
        while True:
            print("\n" + "=" * 80)
            print("GitHub Copilot Coding Agent - Interactive PR Manager")
            print("=" * 80)
            print("\n1. List all open PRs with Copilot status")
            print("2. Show detailed PR information")
            print("3. Invoke Copilot on a PR")
            print("4. Batch invoke Copilot on all open PRs")
            print("5. Exit")
            
            choice = input("\nEnter choice (1-5): ").strip()
            
            if choice == '1':
                self.list_prs_with_copilot_status()
            
            elif choice == '2':
                pr_number = input("Enter PR number: ").strip()
                try:
                    self.show_pr_details(int(pr_number))
                except ValueError:
                    print("❌ Invalid PR number")
            
            elif choice == '3':
                pr_number = input("Enter PR number: ").strip()
                try:
                    self.invoke_copilot_interactive(int(pr_number))
                except ValueError:
                    print("❌ Invalid PR number")
            
            elif choice == '4':
                print("\n⚠️  This will invoke Copilot on all open PRs that don't have it assigned yet.")
                confirm = input("Continue? (y/n): ").strip().lower()
                
                if confirm == 'y':
                    subprocess.run(['python', 'scripts/invoke_copilot_coding_agent_on_prs.py'])
                else:
                    print("⏭️  Cancelled")
            
            elif choice == '5':
                print("\n👋 Goodbye!")
                break
            
            else:
                print("\n❌ Invalid choice")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='GitHub Copilot Coding Agent - Interactive PR Manager'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List all open PRs with Copilot status'
    )
    parser.add_argument(
        '--pr',
        type=int,
        help='Show details for specific PR'
    )
    parser.add_argument(
        '--invoke',
        type=int,
        help='Invoke Copilot on specific PR (interactive)'
    )
    
    args = parser.parse_args()
    
    manager = GitHubCopilotPRManager()
    
    if args.list:
        manager.list_prs_with_copilot_status()
    elif args.pr:
        manager.show_pr_details(args.pr)
    elif args.invoke:
        manager.invoke_copilot_interactive(args.invoke)
    else:
        # Interactive mode
        manager.interactive_mode()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
