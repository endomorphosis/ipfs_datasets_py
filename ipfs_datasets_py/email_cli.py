#!/usr/bin/env python3
"""
Email CLI Tool for IPFS Datasets.

Command-line interface for email ingestion and analysis including:
- IMAP and POP3 server connections
- Folder listing and email export
- .eml file parsing
- Email analysis and search

Usage:
    ipfs-datasets email [command] [options]
    python -m ipfs_datasets_py.email_cli [command] [options]
"""

import argparse
import anyio
import json
import os
import sys
from pathlib import Path
from typing import Optional


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for Email CLI."""
    parser = argparse.ArgumentParser(
        prog='ipfs-datasets email',
        description='Email Ingestion and Analysis CLI'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Test connection command
    test_parser = subparsers.add_parser('test', help='Test email server connection')
    test_parser.add_argument('--protocol', default='imap', choices=['imap', 'pop3'],
                            help='Connection protocol (default: imap)')
    test_parser.add_argument('--server', required=True, help='Mail server hostname')
    test_parser.add_argument('--port', type=int, help='Server port (defaults: IMAP=993, POP3=995)')
    test_parser.add_argument('--username', help='Account username (or use EMAIL_USER env var)')
    test_parser.add_argument('--password', help='Account password (or use EMAIL_PASS env var)')
    test_parser.add_argument('--no-ssl', action='store_true', help='Disable SSL/TLS')
    test_parser.add_argument('--timeout', type=int, default=30, help='Connection timeout (default: 30s)')
    
    # List folders command
    folders_parser = subparsers.add_parser('folders', help='List IMAP mailbox folders')
    folders_parser.add_argument('--server', required=True, help='IMAP server hostname')
    folders_parser.add_argument('--port', type=int, help='Server port (default: 993)')
    folders_parser.add_argument('--username', help='Account username (or use EMAIL_USER env var)')
    folders_parser.add_argument('--password', help='Account password (or use EMAIL_PASS env var)')
    folders_parser.add_argument('--no-ssl', action='store_true', help='Disable SSL/TLS')
    folders_parser.add_argument('--timeout', type=int, default=30, help='Connection timeout (default: 30s)')
    folders_parser.add_argument('--output', '-o', help='Output JSON file')
    
    # Export emails command
    export_parser = subparsers.add_parser('export', help='Export emails from a folder')
    export_parser.add_argument('--folder', default='INBOX', help='Mailbox folder name (default: INBOX)')
    export_parser.add_argument('--server', required=True, help='Mail server hostname')
    export_parser.add_argument('--port', type=int, help='Server port (defaults: IMAP=993, POP3=995)')
    export_parser.add_argument('--username', help='Account username (or use EMAIL_USER env var)')
    export_parser.add_argument('--password', help='Account password (or use EMAIL_PASS env var)')
    export_parser.add_argument('--protocol', default='imap', choices=['imap', 'pop3'],
                              help='Connection protocol (default: imap)')
    export_parser.add_argument('--output', '-o', help='Output file path')
    export_parser.add_argument('--format', '-f', default='json',
                              choices=['json', 'html', 'csv', 'txt'],
                              help='Export format (default: json)')
    export_parser.add_argument('--limit', type=int, help='Maximum number of emails to export')
    export_parser.add_argument('--search', help='IMAP search criteria (e.g., "UNSEEN")')
    export_parser.add_argument('--no-ssl', action='store_true', help='Disable SSL/TLS')
    export_parser.add_argument('--timeout', type=int, default=30, help='Connection timeout (default: 30s)')
    
    # Parse .eml file command
    parse_parser = subparsers.add_parser('parse', help='Parse an .eml file')
    parse_parser.add_argument('file_path', help='Path to .eml file')
    parse_parser.add_argument('--output', '-o', help='Output JSON file')
    parse_parser.add_argument('--no-attachments', action='store_true',
                             help='Do not extract attachment metadata')
    
    # Fetch emails command (returns data, no export)
    fetch_parser = subparsers.add_parser('fetch', help='Fetch emails (no export)')
    fetch_parser.add_argument('--folder', default='INBOX', help='Mailbox folder name (default: INBOX)')
    fetch_parser.add_argument('--server', required=True, help='Mail server hostname')
    fetch_parser.add_argument('--port', type=int, help='Server port (defaults: IMAP=993, POP3=995)')
    fetch_parser.add_argument('--username', help='Account username (or use EMAIL_USER env var)')
    fetch_parser.add_argument('--password', help='Account password (or use EMAIL_PASS env var)')
    fetch_parser.add_argument('--protocol', default='imap', choices=['imap', 'pop3'],
                            help='Connection protocol (default: imap)')
    fetch_parser.add_argument('--limit', type=int, help='Maximum number of emails to fetch')
    fetch_parser.add_argument('--search', help='IMAP search criteria (e.g., "UNSEEN")')
    fetch_parser.add_argument('--no-attachments', action='store_true',
                            help='Do not extract attachment metadata')
    fetch_parser.add_argument('--no-ssl', action='store_true', help='Disable SSL/TLS')
    fetch_parser.add_argument('--timeout', type=int, default=30, help='Connection timeout (default: 30s)')
    fetch_parser.add_argument('--output', '-o', help='Output JSON file')
    
    # Analyze export command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze an email export file')
    analyze_parser.add_argument('file_path', help='Path to email export file (JSON)')
    analyze_parser.add_argument('--output', '-o', help='Output JSON file')
    
    # Search export command
    search_parser = subparsers.add_parser('search', help='Search emails in an export file')
    search_parser.add_argument('file_path', help='Path to email export file (JSON)')
    search_parser.add_argument('query', help='Search query string')
    search_parser.add_argument('--field', default='all',
                              choices=['all', 'subject', 'from', 'to', 'body'],
                              help='Field to search (default: all)')
    search_parser.add_argument('--output', '-o', help='Output JSON file')
    
    return parser


async def cmd_test(args):
    """Test email server connection."""
    from ipfs_datasets_py.mcp_server.tools.email_tools import email_test_connection
    
    result = await email_test_connection(
        protocol=args.protocol,
        server=args.server,
        port=args.port,
        username=args.username,
        password=args.password,
        use_ssl=not args.no_ssl,
        timeout=args.timeout
    )
    
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'success' else 1


async def cmd_folders(args):
    """List IMAP mailbox folders."""
    from ipfs_datasets_py.mcp_server.tools.email_tools import email_list_folders
    
    result = await email_list_folders(
        server=args.server,
        port=args.port,
        username=args.username,
        password=args.password,
        use_ssl=not args.no_ssl,
        timeout=args.timeout
    )
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"Folders saved to {args.output}")
    else:
        print(json.dumps(result, indent=2))
    
    return 0 if result['status'] == 'success' else 1


async def cmd_export(args):
    """Export emails from a folder."""
    from ipfs_datasets_py.mcp_server.tools.email_tools import email_export_folder
    
    result = await email_export_folder(
        folder=args.folder,
        output_path=args.output,
        format=args.format,
        server=args.server,
        port=args.port,
        username=args.username,
        password=args.password,
        protocol=args.protocol,
        limit=args.limit,
        search_criteria=args.search,
        use_ssl=not args.no_ssl,
        timeout=args.timeout
    )
    
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'success' else 1


async def cmd_parse(args):
    """Parse an .eml file."""
    from ipfs_datasets_py.mcp_server.tools.email_tools import email_parse_eml
    
    result = await email_parse_eml(
        file_path=args.file_path,
        include_attachments=not args.no_attachments
    )
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"Parsed email saved to {args.output}")
    else:
        print(json.dumps(result, indent=2))
    
    return 0 if result['status'] == 'success' else 1


async def cmd_fetch(args):
    """Fetch emails."""
    from ipfs_datasets_py.mcp_server.tools.email_tools import email_fetch_emails
    
    result = await email_fetch_emails(
        folder=args.folder,
        server=args.server,
        port=args.port,
        username=args.username,
        password=args.password,
        protocol=args.protocol,
        limit=args.limit,
        search_criteria=args.search,
        include_attachments=not args.no_attachments,
        use_ssl=not args.no_ssl,
        timeout=args.timeout
    )
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"Emails saved to {args.output}")
    else:
        # Print summary instead of full data
        if result['status'] == 'success':
            print(f"Successfully fetched {result['email_count']} emails")
            print(f"Protocol: {result['protocol']}")
            if 'folder' in result:
                print(f"Folder: {result['folder']}")
        else:
            print(json.dumps(result, indent=2))
    
    return 0 if result['status'] == 'success' else 1


async def cmd_analyze(args):
    """Analyze an email export file."""
    from ipfs_datasets_py.mcp_server.tools.email_tools import email_analyze_export
    
    result = await email_analyze_export(file_path=args.file_path)
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"Analysis saved to {args.output}")
    else:
        print(json.dumps(result, indent=2))
    
    return 0 if result['status'] == 'success' else 1


async def cmd_search(args):
    """Search emails in an export file."""
    from ipfs_datasets_py.mcp_server.tools.email_tools import email_search_export
    
    result = await email_search_export(
        file_path=args.file_path,
        query=args.query,
        field=args.field
    )
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"Search results saved to {args.output}")
    else:
        # Print summary
        if result['status'] == 'success':
            print(f"Found {result['match_count']} matching emails")
            print(f"Query: {result['query']}")
            print(f"Field: {result['field']}")
            if result['match_count'] > 0 and result['match_count'] <= 5:
                print("\nMatches:")
                for match in result['matches']:
                    print(f"  - {match.get('subject', 'No subject')} (from {match.get('from', 'Unknown')})")
        else:
            print(json.dumps(result, indent=2))
    
    return 0 if result['status'] == 'success' else 1


async def main_async(args):
    """Main async entry point."""
    parser = create_parser()
    parsed_args = parser.parse_args(args)
    
    if not parsed_args.command:
        parser.print_help()
        return 1
    
    # Route to appropriate command
    commands = {
        'test': cmd_test,
        'folders': cmd_folders,
        'export': cmd_export,
        'parse': cmd_parse,
        'fetch': cmd_fetch,
        'analyze': cmd_analyze,
        'search': cmd_search,
    }
    
    handler = commands.get(parsed_args.command)
    if handler:
        return await handler(parsed_args)
    else:
        print(f"Unknown command: {parsed_args.command}")
        parser.print_help()
        return 1


def main(args=None):
    """Main entry point."""
    if args is None:
        args = sys.argv[1:]
    
    try:
        exit_code = anyio.run(main_async, args)
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
