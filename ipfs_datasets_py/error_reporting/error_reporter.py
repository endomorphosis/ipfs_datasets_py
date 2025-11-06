#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Error Reporter Module

This module provides the core error reporting functionality that captures,
formats, and reports errors to GitHub issues.
"""

import os
import sys
import traceback
import hashlib
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from threading import Lock

from .github_issue_client import GitHubIssueClient

logger = logging.getLogger(__name__)


class ErrorReporter:
    """
    Central error reporter that captures errors and creates GitHub issues.
    
    Features:
    - Error deduplication based on error hash
    - Configurable via environment variables
    - Thread-safe operation
    - Support for multiple error sources (Python, JavaScript, Docker)
    """
    
    def __init__(
        self,
        enabled: Optional[bool] = None,
        repo: Optional[str] = None,
        github_token: Optional[str] = None,
        min_report_interval: int = 3600  # Don't report same error more than once per hour
    ):
        """
        Initialize error reporter.
        
        Args:
            enabled: Enable/disable error reporting. 
                    Defaults to ERROR_REPORTING_ENABLED env var.
            repo: GitHub repository for issues.
            github_token: GitHub authentication token.
            min_report_interval: Minimum seconds between reports of same error.
        """
        # Read configuration from environment
        if enabled is None:
            enabled = os.environ.get('ERROR_REPORTING_ENABLED', 'false').lower() in ('true', '1', 'yes')
        
        self.enabled = enabled
        self.min_report_interval = min_report_interval
        self._reported_errors = {}  # error_hash -> last_report_timestamp
        self._lock = Lock()
        
        # Initialize GitHub client
        self.github_client = GitHubIssueClient(repo=repo, github_token=github_token)
        
        # Log initialization status
        if self.enabled:
            if self.github_client.is_available():
                logger.info("Error reporting enabled and GitHub CLI is available")
            else:
                logger.warning("Error reporting enabled but GitHub CLI is not available")
        else:
            logger.debug("Error reporting is disabled")
    
    def _compute_error_hash(self, error_type: str, error_message: str, error_location: str) -> str:
        """
        Compute a hash for error deduplication.
        
        Args:
            error_type: Type/class of the error
            error_message: Error message
            error_location: Location where error occurred (file:line)
            
        Returns:
            MD5 hash string for deduplication
        """
        content = f"{error_type}|{error_message}|{error_location}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _should_report_error(self, error_hash: str) -> bool:
        """
        Check if error should be reported based on deduplication rules.
        
        Args:
            error_hash: Hash of the error
            
        Returns:
            True if error should be reported
        """
        with self._lock:
            now = datetime.now().timestamp()
            
            if error_hash not in self._reported_errors:
                self._reported_errors[error_hash] = now
                return True
            
            last_report = self._reported_errors[error_hash]
            if now - last_report >= self.min_report_interval:
                self._reported_errors[error_hash] = now
                return True
            
            return False
    
    def _format_error_title(self, error_type: str, error_message: str, source: str) -> str:
        """
        Format error title for GitHub issue.
        
        Args:
            error_type: Type/class of the error
            error_message: Error message
            source: Source of the error (python, javascript, docker)
            
        Returns:
            Formatted issue title
        """
        # Truncate long messages
        message = error_message[:100] + '...' if len(error_message) > 100 else error_message
        return f"[Runtime Error] {error_type}: {message} ({source})"
    
    def _format_error_body(self, error_data: Dict[str, Any]) -> str:
        """
        Format error body for GitHub issue.
        
        Args:
            error_data: Dictionary containing error details
            
        Returns:
            Formatted issue body in Markdown
        """
        body_parts = [
            "# Runtime Error Report",
            "",
            "An error was automatically detected and reported by the runtime error monitoring system.",
            "",
            "## Error Details",
            "",
            f"- **Type**: {error_data.get('error_type', 'Unknown')}",
            f"- **Message**: {error_data.get('error_message', 'No message')}",
            f"- **Source**: {error_data.get('source', 'Unknown')}",
            f"- **Timestamp**: {error_data.get('timestamp', 'Unknown')}",
        ]
        
        # Add location if available
        if error_data.get('error_location'):
            body_parts.append(f"- **Location**: {error_data['error_location']}")
        
        # Add context if available
        if error_data.get('context'):
            body_parts.extend([
                "",
                "## Context",
                "",
                f"```json",
                json.dumps(error_data['context'], indent=2),
                "```"
            ])
        
        # Add stack trace if available
        if error_data.get('stack_trace'):
            body_parts.extend([
                "",
                "## Stack Trace",
                "",
                "```",
                error_data['stack_trace'],
                "```"
            ])
        
        # Add environment info
        body_parts.extend([
            "",
            "## Environment",
            "",
            f"- **Python Version**: {sys.version.split()[0]}",
            f"- **Platform**: {sys.platform}",
        ])
        
        if error_data.get('hostname'):
            body_parts.append(f"- **Hostname**: {error_data['hostname']}")
        
        # Add reproduction info
        body_parts.extend([
            "",
            "## Auto-Generated Report",
            "",
            "This issue was automatically created by the runtime error monitoring system.",
            "Please review and address the error, or close this issue if it's a false positive.",
        ])
        
        return "\n".join(body_parts)
    
    def report_error(
        self,
        error_type: str,
        error_message: str,
        source: str = "python",
        error_location: Optional[str] = None,
        stack_trace: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Report an error and optionally create a GitHub issue.
        
        Args:
            error_type: Type/class of the error (e.g., 'TypeError', 'Error')
            error_message: Error message
            source: Source of the error ('python', 'javascript', 'docker')
            error_location: Location where error occurred (file:line)
            stack_trace: Full stack trace if available
            context: Additional context information
            
        Returns:
            Dictionary with report result
        """
        # Check if reporting is enabled
        if not self.enabled:
            return {
                'success': False,
                'error': 'Error reporting is disabled'
            }
        
        # Prepare error data
        error_data = {
            'error_type': error_type,
            'error_message': error_message,
            'source': source,
            'timestamp': datetime.now().isoformat(),
            'error_location': error_location,
            'stack_trace': stack_trace,
            'context': context or {},
            'hostname': os.environ.get('HOSTNAME', 'unknown')
        }
        
        # Compute error hash for deduplication
        error_hash = self._compute_error_hash(
            error_type,
            error_message,
            error_location or 'unknown'
        )
        
        # Check if we should report this error
        if not self._should_report_error(error_hash):
            logger.debug(f"Skipping duplicate error report: {error_hash}")
            return {
                'success': False,
                'error': 'Error already reported recently',
                'error_hash': error_hash
            }
        
        # Format issue title and body
        title = self._format_error_title(error_type, error_message, source)
        body = self._format_error_body(error_data)
        
        # Determine labels
        labels = ['runtime-error', f'source:{source}']
        if source == 'python':
            labels.append('bug')
        elif source == 'javascript':
            labels.append('frontend')
        elif source == 'docker':
            labels.append('infrastructure')
        
        # Create GitHub issue
        logger.info(f"Creating GitHub issue for error: {error_type}")
        result = self.github_client.create_issue(title, body, labels)
        
        if result['success']:
            logger.info(f"Created issue for error: {result.get('issue_url')}")
        else:
            logger.error(f"Failed to create issue: {result.get('error')}")
        
        return {
            **result,
            'error_hash': error_hash,
            'error_data': error_data
        }
    
    def report_exception(
        self,
        exception: Exception,
        source: str = "python",
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Report a Python exception.
        
        Args:
            exception: The exception to report
            source: Source identifier
            context: Additional context
            
        Returns:
            Dictionary with report result
        """
        error_type = type(exception).__name__
        error_message = str(exception)
        
        # Get stack trace
        stack_trace = ''.join(traceback.format_exception(
            type(exception),
            exception,
            exception.__traceback__
        ))
        
        # Try to extract location from traceback
        error_location = None
        tb = exception.__traceback__
        if tb:
            frame = tb.tb_frame
            error_location = f"{frame.f_code.co_filename}:{tb.tb_lineno}"
        
        return self.report_error(
            error_type=error_type,
            error_message=error_message,
            source=source,
            error_location=error_location,
            stack_trace=stack_trace,
            context=context
        )


# Global error reporter instance
_global_error_reporter: Optional[ErrorReporter] = None


def get_global_error_reporter() -> ErrorReporter:
    """
    Get or create the global error reporter instance.
    
    Returns:
        Global ErrorReporter instance
    """
    global _global_error_reporter
    if _global_error_reporter is None:
        _global_error_reporter = ErrorReporter()
    return _global_error_reporter
