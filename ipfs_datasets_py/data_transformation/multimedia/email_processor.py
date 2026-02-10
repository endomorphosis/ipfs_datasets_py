"""
Email Processing and Ingestion Module

This module provides comprehensive email ingestion, parsing, and analysis capabilities
for IMAP, POP3, and .eml file sources.

Features:
- IMAP and POP3 server connection and authentication
- .eml file parsing
- Email metadata extraction (headers, date, sender, recipients, etc.)
- Attachment extraction and handling
- Email search and filtering
- Export to multiple formats (JSON, HTML, CSV)
- Thread and conversation tracking
- Secure credential management
- anyio support for asyncio/trio compatibility (libp2p integration)

Example:
    >>> # Connect to IMAP server
    >>> processor = EmailProcessor(
    ...     protocol='imap',
    ...     server='imap.gmail.com',
    ...     username='user@gmail.com',
    ...     password='app_password'
    ... )
    >>> # Export emails from inbox
    >>> result = await processor.export_folder(
    ...     folder='INBOX',
    ...     output_path='emails.json',
    ...     format='json'
    ... )
    >>> # Parse .eml file
    >>> result = await processor.parse_eml_file('message.eml')
"""

import anyio
import email
import email.policy
import imaplib
import json
import logging
import os
import poplib
import re
import ssl
from datetime import datetime
from email import message_from_bytes, message_from_string
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal, Tuple, Union
import base64

logger = logging.getLogger(__name__)


