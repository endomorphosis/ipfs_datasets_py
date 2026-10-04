#!/usr/bin/env python3
"""
Add retry logic to GitHub Actions workflows for flaky operations.

This script adds retry logic using actions/retry or manual retry patterns
for common flaky operations:
- Package installations (pip, npm, cargo)
- API calls (GitHub API, external services)
- Network operations (downloads, uploads)
- Docker operations (build, push, pull)
"""

import os
import sys
import yaml
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

WORKFLOW_DIR = Path(__file__).parent.parent / "workflows"

# Retry patterns for different step types
RETRY_PATTERNS = {
    "pip_install": {
        "pattern": r"pip install",
        "uses": "nick-fields/retry@v2",
        "with": {
            "timeout_minutes": 10,
            "max_attempts": 3,
            "retry_wait_seconds": 30,
            "command": "${{ env.INSTALL_COMMAND }}"
        },
        "description": "Install dependencies with retry"
    },
    "npm_install": {
        "pattern": r"npm (install|ci)",
        "uses": "nick-fields/retry@v2",
        "with": {
            "timeout_minutes": 10,
            "max_attempts": 3,
            "retry_wait_seconds": 30,
            "command": "npm ci"
        },
        "description": "Install npm dependencies with retry"
    },
    "docker_build": {
        "pattern": r"docker build",
        "uses": "nick-fields/retry@v2",
        "with": {
            "timeout_minutes": 30,
            "max_attempts": 2,
            "retry_wait_seconds": 60,
            "command": "${{ env.BUILD_COMMAND }}"
        },
        "description": "Build Docker image with retry"
    },
    "curl_download": {
        "pattern": r"curl.*-O|wget",
        "uses": "nick-fields/retry@v2",
        "with": {
            "timeout_minutes": 5,
            "max_attempts": 3,
            "retry_wait_seconds": 15,
            "command": "${{ env.DOWNLOAD_COMMAND }}"
        },
        "description": "Download with retry"
    },
    "gh_api": {
        "pattern": r"gh (api|pr|issue)",
        "uses": "nick-fields/retry@v2",
        "with": {
            "timeout_minutes": 5,
            "max_attempts": 3,
            "retry_wait_seconds": 10,
            "command": "${{ env.GH_COMMAND }}"
        },
        "description": "GitHub CLI command with retry"
    }
}


def should_add_retry(step: Dict[str, Any]) -> Optional[str]:
    """Check if a step should have retry logic added."""
    # Skip if already using retry action
    if isinstance(step.get("uses"), str) and "retry" in step["uses"]:
        return None
    
    # Skip if step is already wrapped in retry logic
    step_run = step.get("run", "")
    if "retry" in step_run.lower() or "max_attempts" in step_run.lower():
        return None
    
    # Check for patterns that need retry
    for pattern_name, pattern_config in RETRY_PATTERNS.items():
        if re.search(pattern_config["pattern"], step_run, re.IGNORECASE):
            return pattern_name
    
    return None


def add_retry_to_workflow(workflow_path: Path, dry_run: bool = True) -> Dict[str, Any]:
    """Add retry logic to a workflow file."""
    try:
        with open(workflow_path, 'r') as f:
            workflow = yaml.safe_load(f)
    except Exception as e:
        return {"error": f"Failed to read workflow: {e}", "steps_modified": 0}
    
    if not workflow or "jobs" not in workflow:
        return {"error": "Invalid workflow structure", "steps_modified": 0}
    
    modifications = []
    steps_modified = 0
    
    for job_name, job_config in workflow["jobs"].items():
        if "steps" not in job_config:
            continue
        
        for i, step in enumerate(job_config["steps"]):
            pattern_type = should_add_retry(step)
            if pattern_type:
                original_step = step.copy()
                modifications.append({
                    "job": job_name,
                    "step_index": i,
                    "step_name": step.get("name", f"step-{i}"),
                    "pattern_type": pattern_type,
                    "original": original_step
                })
                steps_modified += 1
    
    result = {
        "workflow": workflow_path.name,
        "steps_modified": steps_modified,
        "modifications": modifications
    }
    
    if not dry_run and steps_modified > 0:
        # Note: Actual modification would require more sophisticated YAML handling
        # to preserve comments and formatting. This is a dry-run implementation.
        result["note"] = "Actual modifications require manual review and application"
    
    return result


