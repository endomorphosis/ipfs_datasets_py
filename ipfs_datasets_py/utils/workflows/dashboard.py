"""Dashboard generation utilities for GitHub API usage metrics.

This module provides tools for generating dashboards and reports from
GitHub API usage metrics, consolidating functionality from .github/scripts.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class DashboardGenerator:
    """Generates dashboards and reports for GitHub API usage metrics.
    
    Loads metrics from JSON files, aggregates data, and generates reports
    in multiple formats (text, markdown, HTML).
    
    Example:
        >>> generator = DashboardGenerator(repo='owner/repo')
        >>> generator.load_all_metrics(metrics_dir=Path('/tmp'))
        >>> report = generator.generate_report(format='html')
        >>> generator.save_report(report, Path('dashboard.html'))
    """
    
    def __init__(self, repo: Optional[str] = None):
        """Initialize dashboard generator.
        
        Args:
            repo: Repository in format owner/repo (auto-detected if None)
        """
        import os
        self.repo = repo or os.getenv('GITHUB_REPOSITORY', 'unknown/repository')
        self.all_metrics: List[Dict[str, Any]] = []
    
    def load_metrics_from_file(self, metrics_file: Path) -> Optional[Dict[str, Any]]:
        """Load metrics from a JSON file.
        
        Args:
            metrics_file: Path to metrics JSON file
        
        Returns:
            Metrics dictionary or None if failed
        """
        try:
            with open(metrics_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load metrics from {metrics_file}: {e}")
            return None
    
    def load_all_metrics(
        self,
        metrics_dir: Path,
        pattern: str = 'github_api_metrics_*.json'
    ) -> int:
        """Load all metrics files matching pattern.
        
        Args:
            metrics_dir: Directory containing metrics files
            pattern: Glob pattern for metrics files
        
        Returns:
            Number of metrics files loaded
        """
        metrics_files = list(metrics_dir.glob(pattern))
        logger.info(f"Found {len(metrics_files)} metrics files")
        
        for metrics_file in metrics_files:
            data = self.load_metrics_from_file(metrics_file)
            if data:
                self.all_metrics.append(data)
        
        return len(self.all_metrics)
    
    def aggregate_metrics(self) -> Dict[str, Any]:
        """Aggregate metrics across all loaded files.
        
        Returns:
            Aggregated metrics dictionary with:
            - total_workflows: Number of workflows
            - total_calls: Total API calls
            - total_cost: Total estimated cost
            - call_counts: Breakdown by call type
            - by_workflow_name: Stats by workflow
            - workflows: List of workflow runs
        """
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
            total_calls = metrics.get('total_api_calls', metrics.get('total_calls', 0))
            estimated_cost = metrics.get('total_cost', 0)
            
            aggregated['total_calls'] += total_calls
            aggregated['total_cost'] += estimated_cost
            
            # Aggregate by call type
            for call_type, count in metrics.get('calls_by_type', metrics.get('call_counts', {})).items():
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
        """Generate a plain text report.
        
        Args:
            aggregated: Aggregated metrics from aggregate_metrics()
        
        Returns:
            Formatted text report
        """
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
        
        lines.append("="*80)
        return '\n'.join(lines)
    
    def generate_markdown_report(self, aggregated: Dict[str, Any]) -> str:
        """Generate a Markdown report.
        
        Args:
            aggregated: Aggregated metrics from aggregate_metrics()
        
        Returns:
            Formatted markdown report
        """
        lines = []
        lines.append("# GitHub API Usage Dashboard")
        lines.append("")
        lines.append(f"**Repository**: {self.repo}")
        lines.append(f"**Total Workflows Analyzed**: {aggregated['total_workflows']}")
        lines.append(f"**Total API Calls**: {aggregated['total_calls']}")
        lines.append(f"**Total Estimated Cost**: {aggregated['total_cost']} requests")
        lines.append("")
        
        # Rate limit status
        hourly_limit = 5000
        percentage = (aggregated['total_cost'] / hourly_limit) * 100 if hourly_limit > 0 else 0
        lines.append("## Rate Limit Status")
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
        suggestions = self._generate_suggestions(aggregated)
        for suggestion in suggestions:
            lines.append(suggestion)
        lines.append("")
        
        return '\n'.join(lines)
    
    def generate_html_report(self, aggregated: Dict[str, Any]) -> str:
        """Generate an HTML report.
        
        Args:
            aggregated: Aggregated metrics from aggregate_metrics()
        
        Returns:
            Formatted HTML report
        """
        hourly_limit = 5000
        percentage = (aggregated['total_cost'] / hourly_limit) * 100 if hourly_limit > 0 else 0
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>GitHub API Usage Dashboard</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background-color: #f5f5f5; }}
        h1, h2 {{ color: #333; }}
        table {{ width: 100%; border-collapse: collapse; background-color: white; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #4CAF50; color: white; }}
        .stats {{ display: flex; justify-content: space-around; margin: 20px 0; }}
        .stat-box {{ background-color: white; padding: 20px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center; }}
        .stat-value {{ font-size: 2em; font-weight: bold; color: #4CAF50; }}
        .stat-label {{ color: #666; margin-top: 10px; }}
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
    <p><strong>Usage:</strong> {percentage:.1f}% of {hourly_limit} requests/hour</p>
    
    <h2>Top Workflows by API Usage</h2>
    <table>
        <tr><th>Workflow</th><th>API Cost</th><th>Runs</th></tr>
"""
        
        workflows_sorted = sorted(
            aggregated['by_workflow_name'].items(),
            key=lambda x: x[1]['total_cost'],
            reverse=True
        )
        for workflow_name, stats in workflows_sorted[:10]:
            html += f"        <tr><td>{workflow_name}</td><td>{stats['total_cost']} requests</td><td>{stats['runs']}</td></tr>\n"
        
        html += """    </table>
    <h2>Top API Call Types</h2>
    <table>
        <tr><th>Call Type</th><th>Count</th></tr>
"""
        
        call_types_sorted = sorted(
            aggregated['call_counts'].items(),
            key=lambda x: x[1],
            reverse=True
        )
        for call_type, count in call_types_sorted[:15]:
            html += f"        <tr><td><code>{call_type}</code></td><td>{count}</td></tr>\n"
        
        html += """    </table>
</body>
</html>
"""
        return html
    
    def _generate_suggestions(self, aggregated: Dict[str, Any]) -> List[str]:
        """Generate optimization suggestions based on metrics.
        
        Args:
            aggregated: Aggregated metrics
        
        Returns:
            List of suggestion strings
        """
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
        
        if not suggestions:
            suggestions.append("- No major optimization opportunities detected")
        
        return suggestions
    
    def generate_report(
        self,
        format: str = 'text',
        aggregated: Optional[Dict[str, Any]] = None
    ) -> str:
        """Generate a report in the specified format.
        
        Args:
            format: Report format ('text', 'markdown'/'md', or 'html')
            aggregated: Pre-aggregated metrics (will aggregate if None)
        
        Returns:
            Formatted report string
        """
        if aggregated is None:
            aggregated = self.aggregate_metrics()
        
        if format in ('markdown', 'md'):
            return self.generate_markdown_report(aggregated)
        elif format == 'html':
            return self.generate_html_report(aggregated)
        else:
            return self.generate_text_report(aggregated)
    
    def save_report(self, report: str, output_file: Path, format: str = 'text'):
        """Save report to file.
        
        Args:
            report: Report content to save
            output_file: Path to output file
            format: Report format (for logging)
        """
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            f.write(report)
        
        logger.info(f"Saved {format} report to {output_file}")
