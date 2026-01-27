"""
Email Tools for MCP Server

This module provides tools for email ingestion, export, analysis,
and parsing via the Model Context Protocol (MCP) server.

Features:
- IMAP and POP3 server connections
- Email folder listing and export
- .eml file parsing
- Email analysis and statistics
- Search functionality
"""

from .email_connect import (
    email_test_connection,
    email_list_folders
)
from .email_export import (
    email_export_folder,
    email_parse_eml,
    email_fetch_emails
)
from .email_analyze import (
    email_analyze_export,
    email_search_export
)

__all__ = [
    # Connection tools
    'email_test_connection',
    'email_list_folders',
    
    # Export tools
    'email_export_folder',
    'email_parse_eml',
    'email_fetch_emails',
    
    # Analysis tools
    'email_analyze_export',
    'email_search_export',
]
