"""
Error reporting module for automatic GitHub issue creation.

This module provides automatic error reporting functionality that converts
runtime errors into GitHub issues with proper context and deduplication.
"""
from .error_handler import ErrorHandler, error_reporter
from .issue_creator import GitHubIssueCreator
from .config import ErrorReportingConfig

__all__ = [
    'ErrorHandler',
    'error_reporter',
    'GitHubIssueCreator',
    'ErrorReportingConfig',
]
