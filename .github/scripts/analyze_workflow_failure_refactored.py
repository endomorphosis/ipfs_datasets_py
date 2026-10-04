#!/usr/bin/env python3
"""
Workflow Failure Analyzer - Thin Wrapper

This is a thin wrapper around ipfs_datasets_py.utils.workflows.WorkflowAnalyzer
that provides CLI functionality for analyzing GitHub Actions workflow failures.

For core workflow analysis functionality, see: ipfs_datasets_py/utils/workflows/analyzer.py

Usage:
    python analyze_workflow_failure_refactored.py <workflow_file> [--error-log <log>]
    python analyze_workflow_failure_refactored.py <workflow_file> --run-id <id>
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

# Add repository root to path for imports
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Import from utils - this is the single source of truth
from ipfs_datasets_py.utils.workflows import WorkflowAnalyzer


def fetch_error_log_from_run(run_id: str) -> Optional[str]:
    """Fetch error log from a workflow run.
    
    This is workflow-specific functionality kept in .github/scripts.
    
    Args:
        run_id: GitHub Actions workflow run ID
    
    Returns:
        Error log content or None if not found
    """
    # In a real implementation, this would use GitHub API
    # For now, return placeholder
    return f"Error log placeholder for run {run_id}"


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Analyze GitHub Actions workflow failures',
        epilog='Core analysis functionality provided by ipfs_datasets_py.utils.workflows.WorkflowAnalyzer'
    )
    parser.add_argument('workflow_file', type=Path,
                       help='Path to workflow YAML file')
    parser.add_argument('--error-log', type=str,
                       help='Error log content (or path to log file)')
    parser.add_argument('--run-id', type=str,
                       help='Workflow run ID to fetch log from')
    parser.add_argument('--output', type=Path,
                       help='Output JSON file for analysis results')
    parser.add_argument('--format', choices=['text', 'json'], default='text',
                       help='Output format (default: text)')
    
    args = parser.parse_args()
    
    # Get error log
    error_log = None
    if args.error_log:
        # Check if it's a file path
        log_path = Path(args.error_log)
        if log_path.exists():
            error_log = log_path.read_text()
        else:
            error_log = args.error_log
    elif args.run_id:
        error_log = fetch_error_log_from_run(args.run_id)
    else:
        print("Error: Must provide either --error-log or --run-id", file=sys.stderr)
        return 1
    
    # Use utils.workflows.WorkflowAnalyzer for core analysis
    analyzer = WorkflowAnalyzer()
    result = analyzer.analyze_failure(
        workflow_file=args.workflow_file,
        error_log=error_log,
        context={'run_id': args.run_id} if args.run_id else None
    )
    
    # Output results
    if args.format == 'json':
        output_json = json.dumps(result, indent=2)
        if args.output:
            args.output.write_text(output_json)
            print(f"Analysis saved to {args.output}")
        else:
            print(output_json)
    else:
        # Generate text report using utils
        report = analyzer.generate_report(result)
        if args.output:
            args.output.write_text(report)
            print(f"Report saved to {args.output}")
        else:
            print(report)
    
    # Return error code based on severity
    severity_codes = {'low': 0, 'medium': 0, 'high': 1, 'critical': 2}
    return severity_codes.get(result['severity'], 0)


if __name__ == '__main__':
    sys.exit(main())
