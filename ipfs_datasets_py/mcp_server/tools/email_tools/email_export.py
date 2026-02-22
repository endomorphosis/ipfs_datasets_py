# ipfs_datasets_py/mcp_server/tools/email_tools/email_export.py
"""
Email export tools for the MCP server.

This module provides email export capabilities from IMAP/POP3 servers
and .eml file parsing via the MCP protocol.

Uses anyio for asyncio/trio compatibility (libp2p integration)
"""
import anyio
import os
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path

import logging

logger = logging.getLogger(__name__)

# Import Email processor
try:
    from ipfs_datasets_py.processors.multimedia.email_processor import create_email_processor
    EMAIL_AVAILABLE = True
except ImportError:
    EMAIL_AVAILABLE = False
    logger.warning("Email processor not available")


async def email_export_folder(
    folder: str = 'INBOX',
    output_path: Optional[str] = None,
    format: str = 'json',
    server: Optional[str] = None,
    port: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    protocol: str = 'imap',
    limit: Optional[int] = None,
    search_criteria: Optional[str] = None,
    use_ssl: bool = True,
    timeout: int = 30
) -> Dict[str, Any]:
    """
    Export emails from a mailbox folder to a file.
    
    Args:
        folder: Mailbox folder name (default: 'INBOX')
        output_path: Output file path (auto-generated if not provided)
        format: Export format - 'json', 'html', 'csv', or 'txt' (default: 'json')
        server: Mail server hostname (e.g., 'imap.gmail.com')
        port: Server port (defaults: IMAP=993, POP3=995)
        username: Account username/email. If not provided, uses EMAIL_USER env var.
        password: Account password. If not provided, uses EMAIL_PASS env var.
        protocol: Connection protocol - 'imap' or 'pop3' (default: 'imap')
        limit: Maximum number of emails to export
        search_criteria: IMAP search criteria (e.g., 'UNSEEN', 'FROM "sender@example.com"')
        use_ssl: Use SSL/TLS connection (default: True)
        timeout: Connection timeout in seconds (default: 30)
        
    Returns:
        Dict containing export results:
            - status: 'success' or 'error'
            - protocol: Protocol used
            - folder: Folder name
            - output_path: Path to exported file
            - format: Export format used
            - email_count: Number of emails exported
            - error: Error message if failed
    
    Example:
        >>> result = await email_export_folder(
        ...     folder='INBOX',
        ...     output_path='inbox_export.json',
        ...     server='imap.gmail.com',
        ...     format='json',
        ...     limit=100
        ... )
    
    Note:
        IMAP search criteria examples:
        - 'ALL' - All messages
        - 'UNSEEN' - Unread messages
        - 'FROM "sender@example.com"' - From specific sender
        - 'SUBJECT "urgent"' - Subject contains "urgent"
        - 'SINCE "01-Jan-2024"' - Since specific date
    """
    try:
        if not EMAIL_AVAILABLE:
            return {
                "status": "error",
                "error": "Email processor not available. Ensure email_processor.py is installed.",
                "tool": "email_export_folder"
            }
        
        # Validate inputs
        if not server or not server.strip():
            return {
                "status": "error",
                "error": "server is required",
                "folder": folder
            }
        
        if protocol not in ['imap', 'pop3']:
            return {
                "status": "error",
                "error": f"Protocol must be 'imap' or 'pop3', got '{protocol}'",
                "protocol": protocol
            }
        
        if format not in ['json', 'html', 'csv', 'txt']:
            return {
                "status": "error",
                "error": f"Format must be 'json', 'html', 'csv', or 'txt', got '{format}'",
                "format": format
            }
        
        # Use environment variables if credentials not provided
        username = username or os.environ.get('EMAIL_USER')
        password = password or os.environ.get('EMAIL_PASS')
        
        if not username or not password:
            return {
                "status": "error",
                "error": "username and password required. Set EMAIL_USER and EMAIL_PASS environment variables or provide directly.",
                "server": server,
                "folder": folder
            }
        
        # Auto-generate output path if not provided
        if not output_path:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = f"email_export_{folder}_{timestamp}.{format}"
        
        # Create processor
        processor = create_email_processor(
            protocol=protocol,
            server=server,
            port=port,
            username=username,
            password=password,
            use_ssl=use_ssl,
            timeout=timeout
        )
        
        # Connect
        await processor.connect()
        
        # Export folder
        result = await processor.export_folder(
            folder=folder,
            output_path=output_path,
            format=format,
            limit=limit,
            search_criteria=search_criteria
        )
        
        # Disconnect
        await processor.disconnect()
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to export email folder: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "folder": folder,
            "server": server
        }


