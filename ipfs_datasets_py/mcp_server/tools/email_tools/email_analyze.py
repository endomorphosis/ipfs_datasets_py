# ipfs_datasets_py/mcp_server/tools/email_tools/email_analyze.py
"""
Email analysis tools for the MCP server.

This module provides email analysis and statistics capabilities
via the MCP protocol.

Uses anyio for asyncio/trio compatibility (libp2p integration)
"""
import anyio
from typing import Dict, Any, List
from collections import Counter
from datetime import datetime
import json

import logging

logger = logging.getLogger(__name__)


async def email_analyze_export(
    file_path: str
) -> Dict[str, Any]:
    """
    Analyze an email export file and generate statistics.
    
    Args:
        file_path: Path to email export file (JSON format)
        
    Returns:
        Dict containing analysis results:
            - status: 'success' or 'error'
            - file_path: Path to analyzed file
            - total_emails: Total number of emails
            - date_range: Earliest and latest email dates
            - top_senders: Most frequent senders
            - top_recipients: Most frequent recipients
            - attachment_stats: Attachment statistics
            - average_length: Average email length
            - thread_count: Number of threaded conversations
            - error: Error message if failed
    
    Example:
        >>> result = await email_analyze_export(
        ...     file_path='inbox_export.json'
        ... )
    """
    try:
        # Read export file
        def _read_file():
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        data = await anyio.to_thread.run_sync(_read_file)
        
        if 'emails' not in data:
            return {
                "status": "error",
                "error": "Invalid export file format. Expected 'emails' key.",
                "file_path": file_path
            }
        
        emails = data['emails']
        
        if not emails:
            return {
                "status": "success",
                "file_path": file_path,
                "total_emails": 0,
                "message": "No emails to analyze"
            }
        
        # Analyze emails
        senders = []
        recipients = []
        dates = []
        lengths = []
        attachments_count = 0
        total_attachment_size = 0
        threads = {}
        
        for email in emails:
            # Senders and recipients
            if email.get('from'):
                senders.append(email['from'])
            if email.get('to'):
                recipients.append(email['to'])
            
            # Dates
            if email.get('date'):
                try:
                    dates.append(email['date'])
                except (KeyError, TypeError, ValueError):
                    # Skip emails with invalid date format
                    pass
            
            # Length
            body = email.get('body_text', '') or email.get('body_html', '')
            lengths.append(len(body))
            
            # Attachments
            if email.get('attachments'):
                attachments_count += len(email['attachments'])
                for att in email['attachments']:
                    total_attachment_size += att.get('size', 0)
            
            # Threading
            in_reply_to = email.get('in_reply_to', '')
            if in_reply_to:
                thread_id = in_reply_to
                if thread_id not in threads:
                    threads[thread_id] = []
                threads[thread_id].append(email.get('message_id_header', ''))
        
        # Calculate statistics
        sender_counts = Counter(senders)
        recipient_counts = Counter(recipients)
        
        # Date range
        date_range = None
        if dates:
            sorted_dates = sorted(dates)
            date_range = {
                'earliest': sorted_dates[0],
                'latest': sorted_dates[-1]
            }
        
        # Average length
        avg_length = sum(lengths) / len(lengths) if lengths else 0
        
        return {
            "status": "success",
            "file_path": file_path,
            "total_emails": len(emails),
            "date_range": date_range,
            "top_senders": [
                {"sender": sender, "count": count}
                for sender, count in sender_counts.most_common(10)
            ],
            "top_recipients": [
                {"recipient": recipient, "count": count}
                for recipient, count in recipient_counts.most_common(10)
            ],
            "attachment_stats": {
                "total_attachments": attachments_count,
                "total_size_bytes": total_attachment_size,
                "average_per_email": attachments_count / len(emails) if emails else 0
            },
            "average_body_length": int(avg_length),
            "thread_count": len(threads),
            "threads_with_replies": len([t for t in threads.values() if len(t) > 1])
        }
        
    except FileNotFoundError:
        return {
            "status": "error",
            "error": f"File not found: {file_path}",
            "file_path": file_path
        }
    except json.JSONDecodeError:
        return {
            "status": "error",
            "error": "Invalid JSON file",
            "file_path": file_path
        }
    except Exception as e:
        logger.error(f"Failed to analyze email export: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "file_path": file_path
        }


async def email_search_export(
    file_path: str,
    query: str,
    field: str = 'all'
) -> Dict[str, Any]:
    """
    Search emails in an export file.
    
    Args:
        file_path: Path to email export file (JSON format)
        query: Search query string
        field: Field to search - 'all', 'subject', 'from', 'to', 'body' (default: 'all')
        
    Returns:
        Dict containing search results:
            - status: 'success' or 'error'
            - file_path: Path to searched file
            - query: Search query
            - field: Field searched
            - match_count: Number of matching emails
            - matches: List of matching emails
            - error: Error message if failed
    
    Example:
        >>> result = await email_search_export(
        ...     file_path='inbox_export.json',
        ...     query='meeting',
        ...     field='subject'
        ... )
    """
    try:
        # Read export file
        def _read_file():
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        data = await anyio.to_thread.run_sync(_read_file)
        
        if 'emails' not in data:
            return {
                "status": "error",
                "error": "Invalid export file format. Expected 'emails' key.",
                "file_path": file_path
            }
        
        emails = data['emails']
        query_lower = query.lower()
        
        # Search emails
        matches = []
        for email in emails:
            match = False
            
            if field == 'all':
                # Search all fields
                search_text = ' '.join([
                    str(email.get('subject', '')),
                    str(email.get('from', '')),
                    str(email.get('to', '')),
                    str(email.get('body_text', '')),
                    str(email.get('body_html', ''))
                ]).lower()
                match = query_lower in search_text
            
            elif field == 'subject':
                match = query_lower in str(email.get('subject', '')).lower()
            
            elif field == 'from':
                match = query_lower in str(email.get('from', '')).lower()
            
            elif field == 'to':
                match = query_lower in str(email.get('to', '')).lower()
            
            elif field == 'body':
                body_text = str(email.get('body_text', '')) + str(email.get('body_html', ''))
                match = query_lower in body_text.lower()
            
            if match:
                matches.append(email)
        
        return {
            "status": "success",
            "file_path": file_path,
            "query": query,
            "field": field,
            "match_count": len(matches),
            "matches": matches
        }
        
    except FileNotFoundError:
        return {
            "status": "error",
            "error": f"File not found: {file_path}",
            "file_path": file_path
        }
    except json.JSONDecodeError:
        return {
            "status": "error",
            "error": "Invalid JSON file",
            "file_path": file_path
        }
    except Exception as e:
        logger.error(f"Failed to search email export: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "file_path": file_path,
            "query": query
        }
