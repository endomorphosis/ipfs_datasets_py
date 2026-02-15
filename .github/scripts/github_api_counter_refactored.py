#!/usr/bin/env python3
"""
GitHub API Call Counter - Thin Wrapper

This is a thin wrapper around ipfs_datasets_py.utils.github.APICounter that provides
CLI functionality and merge utilities for GitHub Actions workflows.

For the core API counter functionality, see: ipfs_datasets_py/utils/github/counter.py

Usage:
    # Run a command and track it
    python github_api_counter.py --command gh pr list
    
    # Show usage report
    python github_api_counter.py --report
    
    # Merge multiple metrics files
    python github_api_counter.py --merge file1.json file2.json --output merged.json
"""

import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List

# Add repository root to path for imports
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Import from utils - this is the single source of truth
from ipfs_datasets_py.utils.github import APICounter, GitHubAPICounter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def merge_metrics(metrics_files: List[Path], output_file: Path) -> Dict[str, Any]:
    """Merge multiple metrics files into a single aggregated report.
    
    This is workflow-specific functionality kept in .github/scripts for
    convenience, but uses the core APICounter from utils.
    
    Args:
        metrics_files: List of metrics JSON files to merge
        output_file: Where to write merged metrics
    
    Returns:
        Merged metrics dictionary
    """
    merged_data = {
        'workflows': [],
        'total_calls': 0,
        'total_cost': 0,
        'call_counts_aggregated': {},
    }
    
    for metrics_file in metrics_files:
        if not metrics_file.exists():
            logger.warning(f"Metrics file not found: {metrics_file}")
            continue
        
        try:
            with open(metrics_file, 'r') as f:
                data = json.load(f)
                
                merged_data['workflows'].append({
                    'workflow_name': data.get('workflow_name'),
                    'run_id': data.get('workflow_run_id'),
                    'total_calls': data.get('total_api_calls', 0),
                    'estimated_cost': data.get('total_cost', 0),
                })
                
                merged_data['total_calls'] += data.get('total_api_calls', 0)
                merged_data['total_cost'] += data.get('total_cost', 0)
                
                # Aggregate call counts
                for call_type, count in data.get('calls_by_type', {}).items():
                    merged_data['call_counts_aggregated'][call_type] = \
                        merged_data['call_counts_aggregated'].get(call_type, 0) + count
        except Exception as e:
            logger.warning(f"Could not load {metrics_file}: {e}")
    
    with open(output_file, 'w') as f:
        json.dump(merged_data, f, indent=2)
    
    logger.info(f"Merged {len(metrics_files)} metrics files into {output_file}")
    return merged_data


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='GitHub API Call Counter',
        epilog='Core functionality provided by ipfs_datasets_py.utils.github.APICounter'
    )
    parser.add_argument('--command', nargs='+', 
                       help='GitHub CLI command to run and track')
    parser.add_argument('--report', action='store_true', 
                       help='Show usage report from existing metrics')
    parser.add_argument('--merge', nargs='+', 
                       help='Merge multiple metrics files')
    parser.add_argument('--output', 
                       help='Output file for metrics')
    
    args = parser.parse_args()
    
    if args.merge:
        # Merge metrics files
        metrics_files = [Path(f) for f in args.merge]
        output_file = Path(args.output) if args.output else Path('/tmp/merged_github_api_metrics.json')
        merged_data = merge_metrics(metrics_files, output_file)
        
        print("\n" + "="*80)
        print("Merged GitHub API Usage Report")
        print("="*80)
        print(f"Total Workflows: {len(merged_data['workflows'])}")
        print(f"Total API Calls: {merged_data['total_calls']}")
        print(f"Total Estimated Cost: {merged_data['total_cost']} requests")
        print("\nTop Call Types:")
        for call_type, count in sorted(
            merged_data['call_counts_aggregated'].items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:10]:
            print(f"  {call_type:30s} {count:5d}")
        print("="*80)
        
    elif args.command:
        # Run a command and track it using utils.github.APICounter
        with APICounter() as counter:
            result = counter.run_gh_command(args.command)
            print(result.stdout)
            if result.returncode != 0:
                print(result.stderr, file=sys.stderr)
                sys.exit(result.returncode)
    
    elif args.report:
        # Load and display existing metrics
        counter = APICounter()
        if counter.cache_hits + counter.cache_misses > 0:
            print(counter.report())
        else:
            print("No metrics found")
    
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