async def email_parse_eml(
    file_path: str,
    include_attachments: bool = True
) -> Dict[str, Any]:
    """
    Parse an .eml file and extract email data.
    
    Args:
        file_path: Path to .eml file
        include_attachments: Whether to extract attachment metadata (default: True)
        
    Returns:
        Dict containing parsed email data:
            - status: 'success' or 'error'
            - protocol: 'eml'
            - file_path: Path to parsed file
            - email: Parsed email data with subject, from, to, body, attachments, etc.
            - error: Error message if failed
    
    Example:
        >>> result = await email_parse_eml(
        ...     file_path='message.eml',
        ...     include_attachments=True
        ... )
    
    Note:
        Parsed email data includes:
        - subject: Email subject
        - from: Sender address
        - to: Recipient address(es)
        - cc: CC recipient(s)
        - date: Email date (ISO format)
        - body_text: Plain text body
        - body_html: HTML body
        - attachments: List of attachment metadata
        - headers: Full email headers
        - message_id_header: Message-ID header
        - in_reply_to: In-Reply-To header (for threading)
        - references: References header (for threading)
    """
    try:
        if not EMAIL_AVAILABLE:
            return {
                "status": "error",
                "error": "Email processor not available. Ensure email_processor.py is installed.",
                "tool": "email_parse_eml"
            }
        
        # Validate inputs
        if not file_path or not file_path.strip():
            return {
                "status": "error",
                "error": "file_path is required"
            }
        
        # Check if file exists
        file_obj = Path(file_path)
        if not file_obj.exists():
            return {
                "status": "error",
                "error": f"File not found: {file_path}",
                "file_path": file_path
            }
        
        if not file_obj.is_file():
            return {
                "status": "error",
                "error": f"Path is not a file: {file_path}",
                "file_path": file_path
            }
        
        # Create processor
        processor = create_email_processor(protocol='eml')
        
        # Parse .eml file
        result = await processor.parse_eml_file(
            file_path=file_path,
            include_attachments=include_attachments
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to parse .eml file: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "file_path": file_path
        }


async def email_fetch_emails(
    folder: str = 'INBOX',
    server: Optional[str] = None,
    port: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    protocol: str = 'imap',
    limit: Optional[int] = None,
    search_criteria: Optional[str] = None,
    include_attachments: bool = True,
    use_ssl: bool = True,
    timeout: int = 30
) -> Dict[str, Any]:
    """
    Fetch emails from a mailbox folder (returns data, does not save to file).
    
    Args:
        folder: Mailbox folder name (default: 'INBOX', ignored for POP3)
        server: Mail server hostname (e.g., 'imap.gmail.com')
        port: Server port (defaults: IMAP=993, POP3=995)
        username: Account username/email. If not provided, uses EMAIL_USER env var.
        password: Account password. If not provided, uses EMAIL_PASS env var.
        protocol: Connection protocol - 'imap' or 'pop3' (default: 'imap')
        limit: Maximum number of emails to fetch
        search_criteria: IMAP search criteria (e.g., 'UNSEEN', 'FROM "sender@example.com"')
        include_attachments: Whether to extract attachment metadata (default: True)
        use_ssl: Use SSL/TLS connection (default: True)
        timeout: Connection timeout in seconds (default: 30)
        
    Returns:
        Dict containing fetched emails:
            - status: 'success' or 'error'
            - protocol: Protocol used
            - folder: Folder name (IMAP only)
            - email_count: Number of emails fetched
            - emails: List of email data objects
            - error: Error message if failed
    
    Example:
        >>> result = await email_fetch_emails(
        ...     folder='INBOX',
        ...     server='imap.gmail.com',
        ...     limit=10,
        ...     search_criteria='UNSEEN'
        ... )
    """
    try:
        if not EMAIL_AVAILABLE:
            return {
                "status": "error",
                "error": "Email processor not available. Ensure email_processor.py is installed.",
                "tool": "email_fetch_emails"
            }
        
        # Validate inputs
        if not server or not server.strip():
            return {
                "status": "error",
                "error": "server is required",
                "folder": folder
            }
        
        if protocol not in ['imap', 'pop3']:
            return {
                "status": "error",
                "error": f"Protocol must be 'imap' or 'pop3', got '{protocol}'",
                "protocol": protocol
            }
        
        # Use environment variables if credentials not provided
        username = username or os.environ.get('EMAIL_USER')
        password = password or os.environ.get('EMAIL_PASS')
        
        if not username or not password:
            return {
                "status": "error",
                "error": "username and password required. Set EMAIL_USER and EMAIL_PASS environment variables or provide directly.",
                "server": server,
                "folder": folder
            }
        
        # Create processor
        processor = create_email_processor(
            protocol=protocol,
            server=server,
            port=port,
            username=username,
            password=password,
            use_ssl=use_ssl,
            timeout=timeout
        )
        
        # Connect
        await processor.connect()
        
        # Fetch emails
        result = await processor.fetch_emails(
            folder=folder,
            limit=limit,
            search_criteria=search_criteria,
            include_attachments=include_attachments
        )
        
        # Disconnect
        await processor.disconnect()
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to fetch emails: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "folder": folder,
            "server": server
        }
