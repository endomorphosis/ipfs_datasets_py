#!/usr/bin/env python3
"""
Example: Using Automated PR Review System

This example demonstrates how to use the automated PR review system
to analyze and invoke GitHub Copilot on pull requests.

Prerequisites:
    - GitHub CLI installed and authenticated (gh auth login)
    - Repository access
    
Usage:
    python examples/automated_pr_review_example.py
"""

import sys
from pathlib import Path

# Add scripts directory to path
scripts_dir = Path(__file__).parent.parent / 'scripts'
sys.path.insert(0, str(scripts_dir))

from automated_pr_review import AutomatedPRReviewer


def example_1_analyze_specific_pr():
    """Example 1: Analyze a specific PR without invoking Copilot."""
    print("\n" + "="*80)
    print("Example 1: Analyze Specific PR (Dry-Run)")
    print("="*80)
    
    # Create reviewer in dry-run mode
    reviewer = AutomatedPRReviewer(dry_run=True, min_confidence=60)
    
    # Analyze PR #123 (example - replace with real PR number)
    # In dry-run mode, this shows what would be done without actually posting
    result = reviewer.invoke_copilot_on_pr(123)
    
    print(f"\nResult: {result}")
    

def example_2_review_all_prs_dry_run():
    """Example 2: Review all open PRs in dry-run mode."""
    print("\n" + "="*80)
    print("Example 2: Review All Open PRs (Dry-Run)")
    print("="*80)
    
    # Create reviewer with custom confidence threshold
    reviewer = AutomatedPRReviewer(dry_run=True, min_confidence=70)
    
    # Review all PRs (limited to 10 for example)
    stats = reviewer.review_all_prs(limit=10)
    
    # Print summary
    reviewer.print_summary(stats)
    

def example_3_custom_criteria_analysis():
    """Example 3: Demonstrate custom criteria analysis."""
    print("\n" + "="*80)
    print("Example 3: Custom Criteria Analysis")
    print("="*80)
    
    # Create reviewer
    reviewer = AutomatedPRReviewer(dry_run=True)
    
    # Example PR details (normally fetched from GitHub)
    example_pr = {
        'number': 999,
        'title': 'Fix GitHub Actions workflow permissions',
        'body': 'This PR fixes permission denied errors in our CI workflow. Resolves #888.',
        'isDraft': False,
        'labels': [
            {'name': 'auto-fix'},
            {'name': 'workflow'}
        ],
        'files': [
            {'path': '.github/workflows/ci.yml'},
            {'path': 'README.md'}
        ],
        'mergeable': 'MERGEABLE',
        'updatedAt': '2025-10-31T18:00:00Z',
        'headRefName': 'autohealing/fix-workflow-permissions',
        'comments': []
    }
    
    # Analyze the PR
    analysis = reviewer.analyze_pr(example_pr)
    
    print(f"\nPR Analysis Results:")
    print(f"  Should Invoke: {analysis['should_invoke']}")
    print(f"  Confidence: {analysis['confidence']}%")
    print(f"  Task Type: {analysis['task_type']}")
    print(f"  Reasons: {', '.join(analysis['reasons'])}")
    print(f"\n  Criteria Scores:")
    for criterion, score in analysis['criteria_scores'].items():
        print(f"    • {criterion}: {score:+d}")
    
    # Show what comment would be posted
    if analysis['should_invoke']:
        comment = reviewer.create_copilot_comment(example_pr, analysis)
        print(f"\n  Generated Copilot Comment:")
        print(f"  {'─'*76}")
        for line in comment.split('\n'):
            print(f"  {line}")
        print(f"  {'─'*76}")


def example_4_programmatic_usage():
    """Example 4: Using the system programmatically."""
    print("\n" + "="*80)
    print("Example 4: Programmatic Usage")
    print("="*80)
    
    # Initialize reviewer
    reviewer = AutomatedPRReviewer(dry_run=True, min_confidence=65)
    
    # Get all open PRs
    print("\nFetching open PRs...")
    prs = reviewer.get_all_open_prs(limit=5)
    
    if not prs:
        print("No open PRs found (or authentication required)")
        return
    
    print(f"Found {len(prs)} open PRs\n")
    
    # Analyze each PR and show decision
    for pr in prs:
        pr_details = reviewer.get_pr_details(pr['number'])
        if not pr_details:
            continue
            
        analysis = reviewer.analyze_pr(pr_details)
        
        print(f"PR #{pr['number']}: {pr['title'][:50]}...")
        print(f"  → Confidence: {analysis['confidence']}%")
        print(f"  → Decision: {'INVOKE' if analysis['should_invoke'] else 'SKIP'}")
        print(f"  → Task: {analysis['task_type']}\n")


def example_5_mcp_tool_equivalent():
    """Example 5: Show MCP tool equivalent usage."""
    print("\n" + "="*80)
    print("Example 5: MCP Tool Integration")
    print("="*80)
    
    print("""
The automated PR review system is also available as MCP tools:

1. AutomatedPRReviewTool - Review all open PRs
   
   Usage via MCP:
   {
       "tool": "automated_pr_review",
       "parameters": {
           "dry_run": false,
           "min_confidence": 60,
           "limit": 100
       }
   }

2. AnalyzePRTool - Analyze specific PR
   
   Usage via MCP:
   {
       "tool": "analyze_pr",
       "parameters": {
           "pr_number": 123,
           "min_confidence": 60
       }
   }

3. InvokeCopilotOnPRTool - Invoke on specific PR
   
   Usage via MCP:
   {
       "tool": "invoke_copilot_on_pr",
       "parameters": {
           "pr_number": 123,
           "force": false,
           "dry_run": false
       }
   }

These tools are automatically registered with the MCP server when it starts.
    """)


def main():
    """Run all examples."""
    print("\n" + "="*80)
    print("Automated PR Review System - Usage Examples")
    print("="*80)
    
    try:
        # Run examples
        example_1_analyze_specific_pr()
        example_2_review_all_prs_dry_run()
        example_3_custom_criteria_analysis()
        example_4_programmatic_usage()
        example_5_mcp_tool_equivalent()
        
        print("\n" + "="*80)
        print("Examples Complete!")
        print("="*80)
        print("\nNext Steps:")
        print("  1. Authenticate with GitHub CLI: gh auth login")
        print("  2. Try dry-run mode: python scripts/automated_pr_review.py --dry-run")
        print("  3. Review specific PR: python scripts/automated_pr_review.py --pr 123 --dry-run")
        print("  4. See full guide: AUTOMATED_PR_REVIEW_GUIDE.md")
        
    except KeyboardInterrupt:
        print("\n\nExamples interrupted by user")
    except Exception as e:
        print(f"\n\nError running examples: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
