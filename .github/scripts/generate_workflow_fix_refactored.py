#!/usr/bin/env python3
"""
Generate Workflow Fix Proposals - Thin Wrapper

This is a thin wrapper around ipfs_datasets_py.utils.workflows.WorkflowFixer
that provides CLI functionality for generating workflow fix proposals.

For core fix generation functionality, see: ipfs_datasets_py/utils/workflows/fixer.py

Usage:
    # Generate fix from analysis file
    python generate_workflow_fix_refactored.py --analysis analysis.json --workflow-name "CI Tests" --output fix.json
    
    # Or generate analysis on-the-fly
    python generate_workflow_fix_refactored.py --workflow-file workflow.yml --error-log error.txt --output fix.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add repository root to path for imports
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Import from utils - this is the single source of truth
from ipfs_datasets_py.utils.workflows import WorkflowAnalyzer, WorkflowFixer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_analysis(analysis_path: Path) -> dict:
    """Load analysis from JSON file."""
    with open(analysis_path, 'r') as f:
        return json.load(f)


def generate_analysis(workflow_file: Path, error_log: str, workflow_name: str) -> dict:
    """Generate analysis using WorkflowAnalyzer."""
    analyzer = WorkflowAnalyzer()
    return analyzer.analyze_failure(
        workflow_file=workflow_file,
        error_log=error_log,
        context={'workflow_name': workflow_name}
    )


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Generate workflow fix proposals',
        epilog='Core fix generation functionality provided by ipfs_datasets_py.utils.workflows.WorkflowFixer'
    )
    
    # Input options
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        '--analysis',
        type=str,
        help='Path to failure analysis JSON file'
    )
    input_group.add_argument(
        '--workflow-file',
        type=str,
        help='Path to workflow YAML file (will generate analysis)'
    )
    
    # Required arguments
    parser.add_argument(
        '--workflow-name',
        required=True,
        help='Workflow name'
    )
    parser.add_argument(
        '--output',
        required=True,
        help='Output file for fix proposal (JSON)'
    )
    
    # Optional for generating analysis
    parser.add_argument(
        '--error-log',
        type=str,
        help='Error log content or path (required if using --workflow-file)'
    )
    
    args = parser.parse_args()
    
    # Get analysis
    if args.analysis:
        # Load from file
        analysis_path = Path(args.analysis)
        if not analysis_path.exists():
            logger.error(f"Analysis file not found: {analysis_path}")
            return 1
        analysis = load_analysis(analysis_path)
    else:
        # Generate analysis
        if not args.error_log:
            logger.error("--error-log is required when using --workflow-file")
            return 1
        
        workflow_file = Path(args.workflow_file)
        if not workflow_file.exists():
            logger.error(f"Workflow file not found: {workflow_file}")
            return 1
        
        # Check if error_log is a file
        error_log_path = Path(args.error_log)
        if error_log_path.exists():
            error_log = error_log_path.read_text()
        else:
            error_log = args.error_log
        
        logger.info("Generating analysis...")
        analysis = generate_analysis(workflow_file, error_log, args.workflow_name)
    
    # Use utils.workflows.WorkflowFixer for core functionality
    logger.info(f"Generating fix proposal for {args.workflow_name}...")
    fixer = WorkflowFixer(
        analysis=analysis,
        workflow_name=args.workflow_name,
    )
    
    proposal = fixer.generate_fix_proposal()
    
    # Write proposal
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(proposal, f, indent=2)
    
    # Print summary
    print(f"✅ Fix proposal generated: {output_path}")
    print(f"   Branch: {proposal['branch_name']}")
    print(f"   Title: {proposal['pr_title']}")
    print(f"   Fix Type: {proposal['fix_type']}")
    print(f"   Fixes: {len(proposal['fixes'])} proposed")
    print(f"   Labels: {', '.join(proposal['labels'])}")
    
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
