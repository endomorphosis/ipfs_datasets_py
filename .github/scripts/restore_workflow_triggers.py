#!/usr/bin/env python3
"""
Restore Workflow Triggers Script

This script restores correct trigger configuration to workflows that had
their 'on:' replaced with 'true:' by the buggy add_timeouts_bulk.py script.

Usage:
    python restore_workflow_triggers.py --dry-run     # Preview changes
    python restore_workflow_triggers.py --apply       # Apply changes
    python restore_workflow_triggers.py --workflow FILE  # Fix specific workflow
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, Optional
import yaml


# Standard trigger patterns by workflow category
TRIGGER_PATTERNS = {
    # CI/CD Workflows
    "ci_cd": """on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]
  workflow_dispatch:""",
    
    # Monitoring Workflows  
    "monitoring": """on:
  schedule:
    - cron: '*/30 * * * *'  # Every 30 minutes
  workflow_dispatch:""",
    
    # Daily Validation
    "daily_validation": """on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM UTC
  workflow_dispatch:""",
    
    # Auto-Healing Workflows
    "auto_healing": """on:
  workflow_run:
    workflows: ["TARGET_WORKFLOW"]
    types: [completed]
  workflow_dispatch:""",
    
    # PR Workflows
    "pr_workflow": """on:
  pull_request:
    types: [opened, synchronize, reopened]
  workflow_dispatch:""",
    
    # Manual Only
    "manual": """on:
  workflow_dispatch:""",
}

# Workflow classification by name patterns
WORKFLOW_CATEGORIES = {
    "ci_cd": [
        "docker-build-test.yml",
        "docker-ci.yml",
        "graphrag-production-ci.yml",
        "mcp-integration-tests.yml",
        "mcp-dashboard-tests.yml",
        "pdf_processing_ci.yml",
        "gpu-tests.yml",
        "logic-benchmarks.yml",
    ],
    "monitoring": [
        "cli-error-monitoring.yml",
        "cli-error-monitoring-unified.yml",
        "mcp-tools-monitoring.yml",
        "mcp-tools-monitoring-unified.yml",
        "javascript-sdk-monitoring.yml",
        "javascript-sdk-monitoring-unified.yml",
        "github-api-usage-monitor.yml",
        "workflow-health-check.yml",
        "workflow-health-dashboard.yml",
        "workflow-alert-manager.yml",
    ],
    "daily_validation": [
        "scraper-validation.yml",
        "comprehensive-scraper-validation.yml",
        "runner-validation.yml",
        "runner-validation-clean.yml",
        "runner-validation-unified.yml",
        "workflow-validation-ci.yml",
        "workflow-smoke-tests.yml",
        "workflow-integration-tests.yml",
    ],
    "auto_healing": [
        "copilot-agent-autofix.yml",
        "issue-to-draft-pr.yml",
        "continuous-queue-management.yml",
        "update-autohealing-list.yml",
    ],
    "pr_workflow": [
        "pr-completion-monitor.yml",
        "pr-completion-monitor-unified.yml",
        "pr-copilot-monitor.yml",
        "pr-copilot-reviewer.yml",
        "pr-draft-creation-unified.yml",
        "pr-progressive-monitor-unified.yml",
        "enhanced-pr-completion-monitor.yml",
    ],
    "manual": [
        "self-hosted-runner.yml",
        "arm64-runner.yml",
        "test-github-hosted.yml",
        "test-datasets-runner.yml",
        "agentic-optimization.yml",
        "approve-optimization.yml",
        "copilot-issue-assignment.yml",
        "close-stale-draft-prs.yml",
        "documentation-maintenance.yml",
        "gpu-tests-gated.yml",
        "publish_to_pipy.yml",
    ],
}


def get_workflow_category(workflow_name: str) -> Optional[str]:
    """Determine workflow category based on name"""
    for category, workflows in WORKFLOW_CATEGORIES.items():
        if workflow_name in workflows:
            return category
    return None


def has_invalid_trigger(workflow_path: Path) -> bool:
    """Check if workflow has 'true:' instead of 'on:'"""
    try:
        with open(workflow_path, 'r') as f:
            content = f.read()
        
        # Check for 'true:' at the beginning of a line (likely invalid trigger)
        if re.search(r'^true:\s*$', content, re.MULTILINE):
            return True
        
        # Check if workflow is missing 'on:' trigger
        try:
            workflow = yaml.safe_load(content)
            if 'on' not in workflow and 'true' in workflow:
                return True
        except:
            pass
        
        return False
    except Exception as e:
        print(f"Error reading {workflow_path}: {e}")
        return False


def restore_trigger(workflow_path: Path, dry_run: bool = True) -> bool:
    """Restore proper trigger configuration to a workflow"""
    try:
        with open(workflow_path, 'r') as f:
            content = f.read()
        
        workflow_name = workflow_path.name
        category = get_workflow_category(workflow_name)
        
        if not category:
            print(f"⚠️  {workflow_name}: Unknown category, using manual trigger")
            category = "manual"
        
        trigger_pattern = TRIGGER_PATTERNS[category]
        
        # Replace 'true:' with appropriate trigger
        new_content = re.sub(
            r'^true:\s*$',
            trigger_pattern,
            content,
            count=1,
            flags=re.MULTILINE
        )
        
        if new_content != content:
            if not dry_run:
                with open(workflow_path, 'w') as f:
                    f.write(new_content)
                print(f"✅ {workflow_name}: Restored {category} trigger")
            else:
                print(f"🔍 {workflow_name}: Would restore {category} trigger")
            return True
        else:
            print(f"ℹ️  {workflow_name}: No changes needed")
            return False
    
    except Exception as e:
        print(f"❌ Error processing {workflow_path}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Restore workflow trigger configurations"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without applying them'
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Apply trigger fixes'
    )
    parser.add_argument(
        '--workflow',
        type=str,
        help='Fix specific workflow file'
    )
    parser.add_argument(
        '--workflows-dir',
        type=str,
        default='.github/workflows',
        help='Path to workflows directory'
    )
    
    args = parser.parse_args()
    
    if not args.dry_run and not args.apply:
        print("Error: Must specify either --dry-run or --apply")
        return 1
    
    workflows_dir = Path(args.workflows_dir)
    
    if args.workflow:
        # Fix specific workflow
        workflow_path = workflows_dir / args.workflow
        if not workflow_path.exists():
            print(f"Error: Workflow {args.workflow} not found")
            return 1
        
        if has_invalid_trigger(workflow_path):
            restore_trigger(workflow_path, dry_run=args.dry_run)
        else:
            print(f"ℹ️  {args.workflow}: Already has valid trigger")
    else:
        # Fix all workflows
        workflow_files = list(workflows_dir.glob("*.yml")) + \
                        list(workflows_dir.glob("*.yaml"))
        
        fixed_count = 0
        skipped_count = 0
        
        print(f"\n{'🔍 DRY RUN MODE' if args.dry_run else '🔧 APPLYING FIXES'}\n")
        
        for workflow_path in sorted(workflow_files):
            if workflow_path.name.startswith('.'):
                continue
            
            if has_invalid_trigger(workflow_path):
                if restore_trigger(workflow_path, dry_run=args.dry_run):
                    fixed_count += 1
            else:
                skipped_count += 1
        
        print(f"\n📊 Summary:")
        print(f"  {'Would fix' if args.dry_run else 'Fixed'}: {fixed_count} workflows")
        print(f"  Skipped: {skipped_count} workflows (already valid)")
        
        if args.dry_run:
            print(f"\nℹ️  Run with --apply to apply these changes")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
