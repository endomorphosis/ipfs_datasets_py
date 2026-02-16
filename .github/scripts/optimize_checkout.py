#!/usr/bin/env python3
"""
Optimize GitHub Actions checkout operations.

This script analyzes and optimizes actions/checkout usage:
- Add fetch-depth: 1 for shallow clones (faster)
- Remove unnecessary checkouts
- Optimize checkout parameters
"""

import os
import sys
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional

WORKFLOW_DIR = Path(__file__).parent.parent / "workflows"


def should_optimize_checkout(step: Dict[str, Any], job_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Determine if a checkout step should be optimized."""
    if not isinstance(step.get("uses"), str):
        return None
    
    if "actions/checkout" not in step["uses"]:
        return None
    
    with_params = step.get("with", {})
    
    # Skip if already optimized
    if "fetch-depth" in with_params:
        return None
    
    # Determine if full history is needed
    needs_full_history = False
    
    # Check job steps for operations that need history
    for job_step in job_context.get("steps", []):
        run_script = job_step.get("run", "")
        # Look for git operations that need history
        if any(cmd in run_script for cmd in ["git log", "git diff", "git blame", "git tag --list"]):
            needs_full_history = True
            break
    
    optimization = {
        "add_fetch_depth": not needs_full_history,
        "recommended_depth": 1 if not needs_full_history else 0,
        "reason": "No git history operations detected" if not needs_full_history else "Git history needed"
    }
    
    return optimization


def analyze_workflow(workflow_path: Path) -> Dict[str, Any]:
    """Analyze a workflow for checkout optimizations."""
    try:
        with open(workflow_path, 'r') as f:
            workflow = yaml.safe_load(f)
    except Exception as e:
        return {"error": f"Failed to read workflow: {e}"}
    
    if not workflow or "jobs" not in workflow:
        return {"error": "Invalid workflow structure"}
    
    optimizations = []
    checkout_count = 0
    optimizable_count = 0
    
    for job_name, job_config in workflow["jobs"].items():
        if "steps" not in job_config:
            continue
        
        for i, step in enumerate(job_config["steps"]):
            if isinstance(step.get("uses"), str) and "actions/checkout" in step["uses"]:
                checkout_count += 1
                optimization = should_optimize_checkout(step, job_config)
                
                if optimization and optimization.get("add_fetch_depth"):
                    optimizations.append({
                        "job": job_name,
                        "step_index": i,
                        "step_name": step.get("name", f"checkout-{i}"),
                        "optimization": optimization
                    })
                    optimizable_count += 1
    
    return {
        "workflow": workflow_path.name,
        "checkout_count": checkout_count,
        "optimizable_count": optimizable_count,
        "optimizations": optimizations
    }


def analyze_all_workflows() -> Dict[str, Any]:
    """Analyze all workflows for checkout optimizations."""
    if not WORKFLOW_DIR.exists():
        return {"error": "Workflow directory not found"}
    
    results = []
    total_checkouts = 0
    total_optimizable = 0
    
    for workflow_file in WORKFLOW_DIR.glob("*.yml"):
        if workflow_file.name.startswith("."):
            continue
        
        result = analyze_workflow(workflow_file)
        if "error" not in result and result.get("optimizable_count", 0) > 0:
            results.append(result)
            total_checkouts += result["checkout_count"]
            total_optimizable += result["optimizable_count"]
    
    return {
        "total_workflows_analyzed": len(list(WORKFLOW_DIR.glob("*.yml"))),
        "workflows_with_optimizations": len(results),
        "total_checkouts": total_checkouts,
        "total_optimizable": total_optimizable,
        "results": results
    }


def print_summary(summary: Dict[str, Any]):
    """Print formatted summary."""
    print("\n" + "="*70)
    print("CHECKOUT OPTIMIZATION ANALYSIS")
    print("="*70)
    print(f"\nTotal workflows analyzed: {summary['total_workflows_analyzed']}")
    print(f"Workflows with optimizable checkouts: {summary['workflows_with_optimizations']}")
    print(f"Total checkouts found: {summary['total_checkouts']}")
    print(f"Optimizable checkouts: {summary['total_optimizable']}")
    
    if summary.get("total_optimizable", 0) > 0:
        time_saved = summary["total_optimizable"] * 10  # Estimate 10s saved per checkout
        print(f"\nEstimated time savings: ~{time_saved} seconds per workflow run")
        print(f"Network data savings: ~{summary['total_optimizable'] * 50}MB per run")
    
    if summary["results"]:
        print("\n" + "-"*70)
        print("OPTIMIZATION OPPORTUNITIES:")
        print("-"*70)
        
        for result in summary["results"][:10]:  # Show first 10
            print(f"\n📄 {result['workflow']}")
            print(f"   Checkouts: {result['checkout_count']}, Optimizable: {result['optimizable_count']}")
            for opt in result["optimizations"][:2]:  # Show first 2 per workflow
                print(f"   • {opt['job']}: {opt['step_name']}")
                print(f"     → Add fetch-depth: {opt['optimization']['recommended_depth']}")
        
        if len(summary["results"]) > 10:
            print(f"\n... and {len(summary['results']) - 10} more workflows")
    
    print("\n" + "="*70)
    print("\nRECOMMENDATIONS:")
    print("-"*70)
    print("1. Add 'fetch-depth: 1' to checkouts that don't need git history")
    print("2. This reduces clone time by 80-90% for large repositories")
    print("3. Reduces network bandwidth usage significantly")
    print("4. Keep full history (fetch-depth: 0) when needed for:")
    print("   - git log, git diff, git blame operations")
    print("   - Tag listing and comparison")
    print("   - Changelog generation")
    print("5. Test workflows after optimization to ensure correctness")
    print("="*70 + "\n")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Analyze and optimize checkout operations in GitHub Actions"
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
    
    if args.workflow:
        workflow_path = WORKFLOW_DIR / args.workflow
        if not workflow_path.exists():
            print(f"Error: Workflow file not found: {workflow_path}")
            return 1
        
        result = analyze_workflow(workflow_path)
        if args.json:
            import json
            print(json.dumps(result, indent=2))
        else:
            print(f"\nWorkflow: {result['workflow']}")
            print(f"Checkouts: {result.get('checkout_count', 0)}")
            print(f"Optimizable: {result.get('optimizable_count', 0)}")
    else:
        summary = analyze_all_workflows()
        if args.json:
            import json
            print(json.dumps(summary, indent=2))
        else:
            print_summary(summary)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
