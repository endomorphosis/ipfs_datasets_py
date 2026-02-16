#!/usr/bin/env python3
"""
Processor Monitoring Dashboard - View real-time processor health and performance metrics.

Usage:
    python processor_dashboard.py              # View current metrics
    python processor_dashboard.py --json       # JSON output
"""

import argparse
import json
import sys
from datetime import datetime

try:
    from ipfs_datasets_py.processors.infrastructure.monitoring import (
        get_processor_metrics,
        get_monitoring_summary,
        reset_processor_metrics
    )
except ImportError:
    print("Error: Could not import monitoring module")
    sys.exit(1)

def display_dashboard(summary):
    """Display monitoring dashboard."""
    print("\n" + "=" * 80)
    print("PROCESSOR MONITORING DASHBOARD")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total Processors: {summary['total_processors']}")
    print(f"Total Calls: {summary['total_calls']:,}")
    
    if summary['total_calls'] > 0:
        rate = summary['total_successes'] / summary['total_calls'] * 100
        print(f"Overall Success Rate: {rate:.1f}%")
    
    print("\nPROCESSOR DETAILS:")
    print("-" * 80)
    
    if not summary['processors']:
        print("No metrics available yet.")
    else:
        for name, metrics in sorted(summary['processors'].items()):
            print(f"\n{name}:")
            print(f"  Calls: {metrics['calls']}")
            print(f"  Success Rate: {metrics['success_rate']*100:.1f}%")
            print(f"  Avg Time: {metrics['avg_time']:.3f}s")
            if metrics['last_error']:
                print(f"  Last Error: {metrics['last_error'][:60]}...")
    
    print("=" * 80 + "\n")

def main():
    parser = argparse.ArgumentParser(description="Processor Monitoring Dashboard")
    parser.add_argument('--json', action='store_true', help='JSON output')
    parser.add_argument('--reset', action='store_true', help='Reset metrics')
    args = parser.parse_args()
    
    if args.reset:
        reset_processor_metrics()
        print("Metrics reset.")
        return
    
    summary = get_monitoring_summary()
    
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        display_dashboard(summary)

if __name__ == '__main__':
    main()
