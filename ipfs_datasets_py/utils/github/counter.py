"""GitHub API call counter and metrics tracking.

This module provides call tracking and statistics for GitHub API usage,
consolidating functionality from .github/scripts/github_api_counter.py.
"""

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class APICallRecord:
    """Record of a GitHub API call.
    
    Attributes:
        call_type: Type of API call (gh_pr_list, gh_issue_create, etc.)
        count: Number of calls
        timestamp: When the call was made
        metadata: Additional call metadata
        cached: Whether this call was served from cache
    """
    call_type: str
    count: int
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    cached: bool = False


class APICounter:
    """GitHub API call counter with metrics tracking.
    
    Tracks all GitHub API calls, cache effectiveness, and exports metrics
    for monitoring. Used by workflows and optimizers to monitor API usage.
    
    Example:
        >>> counter = APICounter()
        >>> counter.count_call("gh_pr_list", 1)
        >>> counter.count_call("gh_issue_view", 5, cached=True)
        >>> print(counter.report())
        >>> counter.save_metrics()
    """
    
    def __init__(self):
        """Initialize API counter."""
        self.call_counts: Dict[str, int] = {}
        self.call_records: List[APICallRecord] = []
        self.cache_hits: int = 0
        self.cache_misses: int = 0
        
        # Workflow context
        self.workflow_run_id = os.getenv('GITHUB_RUN_ID', 'unknown')
        self.workflow_name = os.getenv('GITHUB_WORKFLOW', 'unknown')
        self.start_time = datetime.now()
    
    def count_call(
        self,
        call_type: str,
        count: int = 1,
        cached: bool = False,
        **metadata
    ) -> None:
        """Count an API call.
        
        Args:
            call_type: Type of API call (e.g., "gh_pr_list", "gh_issue_view")
            count: Number of calls (default: 1)
            cached: Whether call was served from cache
            **metadata: Additional metadata to store
        """
        # Update counts
        self.call_counts[call_type] = self.call_counts.get(call_type, 0) + count
        
        # Update cache stats
        if cached:
            self.cache_hits += count
        else:
            self.cache_misses += count
        
        # Record the call
        record = APICallRecord(
            call_type=call_type,
            count=count,
            timestamp=datetime.now(),
            metadata=metadata,
            cached=cached
        )
        self.call_records.append(record)
        
        logger.debug(f"API call: {call_type} (count={count}, cached={cached})")
    
    def run_gh_command(
        self,
        command: List[str],
        timeout: int = 30,
        check: bool = True
    ) -> subprocess.CompletedProcess:
        """Run a gh CLI command and track the call.
        
        Args:
            command: Command arguments (e.g., ['gh', 'pr', 'list'])
            timeout: Command timeout in seconds
            check: Whether to raise on error
            
        Returns:
            CompletedProcess result
        """
        # Extract call type from command
        if len(command) >= 2:
            call_type = f"gh_{command[1]}"
            if len(command) >= 3:
                call_type += f"_{command[2]}"
        else:
            call_type = "gh_command"
        
        # Run command
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=check
            )
            
            # Count the call
            self.count_call(call_type, cached=False)
            
            return result
            
        except subprocess.TimeoutExpired as e:
            logger.error(f"Command timed out: {' '.join(command)}")
            self.count_call(call_type, cached=False, error="timeout")
            raise
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {' '.join(command)}, error: {e}")
            self.count_call(call_type, cached=False, error=str(e))
            raise
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get API usage statistics.
        
        Returns:
            Dict with statistics including:
            - total_api_calls: Total API calls made
            - cache_hits: Number of cache hits
            - cache_misses: Number of cache misses
            - hit_rate: Cache hit rate (0.0 to 1.0)
            - calls_by_type: Breakdown by call type
            - duration_seconds: Time since counter started
        """
        total_calls = self.cache_hits + self.cache_misses
        duration = (datetime.now() - self.start_time).total_seconds()
        
        return {
            'total_api_calls': total_calls,
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'hit_rate': self.cache_hits / total_calls if total_calls > 0 else 0.0,
            'calls_by_type': dict(self.call_counts),
            'total_cost': total_calls,  # Each call = 1 cost unit
            'workflow_run_id': self.workflow_run_id,
            'workflow_name': self.workflow_name,
            'duration_seconds': duration,
        }
    
    def report(self) -> str:
        """Generate human-readable report.
        
        Returns:
            Formatted statistics report
        """
        stats = self.get_statistics()
        
        lines = [
            "=== GitHub API Usage Report ===",
            f"Workflow: {stats['workflow_name']} (Run ID: {stats['workflow_run_id']})",
            f"Duration: {stats['duration_seconds']:.1f}s",
            "",
            f"Total API Calls: {stats['total_api_calls']}",
            f"Cache Hits: {stats['cache_hits']}",
            f"Cache Misses: {stats['cache_misses']}",
            f"Hit Rate: {stats['hit_rate']:.2%}",
            "",
            "Calls by Type:",
        ]
        
        for call_type, count in sorted(
            stats['calls_by_type'].items(),
            key=lambda x: x[1],
            reverse=True
        ):
            lines.append(f"  {call_type}: {count}")
        
        return "\n".join(lines)
    
    def save_metrics(self, file_path: Optional[Path] = None) -> Path:
        """Save metrics to JSON file.
        
        Args:
            file_path: Where to save metrics (uses $RUNNER_TEMP if None)
            
        Returns:
            Path to saved metrics file
        """
        if file_path is None:
            runner_temp = os.getenv('RUNNER_TEMP', '/tmp')
            run_id = self.workflow_run_id
            file_path = Path(runner_temp) / f"github_api_metrics_{run_id}.json"
        
        stats = self.get_statistics()
        
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w') as f:
                json.dump(stats, f, indent=2)
            
            logger.info(f"Saved metrics to {file_path}")
            return file_path
            
        except Exception as e:
            logger.error(f"Failed to save metrics: {e}")
            raise
    
    def reset(self) -> None:
        """Reset all counters and records."""
        self.call_counts.clear()
        self.call_records.clear()
        self.cache_hits = 0
        self.cache_misses = 0
        self.start_time = datetime.now()
        logger.info("Reset API counter")
    
    def run_command_with_retry(
        self,
        command: List[str],
        max_retries: int = 3,
        backoff: float = 2.0,
        timeout: int = 60
    ) -> Tuple[bool, Optional[subprocess.CompletedProcess]]:
        """Run a GitHub CLI command with retry logic.
        
        Automatically retries on rate limit errors and other transient failures.
        
        Args:
            command: Command to run (e.g., ['gh', 'pr', 'list'])
            max_retries: Maximum number of retry attempts
            backoff: Backoff multiplier between retries (exponential)
            timeout: Timeout in seconds for each attempt
        
        Returns:
            Tuple of (success: bool, result: CompletedProcess or None)
        """
        for attempt in range(max_retries):
            try:
                result = self.run_gh_command(command, timeout=timeout, check=False)
                
                if result.returncode == 0:
                    return True, result
                
                # Check for rate limit errors
                if 'rate limit' in result.stderr.lower() or 'api rate limit' in result.stderr.lower():
                    logger.warning(f"⚠️  Rate limit hit on attempt {attempt + 1}/{max_retries}")
                    self.count_call('rate_limit_hit', 1, 
                                   command=' '.join(command), 
                                   attempt=attempt + 1)
                    
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
    
    def is_approaching_limit(self, limit: int = 5000, threshold: float = 0.8) -> bool:
        """Check if we're approaching the API rate limit.
        
        Args:
            limit: Rate limit per hour (default: 5000 for GitHub)
            threshold: Warning threshold as fraction (default: 0.8 = 80%)
        
        Returns:
            True if current API usage >= (limit * threshold)
        """
        total_calls = self.cache_hits + self.cache_misses
        return total_calls >= (limit * threshold)
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - save metrics automatically."""
        try:
            self.save_metrics()
        except Exception as e:
            logger.warning(f"Failed to save metrics on exit: {e}")
        return False


# Backward compatibility alias for optimizers and .github/scripts
GitHubAPICounter = APICounter
