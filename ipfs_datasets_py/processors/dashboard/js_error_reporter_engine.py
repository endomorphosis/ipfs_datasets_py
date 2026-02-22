"""JavaScript Error Reporter engine — canonical location.

Contains the JavaScriptErrorReporter class used by the MCP Dashboard
to receive JS errors, format reports, and create GitHub issues.

MCP tool wrapper lives in:
    ipfs_datasets_py/mcp_server/tools/dashboard_tools/js_error_reporter.py

Reusable by:
    - MCP server tools (mcp_server/tools/dashboard_tools/)
    - CLI commands
    - Direct Python imports
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


try:
    from ipfs_datasets_py.error_reporting.github_issue_client import GitHubIssueClient
except (ImportError, ModuleNotFoundError):
    GitHubIssueClient = None  # type: ignore[assignment]

try:
    from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.auto_healing_coordinator import (
        coordinate_auto_healing,
    )
except (ImportError, ModuleNotFoundError):
    coordinate_auto_healing = None  # type: ignore[assignment]


class JavaScriptErrorReporter:
    """Handles JavaScript errors from the dashboard and creates GitHub issues."""

    def __init__(self) -> None:
        """Initialize the JavaScript error reporter."""
        self.error_history: List[Dict[str, Any]] = []
        self.max_history = 100

    def format_error_report(
        self,
        error_data: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Format JavaScript error data into a structured report.

        Args:
            error_data: Raw error data from the dashboard
            session_id: Optional session identifier

        Returns:
            Formatted error report
        """
        errors = error_data.get("errors", [])
        reported_at = error_data.get("reportedAt", datetime.now().isoformat())

        report: Dict[str, Any] = {
            "source": "javascript_dashboard",
            "session_id": session_id or error_data.get("sessionId", "unknown"),
            "reported_at": reported_at,
            "error_count": len(errors),
            "errors": [],
        }

        for error in errors:
            formatted_error = {
                "type": error.get("type", "unknown"),
                "message": error.get("message", "No error message"),
                "timestamp": error.get("timestamp", reported_at),
                "url": error.get("url", "unknown"),
                "user_agent": error.get("userAgent", "unknown"),
                "stack": error.get("stack"),
                "filename": error.get("filename"),
                "lineno": error.get("lineno"),
                "colno": error.get("colno"),
                "console_history": error.get("consoleHistory", []),
                "action_history": error.get("actionHistory", []),
            }
            report["errors"].append(formatted_error)

        return report

    def create_github_issue_body(self, error_report: Dict[str, Any]) -> str:
        """Create a GitHub issue body from an error report.

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
            "",
        ]

        for idx, error in enumerate(error_report["errors"], 1):
            body_parts.extend(
                [
                    f"### Error {idx}: {error['type']}",
                    "",
                    f"**Message:** {error['message']}",
                    f"**Timestamp:** {error['timestamp']}",
                    f"**URL:** {error['url']}",
                    "",
                ]
            )
            if error.get("filename"):
                body_parts.append(
                    f"**File:** {error['filename']}:{error.get('lineno', '?')}:{error.get('colno', '?')}"
                )
                body_parts.append("")
            if error.get("stack"):
                body_parts.extend(
                    [
                        "**Stack Trace:**",
                        "```",
                        error["stack"][:1000],
                        "```",
                        "",
                    ]
                )
            console_history = error.get("console_history", [])
            if console_history:
                body_parts.extend(["**Console History (last 10 entries):**", "```"])
                for entry in console_history[-10:]:
                    level = entry.get("level", "log")
                    message = entry.get("message", "")[:200]
                    timestamp = entry.get("timestamp", "")
                    body_parts.append(f"[{level}] {timestamp}: {message}")
                body_parts.extend(["```", ""])
            action_history = error.get("action_history", [])
            if action_history:
                body_parts.extend(["**User Actions (last 10):**", "```"])
                for action in action_history[-10:]:
                    action_type = action.get("type", "unknown")
                    element = action.get("element", "")
                    action_id = action.get("id", "")
                    timestamp = action.get("timestamp", "")
                    body_parts.append(f"[{action_type}] {timestamp}: {element} {action_id}")
                body_parts.extend(["```", ""])
            if error.get("user_agent"):
                body_parts.extend([f"**User Agent:** `{error['user_agent']}`", ""])
            body_parts.extend(["---", ""])

        body_parts.extend(
            [
                "",
                "## Auto-Healing",
                "",
                "This issue was automatically created by the MCP Dashboard error reporting system.",
                "The auto-healing workflow will attempt to create a draft PR to fix this issue.",
                "",
                "**Labels:** `bug`, `javascript`, `dashboard`, `auto-healing`",
            ]
        )
        return "\n".join(body_parts)

    def process_error_report(
        self,
        error_data: Dict[str, Any],
        create_issue: bool = True,
    ) -> Dict[str, Any]:
        """Process a JavaScript error report and optionally create a GitHub issue.

        Args:
            error_data: Raw error data from the dashboard
            create_issue: Whether to create a GitHub issue

        Returns:
            Processing result with issue URL if created
        """
        try:
            error_report = self.format_error_report(error_data)
            self.error_history.append(error_report)
            if len(self.error_history) > self.max_history:
                self.error_history.pop(0)

            result: Dict[str, Any] = {
                "success": True,
                "report": error_report,
                "issue_created": False,
            }

            if create_issue:
                issue_result = self._create_github_issue(error_report)
                result["issue_created"] = issue_result.get("success", False)
                result["issue_url"] = issue_result.get("url")
                result["issue_number"] = issue_result.get("number")

            logger.info(f"Processed JavaScript error report: {error_report['error_count']} errors")
            return result

        except Exception as e:
            logger.error("Failed to process error report", exc_info=True)
            return {
                "success": False,
                "error": f"Failed to process error report: {type(e).__name__}",
            }

    def _create_github_issue(self, error_report: Dict[str, Any]) -> Dict[str, Any]:
        """Create a GitHub issue from an error report."""
        try:
            if GitHubIssueClient is None:
                raise ImportError("GitHubIssueClient not available")

            first_error = error_report["errors"][0] if error_report["errors"] else {}
            error_type = first_error.get("type", "unknown")
            error_message = first_error.get("message", "JavaScript error")[:80]
            title = f"[Dashboard JS Error] {error_type}: {error_message}"
            body = self.create_github_issue_body(error_report)

            client = GitHubIssueClient()
            if not client.is_available():
                logger.warning("GitHub CLI not available, cannot create issue")
                return {"success": False, "error": "GitHub CLI not available"}

            result = client.create_issue(
                title=title,
                body=body,
                labels=["bug", "javascript", "dashboard", "auto-healing"],
            )

            if result.get("success"):
                logger.info(f"Created GitHub issue: {result.get('url')}")
                self._trigger_auto_healing(result.get("number"))

            return result
        except Exception as e:
            logger.error(f"Failed to create GitHub issue: {e}")
            return {"success": False, "error": str(e)}

    def _trigger_auto_healing(self, issue_number: Optional[int]) -> None:
        """Trigger the auto-healing workflow for a created issue."""
        try:
            if not issue_number:
                return
            if coordinate_auto_healing is None:
                logger.warning("coordinate_auto_healing not available; skipping auto-healing")
                return
            healing_report = {
                "success": True,
                "patterns": [{"pattern": "javascript_error", "occurrences": 1, "severity": "high"}],
                "issue_number": issue_number,
            }
            healing_result = coordinate_auto_healing(error_report=healing_report, dry_run=False)
            logger.info(f"Auto-healing triggered for issue #{issue_number}: {healing_result}")
        except Exception as e:
            logger.error(f"Failed to trigger auto-healing: {e}")

    def get_error_statistics(self) -> Dict[str, Any]:
        """Get statistics about reported errors.

        Returns:
            Error statistics dict
        """
        total_errors = len(self.error_history)
        if total_errors == 0:
            return {"total_reports": 0, "total_errors": 0, "error_types": {}}

        error_types: Dict[str, int] = {}
        total_error_count = 0
        for report in self.error_history:
            total_error_count += report["error_count"]
            for error in report["errors"]:
                error_type = error["type"]
                error_types[error_type] = error_types.get(error_type, 0) + 1

        return {
            "total_reports": total_errors,
            "total_errors": total_error_count,
            "error_types": error_types,
            "last_report": self.error_history[-1]["reported_at"] if self.error_history else None,
        }


_js_error_reporter: Optional[JavaScriptErrorReporter] = None


def get_js_error_reporter() -> JavaScriptErrorReporter:
    """Get the global JavaScript error reporter instance."""
    global _js_error_reporter
    if _js_error_reporter is None:
        _js_error_reporter = JavaScriptErrorReporter()
    return _js_error_reporter
