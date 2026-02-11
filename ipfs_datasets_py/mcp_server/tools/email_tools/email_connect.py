# ipfs_datasets_py/mcp_server/tools/email_tools/email_connect.py
"""
Email connection tools for the MCP server.

This module provides tools for connecting to IMAP and POP3 email servers
via the Model Context Protocol.

Uses anyio for asyncio/trio compatibility (libp2p integration)
"""
import anyio
import os
from typing import Dict, Any, Optional

import logging

logger = logging.getLogger(__name__)

# Import Email processor
try:
    from ipfs_datasets_py.data_transformation.multimedia.email_processor import create_email_processor
    EMAIL_AVAILABLE = True
except ImportError:
    EMAIL_AVAILABLE = False
    logger.warning("Email processor not available")


async def email_test_connection(
    protocol: str = 'imap',
    server: Optional[str] = None,
    port: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    use_ssl: bool = True,
    timeout: int = 30
) -> Dict[str, Any]:
    """
    Test connection to an email server.
    
    Args:
        protocol: Connection protocol - 'imap' or 'pop3'
        server: Mail server hostname (e.g., 'imap.gmail.com')
        port: Server port (defaults: IMAP=993, POP3=995)
        username: Account username/email. If not provided, uses EMAIL_USER env var.
        password: Account password. If not provided, uses EMAIL_PASS env var.
        use_ssl: Use SSL/TLS connection (default: True)
        timeout: Connection timeout in seconds (default: 30)
        
    Returns:
        Dict containing connection test results:
            - status: 'success' or 'error'
            - protocol: Protocol used
            - server: Server hostname
            - port: Port used
            - connected: Connection status
            - error: Error message if failed
    
    Example:
        >>> result = await email_test_connection(
        ...     protocol='imap',
        ...     server='imap.gmail.com',
        ...     username='user@gmail.com',
        ...     password='app_password'
        ... )
    
    Note:
        Credentials can be provided via:
        1. Direct parameters
        2. EMAIL_USER and EMAIL_PASS environment variables
    """
    try:
        if not EMAIL_AVAILABLE:
            return {
                "status": "error",
                "error": "Email processor not available. Ensure email_processor.py is installed.",
                "tool": "email_test_connection"
            }
        
        # Validate inputs
        if not server or not server.strip():
            return {
                "status": "error",
                "error": "server is required",
                "protocol": protocol
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
                "protocol": protocol,
                "server": server
            }
        
        # Create processor and test connection
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
        result = await processor.connect()
        
        # Disconnect
        await processor.disconnect()
        
        return result
        
    except Exception as e:
        logger.error(f"Email connection test failed: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "protocol": protocol,
            "server": server
        }


async def email_list_folders(
    server: Optional[str] = None,
    port: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    use_ssl: bool = True,
    timeout: int = 30
) -> Dict[str, Any]:
    """
    List all mailbox folders (IMAP only).
    
    Args:
        server: IMAP server hostname (e.g., 'imap.gmail.com')
        port: Server port (default: 993)
        username: Account username/email. If not provided, uses EMAIL_USER env var.
        password: Account password. If not provided, uses EMAIL_PASS env var.
        use_ssl: Use SSL/TLS connection (default: True)
        timeout: Connection timeout in seconds (default: 30)
        
    Returns:
        Dict containing folder list:
            - status: 'success' or 'error'
            - folder_count: Number of folders
            - folders: List of folder objects with name, delimiter, raw info
            - error: Error message if failed
    
    Example:
        >>> result = await email_list_folders(
        ...     server='imap.gmail.com',
        ...     username='user@gmail.com',
        ...     password='app_password'
        ... )
    """
    try:
        if not EMAIL_AVAILABLE:
            return {
                "status": "error",
                "error": "Email processor not available. Ensure email_processor.py is installed.",
                "tool": "email_list_folders"
            }
        
        # Validate inputs
        if not server or not server.strip():
            return {
                "status": "error",
                "error": "server is required"
            }
        
        # Use environment variables if credentials not provided
        username = username or os.environ.get('EMAIL_USER')
        password = password or os.environ.get('EMAIL_PASS')
        
        if not username or not password:
            return {
                "status": "error",
                "error": "username and password required. Set EMAIL_USER and EMAIL_PASS environment variables or provide directly.",
                "server": server
            }
        
        # Create processor
        processor = create_email_processor(
            protocol='imap',
            server=server,
            port=port,
            username=username,
            password=password,
            use_ssl=use_ssl,
            timeout=timeout
        )
        
        # Connect
        await processor.connect()
        
        # List folders
        result = await processor.list_folders()
        
        # Disconnect
        await processor.disconnect()
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to list email folders: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "server": server
        }
