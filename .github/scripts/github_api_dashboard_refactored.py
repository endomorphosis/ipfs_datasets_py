#!/usr/bin/env python3
"""
GitHub API Usage Dashboard - Thin Wrapper

This is a thin wrapper around ipfs_datasets_py.utils.workflows.DashboardGenerator
that provides CLI functionality for generating GitHub API usage dashboards.

For core dashboard generation functionality, see: ipfs_datasets_py/utils/workflows/dashboard.py

Usage:
    # Generate text report
    python github_api_dashboard_refactored.py

    # Generate HTML dashboard
    python github_api_dashboard_refactored.py --format html --output dashboard.html
    
    # Generate markdown report
    python github_api_dashboard_refactored.py --format markdown --output report.md
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add repository root to path for imports
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Import from utils - this is the single source of truth
from ipfs_datasets_py.utils.workflows import DashboardGenerator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Generate GitHub API usage dashboard and reports',
        epilog='Core dashboard functionality provided by ipfs_datasets_py.utils.workflows.DashboardGenerator',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--format',
        choices=['text', 'markdown', 'md', 'html'],
        default='text',
        help='Report format (default: text)'
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Output file path (optional, prints to stdout if not specified)'
    )
    parser.add_argument(
        '--repo',
        type=str,
        help='Repository in format owner/repo (optional, auto-detected from env)'
    )
    parser.add_argument(
        '--metrics-dir',
        type=str,
        help='Directory containing metrics files (default: $RUNNER_TEMP or /tmp)'
    )
    
    args = parser.parse_args()
    
    # Use utils.workflows.DashboardGenerator for core functionality
    dashboard = DashboardGenerator(repo=args.repo)
    
    # Determine metrics directory
    if args.metrics_dir:
        metrics_dir = Path(args.metrics_dir)
    else:
        metrics_dir = Path(os.getenv('RUNNER_TEMP', '/tmp'))
    
    # Load metrics
    count = dashboard.load_all_metrics(metrics_dir)
    
    if count == 0:
        logger.warning("No metrics found to generate report")
        print("No metrics available")
        return 0
    
    # Aggregate metrics
    aggregated = dashboard.aggregate_metrics()
    
    # Generate report
    report = dashboard.generate_report(format=args.format, aggregated=aggregated)
    
    # Save or print
    if args.output:
        output_file = Path(args.output)
        dashboard.save_report(report, output_file, format=args.format)
    else:
        print(report)
    
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
