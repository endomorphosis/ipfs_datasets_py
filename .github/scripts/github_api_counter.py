#!/usr/bin/env python3
"""
GitHub API Call Counter

This module provides utilities to track and count GitHub API calls made during
GitHub Actions workflows. This helps ensure we stay under the rate limit of
5000 requests per hour and identify areas for optimization.

Usage:
    # As a wrapper for subprocess calls
    from github_api_counter import GitHubAPICounter
    
    counter = GitHubAPICounter()
    counter.run_gh_command(['gh', 'pr', 'list'])
    counter.save_metrics()
    
    # As a context manager
    with GitHubAPICounter() as counter:
        counter.run_gh_command(['gh', 'issue', 'create', '--title', 'Test'])
    
    # Direct counting
    counter = GitHubAPICounter()
    counter.count_api_call('gh_pr_list', 1)
    counter.report()
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GitHubAPICounter:
    """Tracks GitHub API calls made during workflow execution."""
    
    # GitHub API endpoints and their typical costs
    API_COSTS = {
        'gh_pr_list': 1,
        'gh_pr_view': 1,
        'gh_pr_create': 1,
        'gh_pr_comment': 1,
        'gh_pr_edit': 1,
        'gh_pr_close': 1,
        'gh_pr_merge': 1,
        'gh_issue_list': 1,
        'gh_issue_view': 1,
        'gh_issue_create': 1,
        'gh_issue_comment': 1,
        'gh_issue_edit': 1,
        'gh_issue_close': 1,
        'gh_run_list': 1,
        'gh_run_view': 1,
        'gh_run_download': 1,
        'gh_api': 1,  # Generic API call
        'gh_repo_view': 1,
        'gh_repo_list': 1,
        'gh_workflow_view': 1,
        'gh_workflow_run': 1,
        'gh_release_list': 1,
        'gh_release_view': 1,
        'gh_release_create': 1,
        'github_api_rest': 1,  # Direct REST API call
        'github_api_graphql': 1,  # GraphQL API call (usually counts multiple)
    }
    
    def __init__(self, metrics_file: Optional[str] = None):
        """
        Initialize the API counter.
        
        Args:
            metrics_file: Path to save metrics. Defaults to workflow temp directory.
        """
        self.call_counts: Dict[str, int] = {}
        self.call_timestamps: List[Dict[str, Any]] = []
        self.workflow_run_id = os.getenv('GITHUB_RUN_ID', 'local')
        self.workflow_name = os.getenv('GITHUB_WORKFLOW', 'unknown')
        self.start_time = datetime.now()
        
        # Determine metrics file location
        if metrics_file:
            self.metrics_file = Path(metrics_file)
        else:
            # Use GitHub Actions environment or temp directory
            runner_temp = os.getenv('RUNNER_TEMP', '/tmp')
            self.metrics_file = Path(runner_temp) / f'github_api_metrics_{self.workflow_run_id}.json'
        
        # Load existing metrics if available
        self._load_existing_metrics()
    
    def _load_existing_metrics(self):
        """Load existing metrics from file if available."""
        if self.metrics_file.exists():
            try:
                with open(self.metrics_file, 'r') as f:
                    data = json.load(f)
                    self.call_counts = data.get('call_counts', {})
                    self.call_timestamps = data.get('call_timestamps', [])
                    logger.info(f"Loaded existing metrics from {self.metrics_file}")
            except Exception as e:
                logger.warning(f"Could not load existing metrics: {e}")
    
    def _detect_command_type(self, command: List[str]) -> str:
        """
        Detect the type of GitHub command being run.
        
        Args:
            command: Command list
        
        Returns:
            Command type identifier
        """
        cmd_str = ' '.join(command)
        
        # GitHub CLI commands
        if 'gh pr list' in cmd_str:
            return 'gh_pr_list'
        elif 'gh pr view' in cmd_str:
            return 'gh_pr_view'
        elif 'gh pr create' in cmd_str:
            return 'gh_pr_create'
        elif 'gh pr comment' in cmd_str:
            return 'gh_pr_comment'
        elif 'gh pr edit' in cmd_str:
            return 'gh_pr_edit'
        elif 'gh pr close' in cmd_str:
            return 'gh_pr_close'
        elif 'gh pr merge' in cmd_str:
            return 'gh_pr_merge'
        elif 'gh issue list' in cmd_str:
            return 'gh_issue_list'
        elif 'gh issue view' in cmd_str:
            return 'gh_issue_view'
        elif 'gh issue create' in cmd_str:
            return 'gh_issue_create'
        elif 'gh issue comment' in cmd_str:
            return 'gh_issue_comment'
        elif 'gh issue edit' in cmd_str:
            return 'gh_issue_edit'
        elif 'gh issue close' in cmd_str:
            return 'gh_issue_close'
        elif 'gh run list' in cmd_str:
            return 'gh_run_list'
        elif 'gh run view' in cmd_str:
            return 'gh_run_view'
        elif 'gh run download' in cmd_str:
            return 'gh_run_download'
        elif 'gh api' in cmd_str:
            return 'gh_api'
        elif 'gh repo view' in cmd_str:
            return 'gh_repo_view'
        elif 'gh repo list' in cmd_str:
            return 'gh_repo_list'
        elif 'gh workflow view' in cmd_str:
            return 'gh_workflow_view'
        elif 'gh workflow run' in cmd_str:
            return 'gh_workflow_run'
        elif 'gh release list' in cmd_str:
            return 'gh_release_list'
        elif 'gh release view' in cmd_str:
            return 'gh_release_view'
        elif 'gh release create' in cmd_str:
            return 'gh_release_create'
        else:
            # Generic gh command
            return 'gh_api'
    
    def count_api_call(self, call_type: str, count: int = 1, metadata: Optional[Dict] = None):
        """
        Manually count an API call.
        
        Args:
            call_type: Type of API call
            count: Number of calls (default 1)
            metadata: Additional metadata about the call
        """
        self.call_counts[call_type] = self.call_counts.get(call_type, 0) + count
        
        # Record timestamp
        timestamp_record = {
            'type': call_type,
            'count': count,
            'timestamp': datetime.now().isoformat(),
            'metadata': metadata or {}
        }
        self.call_timestamps.append(timestamp_record)
        
        logger.debug(f"Counted {count} {call_type} call(s)")
    
    def run_gh_command(
        self,
        command: List[str],
        timeout: int = 60,
        check: bool = True,
        **kwargs
    ) -> subprocess.CompletedProcess:
        """
        Run a GitHub CLI command and count the API call.
        
        Args:
            command: Command to run
            timeout: Timeout in seconds
            check: Whether to raise on non-zero exit
            **kwargs: Additional arguments for subprocess.run
        
        Returns:
            CompletedProcess instance
        """
        # Detect command type and count it
        cmd_type = self._detect_command_type(command)
        self.count_api_call(cmd_type, 1, {'command': ' '.join(command)})
        
        # Run the command
        logger.info(f"Running GitHub command: {' '.join(command)}")
        result = subprocess.run(
            command,
            timeout=timeout,
            check=check,
            capture_output=True,
            text=True,
            **kwargs
        )
        
        return result
    
    def run_command_with_retry(
        self,
        command: List[str],
        max_retries: int = 3,
        backoff: float = 2.0,
        timeout: int = 60
    ) -> Tuple[bool, Optional[subprocess.CompletedProcess]]:
        """
        Run a GitHub CLI command with retry logic.
        
        Args:
            command: Command to run
            max_retries: Maximum number of retry attempts
            backoff: Backoff multiplier between retries
            timeout: Timeout in seconds
        
        Returns:
            Tuple of (success, result)
        """
        for attempt in range(max_retries):
            try:
                result = self.run_gh_command(command, timeout=timeout, check=False)
                
                if result.returncode == 0:
                    return True, result
                
                # Check for rate limit errors
                if 'rate limit' in result.stderr.lower() or 'api rate limit' in result.stderr.lower():
                    logger.warning(f"⚠️  Rate limit hit on attempt {attempt + 1}/{max_retries}")
                    self.count_api_call('rate_limit_hit', 1, {
                        'command': ' '.join(command),
                        'attempt': attempt + 1
                    })
                    
                    if attempt < max_retries - 1:
                        wait_time = backoff ** (attempt + 1)
                        logger.info(f"Waiting {wait_time}s before retry...")
                        time.sleep(wait_time)
                    continue
                
                # Other errors
                logger.error(f"Command failed with exit code {result.returncode}: {result.stderr}")
                if attempt < max_retries - 1:
                    wait_time = backoff ** attempt
                    logger.info(f"Retrying in {wait_time}s (attempt {attempt + 2}/{max_retries})...")
                    time.sleep(wait_time)
                else:
                    return False, result
                    
            except subprocess.TimeoutExpired:
                logger.error(f"Command timed out on attempt {attempt + 1}/{max_retries}")
                if attempt == max_retries - 1:
                    return False, None
                time.sleep(backoff ** attempt)
            except Exception as e:
                logger.error(f"Unexpected error on attempt {attempt + 1}/{max_retries}: {e}")
                if attempt == max_retries - 1:
                    return False, None
                time.sleep(backoff ** attempt)
        
        return False, None
    
    def get_total_calls(self) -> int:
        """Get total number of API calls made."""
        return sum(self.call_counts.values())
    
    def get_call_breakdown(self) -> Dict[str, int]:
        """Get breakdown of API calls by type."""
        return dict(self.call_counts)
    
    def get_estimated_cost(self) -> int:
        """
        Get estimated API call cost.
        
        Returns:
            Estimated number of API requests consumed
        """
        total_cost = 0
        for call_type, count in self.call_counts.items():
            cost_per_call = self.API_COSTS.get(call_type, 1)
            total_cost += cost_per_call * count
        return total_cost
    
    def is_approaching_limit(self, limit: int = 5000, threshold: float = 0.8) -> bool:
        """
        Check if we're approaching the rate limit.
        
        Args:
            limit: Rate limit (default 5000 per hour)
            threshold: Threshold percentage (default 0.8 = 80%)
        
        Returns:
            True if approaching limit
        """
        total_cost = self.get_estimated_cost()
        return total_cost >= (limit * threshold)
    
    def save_metrics(self, output_file: Optional[Path] = None):
        """
        Save metrics to JSON file.
        
        Args:
            output_file: Optional override for output file path
        """
        output_path = output_file or self.metrics_file
        
        metrics_data = {
            'workflow_run_id': self.workflow_run_id,
            'workflow_name': self.workflow_name,
            'start_time': self.start_time.isoformat(),
            'end_time': datetime.now().isoformat(),
            'duration_seconds': (datetime.now() - self.start_time).total_seconds(),
            'call_counts': self.call_counts,
            'call_timestamps': self.call_timestamps,
            'total_calls': self.get_total_calls(),
            'estimated_cost': self.get_estimated_cost(),
        }
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(metrics_data, f, indent=2)
        
        logger.info(f"Saved metrics to {output_path}")
        
        # Also save to GitHub Actions step summary if available
        github_step_summary = os.getenv('GITHUB_STEP_SUMMARY')
        if github_step_summary:
            self._append_to_step_summary(github_step_summary)
    
    def _append_to_step_summary(self, summary_file: str):
        """Append metrics to GitHub Actions step summary."""
        try:
            with open(summary_file, 'a') as f:
                f.write("\n\n## 📊 GitHub API Usage Metrics\n\n")
                f.write(f"**Workflow**: {self.workflow_name}\n\n")
                f.write(f"**Run ID**: {self.workflow_run_id}\n\n")
                f.write(f"**Total API Calls**: {self.get_total_calls()}\n\n")
                f.write(f"**Estimated Cost**: {self.get_estimated_cost()} requests\n\n")
                
                if self.is_approaching_limit():
                    f.write("⚠️ **WARNING**: Approaching rate limit threshold (80% of 5000/hour)\n\n")
                
                f.write("### Call Breakdown\n\n")
                f.write("| Call Type | Count |\n")
                f.write("|-----------|-------|\n")
                for call_type, count in sorted(self.call_counts.items(), key=lambda x: x[1], reverse=True):
                    f.write(f"| `{call_type}` | {count} |\n")
                
                f.write("\n")
            
            logger.info(f"Appended metrics to GitHub Step Summary")
        except Exception as e:
            logger.warning(f"Could not append to step summary: {e}")
    
    def report(self):
        """Print a summary report to stdout."""
        print("\n" + "="*80)
        print("GitHub API Usage Report")
        print("="*80)
        print(f"Workflow: {self.workflow_name}")
        print(f"Run ID: {self.workflow_run_id}")
        print(f"Duration: {(datetime.now() - self.start_time).total_seconds():.2f}s")
        print(f"\nTotal API Calls: {self.get_total_calls()}")
        print(f"Estimated Cost: {self.get_estimated_cost()} requests")
        
        if self.is_approaching_limit():
            print("\n⚠️  WARNING: Approaching rate limit threshold (80% of 5000/hour)")
        
        print("\nCall Breakdown:")
        print("-" * 80)
        for call_type, count in sorted(self.call_counts.items(), key=lambda x: x[1], reverse=True):
            cost = self.API_COSTS.get(call_type, 1) * count
            print(f"  {call_type:30s} {count:5d} calls  ({cost:5d} requests)")
        print("="*80 + "\n")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - auto-save metrics."""
        self.save_metrics()
        return False