class EmailProcessor:
    """
    Email Processing and Ingestion
    
    Provides a unified interface for processing emails from IMAP servers, POP3 servers,
    and .eml files. Supports comprehensive metadata extraction, attachment handling,
    and export to multiple formats.
    
    Features:
    - Multi-protocol support (IMAP, POP3, .eml files)
    - Secure authentication (SSL/TLS)
    - Email search and filtering
    - Metadata extraction and parsing
    - Attachment extraction
    - Multiple export formats (JSON, HTML, CSV)
    - Thread tracking
    - Asynchronous operation support
    
    Args:
        protocol (str): Connection protocol - 'imap', 'pop3', or 'eml' for file parsing
        server (Optional[str]): Mail server hostname (required for IMAP/POP3)
        port (Optional[int]): Server port (defaults: IMAP=993, POP3=995)
        username (Optional[str]): Account username/email
        password (Optional[str]): Account password (can use env vars)
        use_ssl (bool): Use SSL/TLS connection (default: True)
        timeout (int): Connection timeout in seconds (default: 30)
        
    Attributes:
        protocol (str): Active protocol
        server (str): Mail server hostname
        connection: Active IMAP or POP3 connection
        connected (bool): Connection status
        
    Example:
        >>> # IMAP connection
        >>> processor = EmailProcessor(
        ...     protocol='imap',
        ...     server='imap.gmail.com',
        ...     username=os.getenv('EMAIL_USER'),
        ...     password=os.getenv('EMAIL_PASS')
        ... )
        >>> await processor.connect()
        >>> emails = await processor.fetch_emails(folder='INBOX', limit=10)
        >>> await processor.disconnect()
        
        >>> # Parse .eml file
        >>> processor = EmailProcessor(protocol='eml')
        >>> email_data = await processor.parse_eml_file('message.eml')
    """
    
    VALID_PROTOCOLS = ['imap', 'pop3', 'eml']
    VALID_EXPORT_FORMATS = ['json', 'html', 'csv', 'txt']
    
    DEFAULT_IMAP_PORT = 993
    DEFAULT_POP3_PORT = 995
    
    def __init__(
        self,
        protocol: Literal['imap', 'pop3', 'eml'] = 'imap',
        server: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_ssl: bool = True,
        timeout: int = 30,
    ):
        """Initialize email processor with connection parameters."""
        if protocol not in self.VALID_PROTOCOLS:
            raise ValueError(f"Protocol must be one of {self.VALID_PROTOCOLS}, got '{protocol}'")
        
        self.protocol = protocol
        self.server = server
        self.username = username or os.environ.get('EMAIL_USER')
        self.password = password or os.environ.get('EMAIL_PASS')
        self.use_ssl = use_ssl
        self.timeout = timeout
        
        # Set default ports
        if port is None:
            if protocol == 'imap':
                self.port = self.DEFAULT_IMAP_PORT
            elif protocol == 'pop3':
                self.port = self.DEFAULT_POP3_PORT
            else:
                self.port = None
        else:
            self.port = port
        
        self.connection = None
        self.connected = False
        
        # Validate server for non-eml protocols
        if protocol in ['imap', 'pop3'] and not server:
            raise ValueError(f"Server hostname required for {protocol.upper()} protocol")
    
    async def connect(self) -> Dict[str, Any]:
        """
        Connect to email server.
        
        Returns:
            Dict with connection status and details
            
        Raises:
            ValueError: If credentials are missing
            ConnectionError: If connection fails
        """
        if self.protocol == 'eml':
            return {
                'status': 'success',
                'message': 'EML protocol does not require connection',
                'protocol': 'eml'
            }
        
        if not self.username or not self.password:
            raise ValueError(f"Username and password required for {self.protocol.upper()} connection")
        
        try:
            if self.protocol == 'imap':
                await self._connect_imap()
            elif self.protocol == 'pop3':
                await self._connect_pop3()
            
            self.connected = True
            logger.info(f"Connected to {self.protocol.upper()} server: {self.server}")
            
            return {
                'status': 'success',
                'protocol': self.protocol,
                'server': self.server,
                'port': self.port,
                'username': self.username,
                'connected': True
            }
            
        except Exception as e:
            logger.error(f"Connection failed: {str(e)}")
            raise ConnectionError(f"Failed to connect to {self.protocol.upper()} server: {str(e)}")
    
    async def _connect_imap(self):
        """Connect to IMAP server."""
        def _do_connect():
            if self.use_ssl:
                conn = imaplib.IMAP4_SSL(self.server, self.port, timeout=self.timeout)
            else:
                conn = imaplib.IMAP4(self.server, self.port)
            
            conn.login(self.username, self.password)
            return conn
        
        # Run blocking IMAP operations in thread pool
        self.connection = await anyio.to_thread.run_sync(_do_connect)
    
    async def _connect_pop3(self):
        """Connect to POP3 server."""
        def _do_connect():
            if self.use_ssl:
                conn = poplib.POP3_SSL(self.server, self.port, timeout=self.timeout)
            else:
                conn = poplib.POP3(self.server, self.port, timeout=self.timeout)
            
            conn.user(self.username)
            conn.pass_(self.password)
            return conn
        
        # Run blocking POP3 operations in thread pool
        self.connection = await anyio.to_thread.run_sync(_do_connect)
    
    async def disconnect(self) -> Dict[str, Any]:
        """
        Disconnect from email server.
        
        Returns:
            Dict with disconnection status
        """
        if not self.connected or self.protocol == 'eml':
            return {
                'status': 'success',
                'message': 'Not connected or EML protocol',
                'connected': False
            }
        
        try:
            if self.protocol == 'imap' and self.connection:
                await anyio.to_thread.run_sync(self.connection.logout)
            elif self.protocol == 'pop3' and self.connection:
                await anyio.to_thread.run_sync(self.connection.quit)
            
            self.connection = None
            self.connected = False
            logger.info(f"Disconnected from {self.protocol.upper()} server")
            
            return {
                'status': 'success',
                'protocol': self.protocol,
                'connected': False
            }
            
        except Exception as e:
            logger.error(f"Disconnection error: {str(e)}")
            return {
                'status': 'error',
                'error': str(e),
                'connected': False
            }
    
    async def list_folders(self) -> Dict[str, Any]:
        """
        List all mailbox folders (IMAP only).
        
        Returns:
            Dict with list of folders and metadata
        """
        if self.protocol != 'imap':
            return {
                'status': 'error',
                'error': f'Folder listing only available for IMAP, current protocol: {self.protocol}'
            }
        
        if not self.connected:
            return {
                'status': 'error',
                'error': 'Not connected to server. Call connect() first.'
            }
        
        try:
            def _list_folders():
                status, folders = self.connection.list()
                if status != 'OK':
                    raise Exception(f"Failed to list folders: {status}")
                
                folder_list = []
                for folder in folders:
                    # Parse folder response (e.g., '(\\HasNoChildren) "/" "INBOX"')
                    folder_str = folder.decode() if isinstance(folder, bytes) else folder
                    match = re.search(r'\) "(.)" "?(.+?)"?$', folder_str)
                    if match:
                        delimiter = match.group(1)
                        name = match.group(2)
                        folder_list.append({
                            'name': name,
                            'delimiter': delimiter,
                            'raw': folder_str
                        })
                
                return folder_list
            
            folders = await anyio.to_thread.run_sync(_list_folders)
            
            return {
                'status': 'success',
                'protocol': self.protocol,
                'server': self.server,
                'folder_count': len(folders),
                'folders': folders
            }
            
        except Exception as e:
            logger.error(f"Failed to list folders: {str(e)}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    async def fetch_emails(
        self,
        folder: str = 'INBOX',
        limit: Optional[int] = None,
        search_criteria: Optional[str] = None,
        include_attachments: bool = True
    ) -> Dict[str, Any]:
        """
        Fetch emails from a folder.
        
        Args:
            folder: Mailbox folder name (IMAP) or None (POP3)
            limit: Maximum number of emails to fetch
            search_criteria: IMAP search criteria (e.g., 'UNSEEN', 'FROM "sender@example.com"')
            include_attachments: Whether to extract attachment metadata
            
        Returns:
            Dict with emails and metadata
        """
        if not self.connected and self.protocol != 'eml':
            return {
                'status': 'error',
                'error': 'Not connected to server. Call connect() first.'
            }
        
        try:
            if self.protocol == 'imap':
                return await self._fetch_imap(folder, limit, search_criteria, include_attachments)
            elif self.protocol == 'pop3':
                return await self._fetch_pop3(limit, include_attachments)
            else:
                return {
                    'status': 'error',
                    'error': 'EML protocol requires parse_eml_file() method'
                }
                
        except Exception as e:
            logger.error(f"Failed to fetch emails: {str(e)}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    async def _fetch_imap(
        self,
        folder: str,
        limit: Optional[int],
        search_criteria: Optional[str],
        include_attachments: bool
    ) -> Dict[str, Any]:
        """Fetch emails from IMAP server."""
        def _fetch():
            # Select folder
            status, count = self.connection.select(folder, readonly=True)
            if status != 'OK':
                raise Exception(f"Failed to select folder '{folder}': {status}")
            
            # Search for messages
            search_query = search_criteria or 'ALL'
            status, message_ids = self.connection.search(None, search_query)
            if status != 'OK':
                raise Exception(f"Search failed: {status}")
            
            ids = message_ids[0].split()
            
            # Apply limit
            if limit:
                ids = ids[-limit:]  # Get most recent emails
            
            emails = []
            for msg_id in ids:
                status, msg_data = self.connection.fetch(msg_id, '(RFC822)')
                if status == 'OK':
                    email_body = msg_data[0][1]
                    email_message = message_from_bytes(email_body, policy=email.policy.default)
                    parsed = self._parse_email_message(email_message, include_attachments)
                    parsed['message_id'] = msg_id.decode()
                    emails.append(parsed)
            
            return emails, len(ids)
        
        emails, total_count = await anyio.to_thread.run_sync(_fetch)
        
        return {
            'status': 'success',
            'protocol': self.protocol,
            'folder': folder,
            'email_count': len(emails),
            'total_matched': total_count,
            'emails': emails
        }
    
    async def _fetch_pop3(
        self,
        limit: Optional[int],
        include_attachments: bool
    ) -> Dict[str, Any]:
        """Fetch emails from POP3 server."""
        def _fetch():
            # Get message count
            num_messages = len(self.connection.list()[1])
            
            # Determine which messages to fetch
            start = max(1, num_messages - limit + 1) if limit else 1
            
            emails = []
            for i in range(start, num_messages + 1):
                resp, lines, octets = self.connection.retr(i)
                email_body = b'\n'.join(lines)
                email_message = message_from_bytes(email_body, policy=email.policy.default)
                parsed = self._parse_email_message(email_message, include_attachments)
                parsed['message_id'] = str(i)
                emails.append(parsed)
            
            return emails, num_messages
        
        emails, total_count = await anyio.to_thread.run_sync(_fetch)
        
        return {
            'status': 'success',
            'protocol': self.protocol,
            'email_count': len(emails),
            'total_messages': total_count,
            'emails': emails
        }
    
    def _parse_email_message(
        self,
        email_message: email.message.EmailMessage,
        include_attachments: bool = True
    ) -> Dict[str, Any]:
        """
        Parse email message and extract metadata.
        
        Args:
            email_message: Parsed email message object
            include_attachments: Whether to extract attachment metadata
            
        Returns:
            Dict with parsed email data
        """
        # Decode headers
        subject = self._decode_header(email_message.get('Subject', ''))
        from_addr = self._decode_header(email_message.get('From', ''))
        to_addr = self._decode_header(email_message.get('To', ''))
        cc_addr = self._decode_header(email_message.get('Cc', ''))
        date_str = email_message.get('Date', '')
        
        # Parse date
        email_date = None
        try:
            if date_str:
                email_date = parsedate_to_datetime(date_str)
        except Exception as e:
            logger.warning(f"Failed to parse date '{date_str}': {e}")
        
        # Extract body
        body_text = ''
        body_html = ''
        
        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                if content_type == 'text/plain':
                    try:
                        body_text += part.get_content()
                    except (UnicodeDecodeError, LookupError, AttributeError):
                        body_text += str(part.get_payload(decode=True), errors='ignore')
                elif content_type == 'text/html':
                    try:
                        body_html += part.get_content()
                    except (UnicodeDecodeError, LookupError, AttributeError):
                        body_html += str(part.get_payload(decode=True), errors='ignore')
        else:
            content_type = email_message.get_content_type()
            try:
                content = email_message.get_content()
            except (UnicodeDecodeError, LookupError, AttributeError):
                content = str(email_message.get_payload(decode=True), errors='ignore')
            
            if content_type == 'text/plain':
                body_text = content
            elif content_type == 'text/html':
                body_html = content
        
        # Extract attachments
        attachments = []
        if include_attachments:
            attachments = self._extract_attachments(email_message)
        
        return {
            'subject': subject,
            'from': from_addr,
            'to': to_addr,
            'cc': cc_addr,
            'date': email_date.isoformat() if email_date else None,
            'body_text': body_text,
            'body_html': body_html,
            'attachments': attachments,
            'headers': dict(email_message.items()),
            'message_id_header': email_message.get('Message-ID', ''),
            'in_reply_to': email_message.get('In-Reply-To', ''),
            'references': email_message.get('References', ''),
        }
    
    def _decode_header(self, header: str) -> str:
        """Decode email header handling various encodings."""
        if not header:
            return ''
        
        decoded_parts = []
        for part, encoding in decode_header(header):
            if isinstance(part, bytes):
                try:
                    decoded_parts.append(part.decode(encoding or 'utf-8'))
                except (UnicodeDecodeError, LookupError):
                    decoded_parts.append(part.decode('utf-8', errors='ignore'))
            else:
                decoded_parts.append(part)
        
        return ''.join(decoded_parts)
    
    def _extract_attachments(self, email_message: email.message.EmailMessage) -> List[Dict[str, Any]]:
        """Extract attachment metadata from email."""
        attachments = []
        
        for part in email_message.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            if part.get('Content-Disposition') is None:
                continue
            
            filename = part.get_filename()
            if filename:
                attachments.append({
                    'filename': self._decode_header(filename),
                    'content_type': part.get_content_type(),
                    'size': len(part.get_payload(decode=True) or b''),
                })
        
        return attachments
    
    async def parse_eml_file(self, file_path: str, include_attachments: bool = True) -> Dict[str, Any]:
        """
        Parse an .eml file.
        
        Args:
            file_path: Path to .eml file
            include_attachments: Whether to extract attachment metadata
            
        Returns:
            Dict with parsed email data
        """
        try:
            def _parse():
                with open(file_path, 'rb') as f:
                    email_message = message_from_bytes(f.read(), policy=email.policy.default)
                return self._parse_email_message(email_message, include_attachments)
            
            parsed = await anyio.to_thread.run_sync(_parse)
            
            return {
                'status': 'success',
                'protocol': 'eml',
                'file_path': file_path,
                'email': parsed
            }
            
        except Exception as e:
            logger.error(f"Failed to parse .eml file '{file_path}': {str(e)}")
            return {
                'status': 'error',
                'error': str(e),
                'file_path': file_path
            }
    
    async def export_folder(
        self,
        folder: str = 'INBOX',
        output_path: str = 'emails_export.json',
        format: Literal['json', 'html', 'csv', 'txt'] = 'json',
        limit: Optional[int] = None,
        search_criteria: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Export emails from a folder to a file.
        
        Args:
            folder: Mailbox folder name
            output_path: Output file path
            format: Export format ('json', 'html', 'csv', 'txt')
            limit: Maximum number of emails to export
            search_criteria: IMAP search criteria
            
        Returns:
            Dict with export results
        """
        # Fetch emails
        result = await self.fetch_emails(
            folder=folder,
            limit=limit,
            search_criteria=search_criteria,
            include_attachments=True
        )
        
        if result['status'] != 'success':
            return result
        
        emails = result['emails']
        
        # Export to file
        try:
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            if format == 'json':
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        'metadata': {
                            'folder': folder,
                            'export_date': datetime.now().isoformat(),
                            'email_count': len(emails),
                            'protocol': self.protocol,
                            'server': self.server
                        },
                        'emails': emails
                    }, f, indent=2, ensure_ascii=False)
            
            elif format == 'csv':
                import csv
                with open(output_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=['date', 'from', 'to', 'subject', 'body_text'])
                    writer.writeheader()
                    for email_data in emails:
                        writer.writerow({
                            'date': email_data['date'],
                            'from': email_data['from'],
                            'to': email_data['to'],
                            'subject': email_data['subject'],
                            'body_text': email_data['body_text'][:500]  # Truncate for CSV
                        })
            
            elif format == 'html':
                html_content = self._generate_html_export(emails, folder)
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(html_content)
            
            elif format == 'txt':
                with open(output_file, 'w', encoding='utf-8') as f:
                    for i, email_data in enumerate(emails, 1):
                        f.write(f"{'=' * 80}\n")
                        f.write(f"Email {i}/{len(emails)}\n")
                        f.write(f"{'=' * 80}\n")
                        f.write(f"Date: {email_data['date']}\n")
                        f.write(f"From: {email_data['from']}\n")
                        f.write(f"To: {email_data['to']}\n")
                        f.write(f"Subject: {email_data['subject']}\n")
                        f.write(f"\n{email_data['body_text']}\n\n")
            
            return {
                'status': 'success',
                'protocol': self.protocol,
                'folder': folder,
                'output_path': str(output_file),
                'format': format,
                'email_count': len(emails)
            }
            
        except Exception as e:
            logger.error(f"Failed to export emails: {str(e)}")
            return {
                'status': 'error',
                'error': str(e),
                'folder': folder
            }
    
    def _generate_html_export(self, emails: List[Dict[str, Any]], folder: str) -> str:
        """Generate HTML export of emails."""
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Email Export - {folder}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
        .email {{ background: white; margin: 20px 0; padding: 20px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .header {{ border-bottom: 1px solid #ddd; padding-bottom: 10px; margin-bottom: 10px; }}
        .subject {{ font-size: 18px; font-weight: bold; margin-bottom: 10px; }}
        .meta {{ color: #666; font-size: 14px; }}
        .body {{ margin-top: 15px; line-height: 1.6; }}
        .attachments {{ margin-top: 10px; padding: 10px; background: #f9f9f9; border-left: 3px solid #4CAF50; }}
    </style>
</head>
<body>
    <h1>Email Export - {folder}</h1>
    <p>Total emails: {len(emails)}</p>
"""
        
        for i, email_data in enumerate(emails, 1):
            html += f"""
    <div class="email">
        <div class="header">
            <div class="subject">{self._html_escape(email_data['subject'])}</div>
            <div class="meta">
                <strong>From:</strong> {self._html_escape(email_data['from'])}<br>
                <strong>To:</strong> {self._html_escape(email_data['to'])}<br>
                <strong>Date:</strong> {email_data['date']}<br>
            </div>
        </div>
        <div class="body">
            {self._html_escape(email_data['body_text']) if email_data['body_text'] else email_data.get('body_html', '')}
        </div>
"""
            if email_data.get('attachments'):
                html += '        <div class="attachments"><strong>Attachments:</strong> '
                html += ', '.join([f"{att['filename']} ({att['size']} bytes)" for att in email_data['attachments']])
                html += '</div>\n'
            
            html += '    </div>\n'
        
        html += """
</body>
</html>
"""
        return html
    
    def _html_escape(self, text: str) -> str:
        """Basic HTML escaping."""
        if not text:
            return ''
        return (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&#39;'))


def create_email_processor(
    protocol: Literal['imap', 'pop3', 'eml'] = 'imap',
    server: Optional[str] = None,
    port: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    use_ssl: bool = True,
    timeout: int = 30,
) -> EmailProcessor:
    """
    Factory function to create an EmailProcessor instance.
    
    Args:
        protocol: Connection protocol - 'imap', 'pop3', or 'eml'
        server: Mail server hostname (required for IMAP/POP3)
        port: Server port (defaults: IMAP=993, POP3=995)
        username: Account username/email
        password: Account password (can use env vars)
        use_ssl: Use SSL/TLS connection (default: True)
        timeout: Connection timeout in seconds (default: 30)
        
    Returns:
        EmailProcessor instance
        
    Example:
        >>> processor = create_email_processor(
        ...     protocol='imap',
        ...     server='imap.gmail.com',
        ...     username='user@gmail.com',
        ...     password='app_password'
        ... )
    """
    return EmailProcessor(
        protocol=protocol,
        server=server,
        port=port,
        username=username,
        password=password,
        use_ssl=use_ssl,
        timeout=timeout
    )
