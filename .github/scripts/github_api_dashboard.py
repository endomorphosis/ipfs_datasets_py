#!/usr/bin/env python3
"""
GitHub API Usage Dashboard

Generates a comprehensive report of GitHub API usage across workflows.
Can be run as a standalone script or imported as a module.

Usage:
    # Generate report for current workflow
    python github_api_dashboard.py --workflow-run-id $GITHUB_RUN_ID
    
    # Generate report for all recent workflows
    python github_api_dashboard.py --all-workflows --days 7
    
    # Generate HTML dashboard
    python github_api_dashboard.py --format html --output dashboard.html
"""

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GitHubAPIUsageDashboard:
    """Generate dashboards and reports for GitHub API usage."""
    
    def __init__(self, repo: Optional[str] = None):
        """
        Initialize the dashboard.
        
        Args:
            repo: Repository in format owner/repo
        """
        self.repo = repo or os.getenv('GITHUB_REPOSITORY', '')
        self.metrics_dir = Path(os.getenv('RUNNER_TEMP', '/tmp'))
        self.all_metrics: List[Dict[str, Any]] = []
    
    def load_metrics_from_file(self, metrics_file: Path) -> Optional[Dict[str, Any]]:
        """Load metrics from a JSON file."""
        try:
            with open(metrics_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load metrics from {metrics_file}: {e}")
            return None
    
    def load_all_metrics(self, pattern: str = 'github_api_metrics_*.json'):
        """Load all metrics files matching the pattern."""
        metrics_files = list(self.metrics_dir.glob(pattern))
        logger.info(f"Found {len(metrics_files)} metrics files")
        
        for metrics_file in metrics_files:
            data = self.load_metrics_from_file(metrics_file)
            if data:
                self.all_metrics.append(data)
        
        return len(self.all_metrics)
    
    def aggregate_metrics(self) -> Dict[str, Any]:
        """Aggregate metrics across all loaded files."""
        aggregated = {
            'total_workflows': len(self.all_metrics),
            'total_calls': 0,
            'total_cost': 0,
            'call_counts': defaultdict(int),
            'workflows': [],
            'by_workflow_name': defaultdict(lambda: {
                'runs': 0,
                'total_calls': 0,
                'total_cost': 0,
            }),
        }
        
        for metrics in self.all_metrics:
            workflow_name = metrics.get('workflow_name', 'unknown')
            run_id = metrics.get('workflow_run_id', 'unknown')
            total_calls = metrics.get('total_calls', 0)
            estimated_cost = metrics.get('estimated_cost', 0)
            
            aggregated['total_calls'] += total_calls
            aggregated['total_cost'] += estimated_cost
            
            # Aggregate by call type
            for call_type, count in metrics.get('call_counts', {}).items():
                aggregated['call_counts'][call_type] += count
            
            # Aggregate by workflow name
            aggregated['by_workflow_name'][workflow_name]['runs'] += 1
            aggregated['by_workflow_name'][workflow_name]['total_calls'] += total_calls
            aggregated['by_workflow_name'][workflow_name]['total_cost'] += estimated_cost
            
            # Add to workflows list
            aggregated['workflows'].append({
                'workflow_name': workflow_name,
                'run_id': run_id,
                'total_calls': total_calls,
                'estimated_cost': estimated_cost,
                'start_time': metrics.get('start_time'),
                'duration_seconds': metrics.get('duration_seconds'),
            })
        
        return aggregated
    
    def generate_text_report(self, aggregated: Dict[str, Any]) -> str:
        """Generate a text report."""
        lines = []
        lines.append("="*80)
        lines.append("GitHub API Usage Dashboard")
        lines.append("="*80)
        lines.append(f"Repository: {self.repo}")
        lines.append(f"Total Workflows Analyzed: {aggregated['total_workflows']}")
        lines.append(f"Total API Calls: {aggregated['total_calls']}")
        lines.append(f"Total Estimated Cost: {aggregated['total_cost']} requests")
        lines.append("")
        
        # Rate limit status
        hourly_limit = 5000
        percentage = (aggregated['total_cost'] / hourly_limit) * 100 if hourly_limit > 0 else 0
        lines.append(f"Rate Limit Status: {percentage:.1f}% of {hourly_limit} requests/hour")
        if percentage >= 80:
            lines.append("⚠️  WARNING: Approaching rate limit threshold!")
        elif percentage >= 50:
            lines.append("⚡ CAUTION: Over 50% of rate limit used")
        else:
            lines.append("✅ Usage within safe limits")
        lines.append("")
        
        # Top workflows by API usage
        lines.append("Top Workflows by API Usage:")
        lines.append("-"*80)
        workflows_sorted = sorted(
            aggregated['by_workflow_name'].items(),
            key=lambda x: x[1]['total_cost'],
            reverse=True
        )
        for workflow_name, stats in workflows_sorted[:10]:
            lines.append(f"  {workflow_name[:50]:50s} {stats['total_cost']:6d} requests ({stats['runs']:3d} runs)")
        lines.append("")
        
        # Top API call types
        lines.append("Top API Call Types:")
        lines.append("-"*80)
        call_types_sorted = sorted(
            aggregated['call_counts'].items(),
            key=lambda x: x[1],
            reverse=True
        )
        for call_type, count in call_types_sorted[:15]:
            lines.append(f"  {call_type[:50]:50s} {count:6d} calls")
        lines.append("")
        
        # Recent workflow runs
        lines.append("Recent Workflow Runs:")
        lines.append("-"*80)
        recent_workflows = sorted(
            aggregated['workflows'],
            key=lambda x: x.get('start_time', ''),
            reverse=True
        )[:10]
        for workflow in recent_workflows:
            name = workflow['workflow_name'][:40]
            calls = workflow['total_calls']
            cost = workflow['estimated_cost']
            run_id = workflow.get('run_id', 'unknown')
            lines.append(f"  {name:40s} {calls:4d} calls ({cost:4d} requests) - Run {run_id}")
        
        lines.append("="*80)
        return '\n'.join(lines)
    
    def generate_markdown_report(self, aggregated: Dict[str, Any]) -> str:
        """Generate a Markdown report."""
        lines = []
        lines.append("# GitHub API Usage Dashboard")
        lines.append("")
        lines.append(f"**Repository**: {self.repo}")
        lines.append("")
        lines.append(f"**Total Workflows Analyzed**: {aggregated['total_workflows']}")
        lines.append("")
        lines.append(f"**Total API Calls**: {aggregated['total_calls']}")
        lines.append("")
        lines.append(f"**Total Estimated Cost**: {aggregated['total_cost']} requests")
        lines.append("")
        
        # Rate limit status
        hourly_limit = 5000
        percentage = (aggregated['total_cost'] / hourly_limit) * 100 if hourly_limit > 0 else 0
        lines.append("## Rate Limit Status")
        lines.append("")
        lines.append(f"**Usage**: {percentage:.1f}% of {hourly_limit} requests/hour")
        lines.append("")
        if percentage >= 80:
            lines.append("⚠️ **WARNING**: Approaching rate limit threshold!")
        elif percentage >= 50:
            lines.append("⚡ **CAUTION**: Over 50% of rate limit used")
        else:
            lines.append("✅ Usage within safe limits")
        lines.append("")
        
        # Top workflows
        lines.append("## Top Workflows by API Usage")
        lines.append("")
        lines.append("| Workflow | API Cost | Runs |")
        lines.append("|----------|----------|------|")
        workflows_sorted = sorted(
            aggregated['by_workflow_name'].items(),
            key=lambda x: x[1]['total_cost'],
            reverse=True
        )
        for workflow_name, stats in workflows_sorted[:10]:
            lines.append(f"| {workflow_name} | {stats['total_cost']} requests | {stats['runs']} |")
        lines.append("")
        
        # Top API call types
        lines.append("## Top API Call Types")
        lines.append("")
        lines.append("| Call Type | Count |")
        lines.append("|-----------|-------|")
        call_types_sorted = sorted(
            aggregated['call_counts'].items(),
            key=lambda x: x[1],
            reverse=True
        )
        for call_type, count in call_types_sorted[:15]:
            lines.append(f"| `{call_type}` | {count} |")
        lines.append("")
        
        # Optimization suggestions
        lines.append("## Optimization Suggestions")
        lines.append("")
        
        # Check for common optimization opportunities
        suggestions = []
        
        # Check for excessive gh pr list calls
        pr_list_count = aggregated['call_counts'].get('gh_pr_list', 0)
        if pr_list_count > 50:
            suggestions.append(f"- Consider caching `gh pr list` results (currently {pr_list_count} calls)")
        
        # Check for excessive gh run view calls
        run_view_count = aggregated['call_counts'].get('gh_run_view', 0)
        if run_view_count > 100:
            suggestions.append(f"- Optimize `gh run view` calls with batch operations (currently {run_view_count} calls)")
        
        # Check for retry patterns
        retry_count = aggregated['call_counts'].get('rate_limit_hit', 0)
        if retry_count > 0:
            suggestions.append(f"- **Rate limit hits detected**: {retry_count} times. Implement exponential backoff.")
        
        if suggestions:
            for suggestion in suggestions:
                lines.append(suggestion)
        else:
            lines.append("- No major optimization opportunities detected")
        
        lines.append("")
        return '\n'.join(lines)
    
    def generate_html_report(self, aggregated: Dict[str, Any]) -> str:
        """Generate an HTML report."""
        # For simplicity, convert markdown to HTML-like structure
        md_report = self.generate_markdown_report(aggregated)
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>GitHub API Usage Dashboard</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        h1, h2 {{
            color: #333;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background-color: white;
            margin: 20px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #4CAF50;
            color: white;
        }}
        .warning {{
            background-color: #fff3cd;
            border: 1px solid #ffc107;
            padding: 15px;
            margin: 20px 0;
            border-radius: 5px;
        }}
        .success {{
            background-color: #d4edda;
            border: 1px solid #28a745;
            padding: 15px;
            margin: 20px 0;
            border-radius: 5px;
        }}
        .stats {{
            display: flex;
            justify-content: space-around;
            margin: 20px 0;
        }}
        .stat-box {{
            background-color: white;
            padding: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            text-align: center;
        }}
        .stat-value {{
            font-size: 2em;
            font-weight: bold;
            color: #4CAF50;
        }}
        .stat-label {{
            color: #666;
            margin-top: 10px;
        }}
    </style>
</head>
<body>
    <h1>GitHub API Usage Dashboard</h1>
    <p><strong>Repository:</strong> {self.repo}</p>
    
    <div class="stats">
        <div class="stat-box">
            <div class="stat-value">{aggregated['total_workflows']}</div>
            <div class="stat-label">Workflows Analyzed</div>
        </div>
        <div class="stat-box">
            <div class="stat-value">{aggregated['total_calls']}</div>
            <div class="stat-label">Total API Calls</div>
        </div>
        <div class="stat-box">
            <div class="stat-value">{aggregated['total_cost']}</div>
            <div class="stat-label">Estimated Cost (requests)</div>
        </div>
    </div>
    
    <h2>Rate Limit Status</h2>
    <p><strong>Usage:</strong> {(aggregated['total_cost'] / 5000) * 100:.1f}% of 5000 requests/hour</p>
    
    <h2>Top Workflows by API Usage</h2>
    <table>
        <tr>
            <th>Workflow</th>
            <th>API Cost</th>
            <th>Runs</th>
        </tr>
"""
        
        workflows_sorted = sorted(
            aggregated['by_workflow_name'].items(),
            key=lambda x: x[1]['total_cost'],
            reverse=True
        )
        for workflow_name, stats in workflows_sorted[:10]:
            html += f"""        <tr>
            <td>{workflow_name}</td>
            <td>{stats['total_cost']} requests</td>
            <td>{stats['runs']}</td>
        </tr>
"""
        
        html += """    </table>
    
    <h2>Top API Call Types</h2>
    <table>
        <tr>
            <th>Call Type</th>
            <th>Count</th>
        </tr>
"""
        
        call_types_sorted = sorted(
            aggregated['call_counts'].items(),
            key=lambda x: x[1],
            reverse=True
        )
        for call_type, count in call_types_sorted[:15]:
            html += f"""        <tr>
            <td><code>{call_type}</code></td>
            <td>{count}</td>
        </tr>
"""
        
        html += """    </table>
</body>
</html>
"""
        return html
    
    def save_report(self, report: str, output_file: Path, format: str = 'text'):
        """Save report to file."""
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            f.write(report)
        
        logger.info(f"Saved {format} report to {output_file}")
    
    def generate_and_save(
        self,
        format: str = 'text',
        output_file: Optional[Path] = None
    ) -> str:
        """Generate and optionally save a report."""
        # Load all metrics
        self.load_all_metrics()
        
        if not self.all_metrics:
            logger.warning("No metrics found to generate report")
            return "No metrics available"
        
        # Aggregate
        aggregated = self.aggregate_metrics()
        
        # Generate report
        if format == 'markdown' or format == 'md':
            report = self.generate_markdown_report(aggregated)
        elif format == 'html':
            report = self.generate_html_report(aggregated)
        else:
            report = self.generate_text_report(aggregated)
        
        # Save if output file specified
        if output_file:
            self.save_report(report, output_file, format)
        
        return report


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Generate GitHub API usage dashboard and reports',
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
    
    dashboard = GitHubAPIUsageDashboard(repo=args.repo)
    
    if args.metrics_dir:
        dashboard.metrics_dir = Path(args.metrics_dir)
    
    output_file = Path(args.output) if args.output else None
    
    report = dashboard.generate_and_save(
        format=args.format,
        output_file=output_file
    )
    
    # Print to stdout if no output file
    if not output_file:
        print(report)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
