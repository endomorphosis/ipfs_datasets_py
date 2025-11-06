#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Runtime Error Reporting System

This module provides automatic error reporting functionality that converts
runtime errors into GitHub issues for automated tracking and resolution.
"""

from .error_reporter import ErrorReporter, get_global_error_reporter
from .github_issue_client import GitHubIssueClient
from .error_handler import install_error_handlers, uninstall_error_handlers

__all__ = [
    'ErrorReporter',
    'get_global_error_reporter',
    'GitHubIssueClient',
    'install_error_handlers',
    'uninstall_error_handlers',
]
