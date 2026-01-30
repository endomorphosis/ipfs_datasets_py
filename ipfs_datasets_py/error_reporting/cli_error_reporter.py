#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI Error Reporter for IPFS Datasets

Captures errors from CLI tools and creates GitHub issues with stack traces and logs.
"""

import sys
import logging
import traceback
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class CLIErrorReporter:
    """
    Handles CLI errors and creates GitHub issues.
    """
    
    def __init__(self):
        """Initialize the CLI error reporter."""
        self.error_history = []
        self.max_history = 50
        
    def format_cli_error(
        self,
        error: Exception,
        command: str,
        args: list,
        logs: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Format CLI error data into a structured report.
        
        Args:
            error: Exception that occurred
            command: CLI command that was run
            args: Command line arguments
            logs: Optional log output
            context: Optional additional context
            
        Returns:
            Formatted error report
        """
        # Get stack trace
        stack_trace = ''.join(traceback.format_exception(
            type(error), error, error.__traceback__
        ))
        
        report = {
            'source': 'cli_tool',
            'command': command,
            'args': args,
            'error_type': type(error).__name__,
            'error_message': str(error),
            'stack_trace': stack_trace,
            'timestamp': datetime.utcnow().isoformat(),
            'python_version': sys.version,
            'platform': sys.platform,
            'cwd': str(Path.cwd()),
        }
        
        if logs:
            # Truncate logs if too long
            max_log_lines = 100
            log_lines = logs.splitlines()
            if len(log_lines) > max_log_lines:
                report['logs'] = '\n'.join(log_lines[-max_log_lines:])
                report['logs_truncated'] = True
            else:
                report['logs'] = logs
                report['logs_truncated'] = False
        
        if context:
            report['context'] = context
        
        return report
    
    def create_github_issue_body(self, error_report: Dict[str, Any]) -> str:
        """
        Create a GitHub issue body from a CLI error report.
        
        Args:
            error_report: Formatted error report
            
        Returns:
            Markdown-formatted issue body
        """
        body_parts = [
            "## CLI Tool Error Report",
            "",
            f"**Command:** `{error_report['command']}`",
            f"**Arguments:** `{' '.join(error_report['args'])}`",
            f"**Error Type:** `{error_report['error_type']}`",
            f"**Timestamp:** {error_report['timestamp']}",
            "",
            "---",
            "",
            "### Error Message",
            "",
            "```",
            error_report['error_message'],
            "```",
            "",
            "### Stack Trace",
            "",
            "```python",
            error_report['stack_trace'][:2000],  # Truncate to 2000 chars
            "```",
            ""
        ]
        
        # Add logs if available
        if 'logs' in error_report:
            body_parts.extend([
                "### Recent Logs",
                ""
            ])
            if error_report.get('logs_truncated'):
                body_parts.append("*(Showing last 100 lines)*")
                body_parts.append("")
            body_parts.extend([
                "```",
                error_report['logs'][:3000],  # Truncate to 3000 chars
                "```",
                ""
            ])
        
        # Add environment info
        body_parts.extend([
            "### Environment",
            "",
            f"**Python Version:** `{error_report['python_version']}`",
            f"**Platform:** `{error_report['platform']}`",
            f"**Working Directory:** `{error_report['cwd']}`",
            ""
        ])
        
        # Add context if available
        if 'context' in error_report:
            body_parts.extend([
                "### Additional Context",
                "",
                "```json",
                str(error_report['context'])[:1000],
                "```",
                ""
            ])
        
        # Add auto-healing note
        body_parts.extend([
            "---",
            "",
            "## Auto-Healing",
            "",
            "This issue was automatically created by the CLI error reporting system.",
            "The auto-healing workflow will attempt to create a draft PR to fix this issue.",
            "",
            "**Labels:** `bug`, `cli`, `auto-healing`"
        ])
        
        return "\n".join(body_parts)
    
    def report_cli_error(
        self,
        error: Exception,
        command: str,
        args: list,
        logs: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        create_issue: bool = True
    ) -> Dict[str, Any]:
        """
        Report a CLI error and optionally create a GitHub issue.
        
        Args:
            error: Exception that occurred
            command: CLI command that was run
            args: Command line arguments
            logs: Optional log output
            context: Optional additional context
            create_issue: Whether to create a GitHub issue
            
        Returns:
            Processing result
        """
        try:
            # Format the error report
            error_report = self.format_cli_error(error, command, args, logs, context)
            
            # Store in history
            self.error_history.append(error_report)
            if len(self.error_history) > self.max_history:
                self.error_history.pop(0)
            
            result = {
                'success': True,
                'report': error_report,
                'issue_created': False
            }
            
            if create_issue:
                # Create GitHub issue
                issue_result = self._create_github_issue(error_report)
                result['issue_created'] = issue_result.get('success', False)
                result['issue_url'] = issue_result.get('url')
                result['issue_number'] = issue_result.get('number')
            
            logger.info(f"Reported CLI error: {error_report['error_type']}")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to report CLI error: {e}", exc_info=True)
            return {
                'success': False,
                'error': f"Failed to report CLI error: {type(e).__name__}"
            }
    
    def _create_github_issue(self, error_report: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a GitHub issue from a CLI error report.
        
        Args:
            error_report: Formatted error report
            
        Returns:
            Issue creation result
        """
        try:
            # Import GitHub issue client
            from ipfs_datasets_py.error_reporting.github_issue_client import GitHubIssueClient
            
            # Create issue title
            error_type = error_report['error_type']
            command = error_report['command']
            error_msg = error_report['error_message'][:60]
            
            title = f"[CLI Error] {error_type} in '{command}': {error_msg}"
            
            # Create issue body
            body = self.create_github_issue_body(error_report)
            
            # Create issue with labels
            client = GitHubIssueClient()
            if not client.is_available():
                logger.warning("GitHub CLI not available, cannot create issue")
                return {
                    'success': False,
                    'error': 'GitHub CLI not available'
                }
            
            result = client.create_issue(
                title=title,
                body=body,
                labels=['bug', 'cli', 'auto-healing']
            )
            
            if result.get('success'):
                logger.info(f"Created GitHub issue: {result.get('url')}")
                
                # Trigger auto-healing workflow
                self._trigger_auto_healing(result.get('number'))
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to create GitHub issue: {e}")
            return {
                'success': False,
                'error': f"Failed to create GitHub issue: {type(e).__name__}"
            }
    
    def _trigger_auto_healing(self, issue_number: Optional[int]) -> None:
        """
        Trigger the auto-healing workflow for a created issue.
        
        Args:
            issue_number: GitHub issue number
        """
        try:
            if not issue_number:
                return
            
            # Import auto-healing coordinator
            from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.auto_healing_coordinator import (
                coordinate_auto_healing
            )
            
            # Create error report for auto-healing
            healing_report = {
                'success': True,
                'patterns': [{
                    'pattern': 'cli_error',
                    'occurrences': 1,
                    'severity': 'high'
                }],
                'issue_number': issue_number
            }
            
            # Coordinate auto-healing (in dry-run mode by default)
            healing_result = coordinate_auto_healing(
                error_report=healing_report,
                dry_run=False
            )
            
            logger.info(f"Auto-healing triggered for issue #{issue_number}: {healing_result}")
            
        except Exception as e:
            logger.error(f"Failed to trigger auto-healing: {e}")


# Global instance
_cli_error_reporter = None


def get_cli_error_reporter() -> CLIErrorReporter:
    """Get the global CLI error reporter instance."""
    global _cli_error_reporter
    if _cli_error_reporter is None:
        _cli_error_reporter = CLIErrorReporter()
    return _cli_error_reporter


def install_cli_error_handler():
    """
    Install a global exception handler for CLI errors.
    
    This should be called early in the CLI tool initialization.
    """
    original_excepthook = sys.excepthook
    
    def cli_excepthook(exc_type, exc_value, exc_traceback):
        # Call original hook first
        original_excepthook(exc_type, exc_value, exc_traceback)
        
        # Skip keyboard interrupt
        if issubclass(exc_type, KeyboardInterrupt):
            return
        
        # Report the error
        try:
            reporter = get_cli_error_reporter()
            
            # Get command and args
            command = Path(sys.argv[0]).name if sys.argv else 'unknown'
            args = sys.argv[1:] if len(sys.argv) > 1 else []
            
            # Create exception from the hook data
            exception = exc_value if isinstance(exc_value, Exception) else Exception(str(exc_value))
            if exc_traceback:
                exception = exception.with_traceback(exc_traceback)
            
            # Report the error
            reporter.report_cli_error(
                error=exception,
                command=command,
                args=args,
                context={
                    'uncaught': True,
                    'exception_type': exc_type.__name__
                }
            )
        except Exception as e:
            logger.error(f"Failed to report CLI error: {e}")
    
    sys.excepthook = cli_excepthook
    logger.info("CLI error handler installed")
