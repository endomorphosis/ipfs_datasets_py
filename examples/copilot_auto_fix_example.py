#!/usr/bin/env python3
"""
Example: Using Copilot Auto-Fix Script

This example demonstrates how to use the copilot_auto_fix_all_prs.py script
both from command line and programmatically.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.copilot_auto_fix_all_prs import CopilotAutoFixAllPRs


def example_dry_run():
    """Example: Dry run to preview what would be done."""
    print("=" * 80)
    print("Example 1: Dry Run Mode")
    print("=" * 80)
    print()
    
    # Create instance in dry-run mode
    auto_fixer = CopilotAutoFixAllPRs(dry_run=True, github_token=os.environ.get('GITHUB_TOKEN'))
    
    # Process first 5 PRs
    auto_fixer.process_all_prs(limit=5)
    
    print("\n✅ Dry run completed - no actual changes were made")


def example_specific_prs():
    """Example: Process specific PR numbers."""
    print("\n" + "=" * 80)
    print("Example 2: Process Specific PRs")
    print("=" * 80)
    print()
    
    # Create instance
    auto_fixer = CopilotAutoFixAllPRs(dry_run=True)
    
    # Process specific PRs
    pr_numbers = [123, 456]  # Replace with actual PR numbers
    auto_fixer.process_all_prs(pr_numbers=pr_numbers)
    
    print("\n✅ Specific PRs processed")


def example_analyze_single_pr():
    """Example: Analyze a single PR without invoking Copilot."""
    print("\n" + "=" * 80)
    print("Example 3: Analyze Single PR")
    print("=" * 80)
    print()
    
    auto_fixer = CopilotAutoFixAllPRs(dry_run=True)
    
    # Get PR details
    pr_number = 123  # Replace with actual PR number
    pr_details = auto_fixer.get_pr_details(pr_number)
    
    if pr_details:
        print(f"📄 PR #{pr_number}: {pr_details['title']}")
        print(f"📊 Status: {pr_details['state']}")
        print(f"👤 Author: {pr_details['author']['login']}")
        
        # Analyze the PR
        analysis = auto_fixer.analyze_pr(pr_details)
        print(f"\n🎯 Analysis:")
        print(f"   Fix Type: {analysis['fix_type']}")
        print(f"   Priority: {analysis['priority']}")
        print(f"   Should Fix: {analysis['should_fix']}")
        print(f"   Reasons: {', '.join(analysis['reasons'])}")
        
        # Generate instructions
        instructions = auto_fixer.create_copilot_instructions(pr_details, analysis)
        print(f"\n📝 Generated Instructions:")
        print("-" * 80)
        print(instructions[:500] + "..." if len(instructions) > 500 else instructions)
        print("-" * 80)
    else:
        print(f"❌ Could not get details for PR #{pr_number}")


def example_command_line():
    """Example: How to use from command line."""
    print("\n" + "=" * 80)
    print("Example 4: Command Line Usage")
    print("=" * 80)
    print()
    
    print("# Dry run to preview actions:")
    print("python scripts/copilot_auto_fix_all_prs.py --dry-run")
    print()
    
    print("# Fix all open PRs:")
    print("python scripts/copilot_auto_fix_all_prs.py")
    print()
    
    print("# Fix specific PR:")
    print("python scripts/copilot_auto_fix_all_prs.py --pr 123")
    print()
    
    print("# Fix multiple specific PRs:")
    print("python scripts/copilot_auto_fix_all_prs.py --pr 123 --pr 456 --pr 789")
    print()
    
    print("# Limit number of PRs:")
    print("python scripts/copilot_auto_fix_all_prs.py --limit 10")
    print()
    
    print("# With custom token:")
    print("python scripts/copilot_auto_fix_all_prs.py --token 'ghp_your_token'")
    print()
    
    print("# Verbose mode:")
    print("python scripts/copilot_auto_fix_all_prs.py --verbose")


def main():
    """Run all examples."""
    print("""
╔════════════════════════════════════════════════════════════════════════════╗
║                                                                            ║
║              Copilot Auto-Fix All Pull Requests - Examples                ║
║                                                                            ║
╚════════════════════════════════════════════════════════════════════════════╝
""")
    
    # Check if GitHub token is available
    if not os.environ.get('GITHUB_TOKEN') and not os.environ.get('GH_TOKEN'):
        print("⚠️  Warning: No GitHub token found in environment")
        print("   Set GITHUB_TOKEN or GH_TOKEN to run these examples")
        print()
    
    # Run command line examples (these don't require actual API calls)
    example_command_line()
    
    print("\n" + "=" * 80)
    print("Note: The following examples require GitHub CLI to be installed")
    print("      and authenticated. They are shown here for reference.")
    print("=" * 80)
    
    # Show other examples conceptually
    print("\n# To run actual examples:")
    print("# 1. Ensure gh CLI is installed and authenticated")
    print("# 2. Set GITHUB_TOKEN environment variable")
    print("# 3. Uncomment and run the example functions below")
    print()
    print("# example_dry_run()")
    print("# example_specific_prs()")
    print("# example_analyze_single_pr()")
    
    print("\n✨ Examples completed!")


if __name__ == '__main__':
    main()
