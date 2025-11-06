"""
GitHub issue creator for automatic error reporting.
"""
import hashlib
import json
import logging
import os
import platform
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    requests = None

from .config import ErrorReportingConfig


logger = logging.getLogger(__name__)


class GitHubIssueCreator:
    """Create GitHub issues from error reports."""
    
    def __init__(self, config: Optional[ErrorReportingConfig] = None):
        """
        Initialize GitHub issue creator.
        
        Args:
            config: Error reporting configuration. If None, uses default config.
        """
        self.config = config or ErrorReportingConfig()
        self.state = self._load_state()
    
    def _load_state(self) -> Dict[str, Any]:
        """Load state from file for deduplication tracking."""
        if self.config.state_file.exists():
            try:
                with open(self.config.state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load error reporting state: {e}")
        
        return {
            'reported_errors': {},
            'hourly_count': 0,
            'daily_count': 0,
            'last_hour_reset': datetime.now().isoformat(),
            'last_day_reset': datetime.now().isoformat(),
        }
    
    def _save_state(self):
        """Save state to file."""
        try:
            with open(self.config.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save error reporting state: {e}")
    
    def _reset_rate_limits(self):
        """Reset rate limit counters if time windows have elapsed."""
        now = datetime.now()
        
        # Check hourly reset
        try:
            last_hour_reset = datetime.fromisoformat(self.state['last_hour_reset'])
        except (ValueError, KeyError):
            # Invalid or missing timestamp, reset to now
            last_hour_reset = now
            self.state['last_hour_reset'] = now.isoformat()
        
        if (now - last_hour_reset) > timedelta(hours=1):
            self.state['hourly_count'] = 0
            self.state['last_hour_reset'] = now.isoformat()
        
        # Check daily reset
        try:
            last_day_reset = datetime.fromisoformat(self.state['last_day_reset'])
        except (ValueError, KeyError):
            # Invalid or missing timestamp, reset to now
            last_day_reset = now
            self.state['last_day_reset'] = now.isoformat()
        
        if (now - last_day_reset) > timedelta(days=1):
            self.state['daily_count'] = 0
            self.state['last_day_reset'] = now.isoformat()
    
    def _check_rate_limits(self) -> bool:
        """
        Check if rate limits allow creating a new issue.
        
        Returns:
            True if within rate limits, False otherwise.
        """
        self._reset_rate_limits()
        
        if self.state['hourly_count'] >= self.config.max_issues_per_hour:
            logger.warning(f"Hourly rate limit reached: {self.state['hourly_count']}/{self.config.max_issues_per_hour}")
            return False
        
        if self.state['daily_count'] >= self.config.max_issues_per_day:
            logger.warning(f"Daily rate limit reached: {self.state['daily_count']}/{self.config.max_issues_per_day}")
            return False
        
        return True
    
    def _get_error_signature(self, error: Exception, context: Dict[str, Any]) -> str:
        """
        Generate a unique signature for an error for deduplication.
        
        Args:
            error: The exception object
            context: Additional error context
            
        Returns:
            Hash signature of the error
        """
        # Create signature from error type, message, and first few stack frames
        sig_parts = [
            type(error).__name__,
            str(error),
        ]
        
        # Add first 3 stack frames (most relevant) to signature
        if 'stack_trace' in context:
            stack_lines = context['stack_trace'].split('\n')[:3]
            sig_parts.extend(stack_lines)
        
        signature = '\n'.join(sig_parts)
        return hashlib.sha256(signature.encode()).hexdigest()
    
    def _is_duplicate(self, signature: str) -> bool:
        """
        Check if error with this signature was recently reported.
        
        Args:
            signature: Error signature hash
            
        Returns:
            True if this is a duplicate error, False otherwise.
        """
        if signature not in self.state['reported_errors']:
            return False
        
        try:
            last_reported = datetime.fromisoformat(self.state['reported_errors'][signature])
        except (ValueError, TypeError):
            # Invalid timestamp, treat as not a duplicate
            return False
        
        now = datetime.now()
        
        # Check if within deduplication window
        hours_since_last = (now - last_reported).total_seconds() / 3600
        return hours_since_last < self.config.dedup_window_hours
    
    def _format_issue_title(self, error: Exception, context: Dict[str, Any]) -> str:
        """
        Format the issue title.
        
        Args:
            error: The exception object
            context: Additional error context
            
        Returns:
            Formatted issue title
        """
        error_type = type(error).__name__
        error_msg = str(error)[:100]  # Limit message length
        
        # Include source context if available
        source = context.get('source', 'Unknown')
        
        return f"[Auto-Report] {error_type} in {source}: {error_msg}"
    
    def _format_issue_body(self, error: Exception, context: Dict[str, Any]) -> str:
        """
        Format the issue body with full error details.
        
        Args:
            error: The exception object
            context: Additional error context
            
        Returns:
            Formatted issue body in markdown
        """
        lines = [
            "# Automatic Error Report",
            "",
            "This issue was automatically generated from a runtime error.",
            "",
            "## Error Details",
            "",
            f"**Type:** `{type(error).__name__}`",
            f"**Message:** {str(error)}",
            f"**Source:** {context.get('source', 'Unknown')}",
            f"**Timestamp:** {context.get('timestamp', datetime.now().isoformat())}",
            "",
        ]
        
        # Add stack trace if available and enabled
        if self.config.include_stack_trace and 'stack_trace' in context:
            lines.extend([
                "## Stack Trace",
                "",
                "```python",
                context['stack_trace'],
                "```",
                "",
            ])
        
        # Add environment information if enabled
        if self.config.include_environment and 'environment' in context:
            lines.extend([
                "## Environment",
                "",
                f"**Python Version:** {context['environment'].get('python_version', 'Unknown')}",
                f"**Platform:** {context['environment'].get('platform', 'Unknown')}",
                f"**OS:** {context['environment'].get('os', 'Unknown')}",
                "",
            ])
        
        # Add recent logs if available and enabled
        if self.config.include_logs and 'logs' in context:
            lines.extend([
                "## Recent Logs",
                "",
                "```",
                context['logs'],
                "```",
                "",
            ])
        
        # Add additional context
        if 'additional_info' in context:
            lines.extend([
                "## Additional Information",
                "",
                context['additional_info'],
                "",
            ])
        
        lines.extend([
            "---",
            "",
            "*This issue was automatically created by the error reporting system.*",
            "*Please review and triage appropriately.*",
        ])
        
        return '\n'.join(lines)
    
    def create_issue(
        self,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Create a GitHub issue from an error.
        
        Args:
            error: The exception to report
            context: Additional context about the error
            
        Returns:
            URL of created issue, or None if issue was not created
        """
        if not self.config.is_valid():
            logger.warning("Error reporting is disabled or not properly configured")
            return None
        
        if requests is None:
            logger.warning("requests library not available, cannot create GitHub issue")
            return None
        
        # Prepare context
        if context is None:
            context = {}
        
        # Add default context if not provided
        if 'timestamp' not in context:
            context['timestamp'] = datetime.now().isoformat()
        
        if 'stack_trace' not in context:
            context['stack_trace'] = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        
        if 'environment' not in context:
            context['environment'] = {
                'python_version': sys.version,
                'platform': platform.platform(),
                'os': os.name,
            }
        
        # Generate error signature
        signature = self._get_error_signature(error, context)
        
        # Check for duplicates
        if self._is_duplicate(signature):
            logger.info(f"Skipping duplicate error report (signature: {signature[:8]}...)")
            return None
        
        # Check rate limits
        if not self._check_rate_limits():
            logger.warning("Rate limit exceeded, skipping error report")
            return None
        
        # Format issue
        title = self._format_issue_title(error, context)
        body = self._format_issue_body(error, context)
        labels = context.get('labels', self.config.default_labels)
        
        # Create issue via GitHub API
        try:
            url = f"https://api.github.com/repos/{self.config.github_repo}/issues"
            headers = {
                'Authorization': f'token {self.config.github_token}',
                'Accept': 'application/vnd.github.v3+json',
            }
            data = {
                'title': title,
                'body': body,
                'labels': labels,
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            
            issue_data = response.json()
            issue_url = issue_data.get('html_url')
            
            # Update state
            self.state['reported_errors'][signature] = datetime.now().isoformat()
            self.state['hourly_count'] += 1
            self.state['daily_count'] += 1
            self._save_state()
            
            logger.info(f"Created GitHub issue for error: {issue_url}")
            return issue_url
            
        except Exception as e:
            logger.error(f"Failed to create GitHub issue: {e}")
            return None
