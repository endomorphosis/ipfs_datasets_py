#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JavaScript Error Reporter Tool for MCP Dashboard

This module provides functionality to receive JavaScript errors from the dashboard,
create GitHub issues, and trigger auto-healing workflows.
"""

import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


# Exposed for unit tests to patch/mocking.
try:
    from ipfs_datasets_py.error_reporting.github_issue_client import GitHubIssueClient
except Exception:  # pragma: no cover
    GitHubIssueClient = None  # type: ignore[assignment]


# Exposed for unit tests to patch/mocking.
try:
    from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.auto_healing_coordinator import (
        coordinate_auto_healing,
    )
except Exception:  # pragma: no cover
    coordinate_auto_healing = None  # type: ignore[assignment]


class JavaScriptErrorReporter:
    """
    Handles JavaScript errors from the dashboard and creates GitHub issues.
    """
    
    def __init__(self):
        """Initialize the JavaScript error reporter."""
        self.error_history = []
        self.max_history = 100
        
    def format_error_report(
        self,
        error_data: Dict[str, Any],
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Format JavaScript error data into a structured report.
        
        Args:
            error_data: Raw error data from the dashboard
            session_id: Optional session identifier
            
        Returns:
            Formatted error report
        """
        errors = error_data.get('errors', [])
        reported_at = error_data.get('reportedAt', datetime.utcnow().isoformat())
        
        report = {
            'source': 'javascript_dashboard',
            'session_id': session_id or error_data.get('sessionId', 'unknown'),
            'reported_at': reported_at,
            'error_count': len(errors),
            'errors': []
        }
        
        for error in errors:
            formatted_error = {
                'type': error.get('type', 'unknown'),
                'message': error.get('message', 'No error message'),
                'timestamp': error.get('timestamp', reported_at),
                'url': error.get('url', 'unknown'),
                'user_agent': error.get('userAgent', 'unknown'),
                'stack': error.get('stack'),
                'filename': error.get('filename'),
                'lineno': error.get('lineno'),
                'colno': error.get('colno'),
                'console_history': error.get('consoleHistory', []),
                'action_history': error.get('actionHistory', [])
            }
            report['errors'].append(formatted_error)
        
        return report
    
    def create_github_issue_body(self, error_report: Dict[str, Any]) -> str:
        """
        Create a GitHub issue body from an error report.
        
        Args:
            error_report: Formatted error report
            
        Returns:
            Markdown-formatted issue body
        """
        body_parts = [
            "## JavaScript Dashboard Error Report",
            "",
            f"**Session ID:** `{error_report['session_id']}`",
            f"**Reported At:** {error_report['reported_at']}",
            f"**Error Count:** {error_report['error_count']}",
            "",
            "---",
            ""
        ]
        
        for idx, error in enumerate(error_report['errors'], 1):
            body_parts.extend([
                f"### Error {idx}: {error['type']}",
                "",
                f"**Message:** {error['message']}",
                f"**Timestamp:** {error['timestamp']}",
                f"**URL:** {error['url']}",
                ""
            ])
            
            if error.get('filename'):
                body_parts.append(f"**File:** {error['filename']}:{error.get('lineno', '?')}:{error.get('colno', '?')}")
                body_parts.append("")
            
            if error.get('stack'):
                body_parts.extend([
                    "**Stack Trace:**",
                    "```",
                    error['stack'][:1000],  # Limit stack trace length
                    "```",
                    ""
                ])
            
            # Add recent console history
            console_history = error.get('console_history', [])
            if console_history:
                body_parts.extend([
                    "**Console History (last 10 entries):**",
                    "```"
                ])
                for entry in console_history[-10:]:
                    level = entry.get('level', 'log')
                    message = entry.get('message', '')[:200]  # Truncate long messages
                    timestamp = entry.get('timestamp', '')
                    body_parts.append(f"[{level}] {timestamp}: {message}")
                body_parts.extend([
                    "```",
                    ""
                ])
            
            # Add recent user actions
            action_history = error.get('action_history', [])
            if action_history:
                body_parts.extend([
                    "**User Actions (last 10):**",
                    "```"
                ])
                for action in action_history[-10:]:
                    action_type = action.get('type', 'unknown')
                    element = action.get('element', '')
                    action_id = action.get('id', '')
                    timestamp = action.get('timestamp', '')
                    body_parts.append(f"[{action_type}] {timestamp}: {element} {action_id}")
                body_parts.extend([
                    "```",
                    ""
                ])
            
            # User agent info
            if error.get('user_agent'):
                body_parts.extend([
                    f"**User Agent:** `{error['user_agent']}`",
                    ""
                ])
            
            body_parts.append("---")
            body_parts.append("")
        
        # Add auto-healing note
        body_parts.extend([
            "",
            "## Auto-Healing",
            "",
            "This issue was automatically created by the MCP Dashboard error reporting system.",
            "The auto-healing workflow will attempt to create a draft PR to fix this issue.",
            "",
            f"**Labels:** `bug`, `javascript`, `dashboard`, `auto-healing`"
        ])
        
        return "\n".join(body_parts)
    
    def process_error_report(
        self,
        error_data: Dict[str, Any],
        create_issue: bool = True
    ) -> Dict[str, Any]:
        """
        Process a JavaScript error report and optionally create a GitHub issue.
        
        Args:
            error_data: Raw error data from the dashboard
            create_issue: Whether to create a GitHub issue
            
        Returns:
            Processing result with issue URL if created
        """
        try:
            # Format the error report
            error_report = self.format_error_report(error_data)
            
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
            
            logger.info(f"Processed JavaScript error report: {error_report['error_count']} errors")
            
            return result
            
        except Exception as e:
            # Log full exception details server-side, but do not expose them to the client
            logger.error("Failed to process error report", exc_info=True)
            return {
                'success': False,
                'error': f"Failed to process error report: {type(e).__name__}"
            }
    
    def _create_github_issue(self, error_report: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a GitHub issue from an error report.
        
        Args:
            error_report: Formatted error report
            
        Returns:
            Issue creation result
        """
        try:
            if GitHubIssueClient is None:
                raise ImportError("GitHubIssueClient not available")
            
            # Create issue title
            first_error = error_report['errors'][0] if error_report['errors'] else {}
            error_type = first_error.get('type', 'unknown')
            error_message = first_error.get('message', 'JavaScript error')[:80]
            
            title = f"[Dashboard JS Error] {error_type}: {error_message}"
            
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
                labels=['bug', 'javascript', 'dashboard', 'auto-healing']
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
                'error': str(e)
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

            if coordinate_auto_healing is None:
                logger.warning("coordinate_auto_healing not available; skipping auto-healing")
                return
            
            # Create error report for auto-healing
            healing_report = {
                'success': True,
                'patterns': [{
                    'pattern': 'javascript_error',
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
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about reported errors.
        
        Returns:
            Error statistics
        """
        total_errors = len(self.error_history)
        if total_errors == 0:
            return {
                'total_reports': 0,
                'total_errors': 0,
                'error_types': {}
            }
        
        error_types = {}
        total_error_count = 0
        
        for report in self.error_history:
            total_error_count += report['error_count']
            for error in report['errors']:
                error_type = error['type']
                error_types[error_type] = error_types.get(error_type, 0) + 1
        
        return {
            'total_reports': total_errors,
            'total_errors': total_error_count,
            'error_types': error_types,
            'last_report': self.error_history[-1]['reported_at'] if self.error_history else None
        }


# Global instance
_js_error_reporter = None


def get_js_error_reporter() -> JavaScriptErrorReporter:
    """Get the global JavaScript error reporter instance."""
    global _js_error_reporter
    if _js_error_reporter is None:
        _js_error_reporter = JavaScriptErrorReporter()
    return _js_error_reporter


# Allow patching/consuming this module via either import path.
# Some tests import `mcp_server...` directly after adding `ipfs_datasets_py/` to sys.path,
# while others patch `ipfs_datasets_py.mcp_server...`.
_this_module = sys.modules.get(__name__)
if _this_module is not None:
    sys.modules.setdefault(
        'ipfs_datasets_py.mcp_server.tools.dashboard_tools.js_error_reporter',
        _this_module,
    )