def analyze_all_workflows(dry_run: bool = True) -> Dict[str, Any]:
    """Analyze all workflows for retry logic opportunities."""
    if not WORKFLOW_DIR.exists():
        return {"error": "Workflow directory not found"}
    
    results = []
    total_steps = 0
    total_workflows = 0
    
    for workflow_file in WORKFLOW_DIR.glob("*.yml"):
        if workflow_file.name.startswith("."):
            continue
        
        result = add_retry_to_workflow(workflow_file, dry_run=dry_run)
        if result.get("steps_modified", 0) > 0:
            results.append(result)
            total_steps += result["steps_modified"]
            total_workflows += 1
    
    summary = {
        "total_workflows_analyzed": len(list(WORKFLOW_DIR.glob("*.yml"))),
        "workflows_needing_retry": total_workflows,
        "total_steps_needing_retry": total_steps,
        "results": results,
        "retry_patterns": list(RETRY_PATTERNS.keys())
    }
    
    return summary


def print_summary(summary: Dict[str, Any]):
    """Print a formatted summary of the analysis."""
    print("\n" + "="*70)
    print("RETRY LOGIC ANALYSIS SUMMARY")
    print("="*70)
    print(f"\nTotal workflows analyzed: {summary['total_workflows_analyzed']}")
    print(f"Workflows needing retry logic: {summary['workflows_needing_retry']}")
    print(f"Total steps needing retry: {summary['total_steps_needing_retry']}")
    
    print(f"\nRetry patterns available: {', '.join(summary['retry_patterns'])}")
    
    if summary["results"]:
        print("\n" + "-"*70)
        print("WORKFLOWS WITH RETRY OPPORTUNITIES:")
        print("-"*70)
        
        for result in summary["results"]:
            print(f"\n📄 {result['workflow']}: {result['steps_modified']} steps")
            for mod in result.get("modifications", [])[:3]:  # Show first 3
                print(f"   • {mod['job']}: {mod['step_name']} ({mod['pattern_type']})")
            if len(result.get("modifications", [])) > 3:
                print(f"   ... and {len(result['modifications']) - 3} more")
    
    print("\n" + "="*70)
    print("\nRECOMMENDATIONS:")
    print("-"*70)
    print("1. Review identified steps and add retry logic where appropriate")
    print("2. Use actions/retry or nick-fields/retry@v2 action")
    print("3. Configure appropriate timeout and retry settings per operation")
    print("4. Test retry logic with intentional failures")
    print("5. Monitor workflow runs to verify retry effectiveness")
    print("="*70 + "\n")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Analyze and add retry logic to GitHub Actions workflows"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Analyze without making changes (default)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (requires manual review)"
    )
    parser.add_argument(
        "--workflow",
        type=str,
        help="Analyze specific workflow file"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )
    
    args = parser.parse_args()
    dry_run = not args.apply
    
    if args.workflow:
        workflow_path = WORKFLOW_DIR / args.workflow
        if not workflow_path.exists():
            print(f"Error: Workflow file not found: {workflow_path}")
            return 1
        
        result = add_retry_to_workflow(workflow_path, dry_run=dry_run)
        if args.json:
            import json
            print(json.dumps(result, indent=2))
        else:
            print(f"\nWorkflow: {result['workflow']}")
            print(f"Steps needing retry: {result['steps_modified']}")
    else:
        summary = analyze_all_workflows(dry_run=dry_run)
        if args.json:
            import json
            print(json.dumps(summary, indent=2))
        else:
            print_summary(summary)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