def merge_metrics(metrics_files: List[Path], output_file: Path):
    """
    Merge multiple metrics files into a single report.
    
    Args:
        metrics_files: List of metrics files to merge
        output_file: Output file for merged metrics
    """
    merged_data = {
        'merged_at': datetime.now().isoformat(),
        'source_files': [str(f) for f in metrics_files],
        'workflows': [],
        'total_calls': 0,
        'total_cost': 0,
        'call_counts_aggregated': {},
    }
    
    for metrics_file in metrics_files:
        if not metrics_file.exists():
            continue
        
        try:
            with open(metrics_file, 'r') as f:
                data = json.load(f)
                merged_data['workflows'].append({
                    'workflow_name': data.get('workflow_name'),
                    'run_id': data.get('workflow_run_id'),
                    'total_calls': data.get('total_calls', 0),
                    'estimated_cost': data.get('estimated_cost', 0),
                })
                
                merged_data['total_calls'] += data.get('total_calls', 0)
                merged_data['total_cost'] += data.get('estimated_cost', 0)
                
                # Aggregate call counts
                for call_type, count in data.get('call_counts', {}).items():
                    merged_data['call_counts_aggregated'][call_type] = \
                        merged_data['call_counts_aggregated'].get(call_type, 0) + count
        except Exception as e:
            logger.warning(f"Could not load {metrics_file}: {e}")
    
    with open(output_file, 'w') as f:
        json.dump(merged_data, f, indent=2)
    
    logger.info(f"Merged {len(metrics_files)} metrics files into {output_file}")
    return merged_data


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='GitHub API Call Counter')
    parser.add_argument('--command', nargs='+', help='GitHub CLI command to run')
    parser.add_argument('--report', action='store_true', help='Show usage report')
    parser.add_argument('--merge', nargs='+', help='Merge multiple metrics files')
    parser.add_argument('--output', help='Output file for metrics')
    
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
        for call_type, count in sorted(merged_data['call_counts_aggregated'].items(), 
                                      key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {call_type:30s} {count:5d}")
        print("="*80)
        
    elif args.command:
        # Run a command and track it
        with GitHubAPICounter() as counter:
            result = counter.run_gh_command(args.command)
            print(result.stdout)
            if result.returncode != 0:
                print(result.stderr, file=sys.stderr)
                sys.exit(result.returncode)
    
    elif args.report:
        # Load and display existing metrics
        counter = GitHubAPICounter()
        if counter.get_total_calls() > 0:
            counter.report()
        else:
            print("No metrics found")
    
    else:
        parser.print_help()
