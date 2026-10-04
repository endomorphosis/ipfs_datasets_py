#!/usr/bin/env python3
"""
Analyze GitHub Copilot Auto-Healing metrics and effectiveness.

This script analyzes auto-healing PRs to provide insights on:
- Success rate
- Common error types
- Fix confidence correlation
- Time to resolution
- Copilot implementation success
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any
import subprocess


def run_gh_command(command: List[str]) -> str:
    """Run GitHub CLI command and return output."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {e}", file=sys.stderr)
        return ""


def get_autohealing_prs() -> List[Dict[str, Any]]:
    """Get all auto-healing PRs from the repository."""
    command = [
        'gh', 'pr', 'list',
        '--label', 'auto-healing',
        '--state', 'all',
        '--limit', '1000',
        '--json', 'number,title,state,createdAt,closedAt,mergedAt,labels,author'
    ]
    
    output = run_gh_command(command)
    if not output:
        return []
    
    return json.loads(output)


def analyze_success_rate(prs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate success rate metrics."""
    total = len(prs)
    if total == 0:
        return {
            'total': 0,
            'merged': 0,
            'closed': 0,
            'open': 0,
            'success_rate': 0,
        }
    
    merged = sum(1 for pr in prs if pr['state'] == 'MERGED')
    closed = sum(1 for pr in prs if pr['state'] == 'CLOSED' and not pr.get('mergedAt'))
    open_prs = sum(1 for pr in prs if pr['state'] == 'OPEN')
    
    return {
        'total': total,
        'merged': merged,
        'closed': closed,
        'open': open_prs,
        'success_rate': (merged / total * 100) if total > 0 else 0,
    }


def analyze_time_to_resolution(prs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate average time to resolution."""
    resolved_times = []
    
    for pr in prs:
        if pr['state'] == 'MERGED' and pr.get('mergedAt'):
            created = datetime.fromisoformat(pr['createdAt'].replace('Z', '+00:00'))
            merged = datetime.fromisoformat(pr['mergedAt'].replace('Z', '+00:00'))
            duration = (merged - created).total_seconds() / 3600  # hours
            resolved_times.append(duration)
    
    if not resolved_times:
        return {
            'count': 0,
            'average_hours': 0,
            'median_hours': 0,
            'min_hours': 0,
            'max_hours': 0,
        }
    
    resolved_times.sort()
    return {
        'count': len(resolved_times),
        'average_hours': sum(resolved_times) / len(resolved_times),
        'median_hours': resolved_times[len(resolved_times) // 2],
        'min_hours': min(resolved_times),
        'max_hours': max(resolved_times),
    }


def analyze_error_types(prs: List[Dict[str, Any]]) -> Dict[str, int]:
    """Analyze common error types from PR titles."""
    error_types = {}
    
    for pr in prs:
        title = pr['title'].lower()
        
        # Extract error type from title pattern: "fix: Auto-fix [Error Type] in ..."
        if 'dependency' in title or 'package' in title:
            error_types['dependency'] = error_types.get('dependency', 0) + 1
        elif 'timeout' in title:
            error_types['timeout'] = error_types.get('timeout', 0) + 1
        elif 'permission' in title:
            error_types['permission'] = error_types.get('permission', 0) + 1
        elif 'docker' in title:
            error_types['docker'] = error_types.get('docker', 0) + 1
        elif 'network' in title:
            error_types['network'] = error_types.get('network', 0) + 1
        elif 'test' in title:
            error_types['test'] = error_types.get('test', 0) + 1
        elif 'syntax' in title:
            error_types['syntax'] = error_types.get('syntax', 0) + 1
        else:
            error_types['other'] = error_types.get('other', 0) + 1
    
    return error_types


def analyze_recent_activity(prs: List[Dict[str, Any]], days: int = 30) -> Dict[str, Any]:
    """Analyze auto-healing activity in recent days."""
    cutoff = datetime.now() - timedelta(days=days)
    recent_prs = [
        pr for pr in prs
        if datetime.fromisoformat(pr['createdAt'].replace('Z', '+00:00')) > cutoff
    ]
    
    return {
        'days': days,
        'total_prs': len(recent_prs),
        'merged': sum(1 for pr in recent_prs if pr['state'] == 'MERGED'),
        'open': sum(1 for pr in recent_prs if pr['state'] == 'OPEN'),
        'closed': sum(1 for pr in recent_prs if pr['state'] == 'CLOSED' and not pr.get('mergedAt')),
        'average_per_day': len(recent_prs) / days,
    }


def print_report(prs: List[Dict[str, Any]], days: int = 30):
    """Print comprehensive auto-healing report."""
    print("=" * 80)
    print(" GitHub Copilot Auto-Healing Metrics Report")
    print("=" * 80)
    print()
    
    # Success rate
    success = analyze_success_rate(prs)
    print("📊 Overall Success Rate")
    print("-" * 80)
    print(f"  Total PRs:        {success['total']}")
    print(f"  Merged:           {success['merged']} ({success['success_rate']:.1f}%)")
    print(f"  Closed:           {success['closed']}")
    print(f"  Open:             {success['open']}")
    print()
    
    # Time to resolution
    time_stats = analyze_time_to_resolution(prs)
    print("⏱️  Time to Resolution")
    print("-" * 80)
    print(f"  Resolved PRs:     {time_stats['count']}")
    print(f"  Average:          {time_stats['average_hours']:.1f} hours")
    print(f"  Median:           {time_stats['median_hours']:.1f} hours")
    print(f"  Fastest:          {time_stats['min_hours']:.1f} hours")
    print(f"  Slowest:          {time_stats['max_hours']:.1f} hours")
    print()
    
    # Error types
    error_types = analyze_error_types(prs)
    print("🔍 Error Types Distribution")
    print("-" * 80)
    for error_type, count in sorted(error_types.items(), key=lambda x: x[1], reverse=True):
        percentage = (count / len(prs) * 100) if prs else 0
        print(f"  {error_type.capitalize():20} {count:4} ({percentage:5.1f}%)")
    print()
    
    # Recent activity
    recent = analyze_recent_activity(prs, days)
    print(f"📈 Recent Activity (Last {days} days)")
    print("-" * 80)
    print(f"  Total PRs:        {recent['total_prs']}")
    print(f"  Merged:           {recent['merged']}")
    print(f"  Open:             {recent['open']}")
    print(f"  Closed:           {recent['closed']}")
    print(f"  Average per day:  {recent['average_per_day']:.2f}")
    print()
    
    # Recommendations
    print("💡 Recommendations")
    print("-" * 80)
    if success['success_rate'] < 50:
        print("  ⚠️  Low success rate. Consider:")
        print("     - Reviewing closed PRs for common issues")
        print("     - Adjusting confidence thresholds")
        print("     - Updating error patterns")
    elif success['success_rate'] > 80:
        print("  ✅ Excellent success rate! Auto-healing is working well.")
    else:
        print("  ✓ Good success rate. Keep monitoring and improving.")
    
    if time_stats['average_hours'] > 48:
        print("  ⚠️  Long resolution times. Consider:")
        print("     - Reviewing PR review process")
        print("     - Checking if Copilot is responding quickly")
    
    if recent['average_per_day'] > 5:
        print("  ⚠️  High PR creation rate. Consider:")
        print("     - Investigating root causes of failures")
        print("     - Improving workflow reliability")
    
    print()
    print("=" * 80)
    print()


def export_json(prs: List[Dict[str, Any]], output_file: str):
    """Export metrics to JSON file."""
    metrics = {
        'generated_at': datetime.now().isoformat(),
        'success_rate': analyze_success_rate(prs),
        'time_to_resolution': analyze_time_to_resolution(prs),
        'error_types': analyze_error_types(prs),
        'recent_activity_30d': analyze_recent_activity(prs, 30),
        'recent_activity_7d': analyze_recent_activity(prs, 7),
        'all_prs': prs,
    }
    
    with open(output_file, 'w') as f:
        json.dump(metrics, f, indent=2)
    
    print(f"✅ Metrics exported to: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description='Analyze GitHub Copilot Auto-Healing metrics'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=30,
        help='Number of days for recent activity analysis (default: 30)'
    )
    parser.add_argument(
        '--json',
        type=str,
        metavar='FILE',
        help='Export metrics to JSON file'
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress report output (useful with --json)'
    )
    
    args = parser.parse_args()
    
    print("🔍 Fetching auto-healing PRs...", file=sys.stderr)
    prs = get_autohealing_prs()
    
    if not prs:
        print("❌ No auto-healing PRs found.", file=sys.stderr)
        print("   Make sure you have the GitHub CLI (gh) installed and authenticated.", file=sys.stderr)
        return 1
    
    print(f"✅ Found {len(prs)} auto-healing PRs\n", file=sys.stderr)
    
    if not args.quiet:
        print_report(prs, args.days)
    
    if args.json:
        export_json(prs, args.json)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
