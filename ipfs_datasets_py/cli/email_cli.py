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
    from ipfs_datasets_py.data_transformation.multimedia import EmailProcessor
    
    try:
        processor = EmailProcessor(
            protocol=args.protocol,
            server=args.server,
            port=args.port,
            username=args.username,
            password=args.password,
            use_ssl=not args.no_ssl,
            timeout=args.timeout
        )
        
        result = await processor.connect()
        await processor.disconnect()
        
        print(json.dumps(result, indent=2))
        return 0 if result['status'] == 'success' else 1
        
    except Exception as e:
        result = {
            'status': 'error',
            'error': str(e),
            'protocol': args.protocol,
            'server': args.server
        }
        print(json.dumps(result, indent=2))
        return 1


async def cmd_folders(args):
    """List IMAP mailbox folders."""
    from ipfs_datasets_py.data_transformation.multimedia import EmailProcessor
    
    try:
        processor = EmailProcessor(
            protocol='imap',
            server=args.server,
            port=args.port,
            username=args.username,
            password=args.password,
            use_ssl=not args.no_ssl,
            timeout=args.timeout
        )
        
        await processor.connect()
        result = await processor.list_folders()
        await processor.disconnect()
        
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"Folders saved to {args.output}")
        else:
            print(json.dumps(result, indent=2))
        
        return 0 if result['status'] == 'success' else 1
        
    except Exception as e:
        result = {
            'status': 'error',
            'error': str(e),
            'server': args.server
        }
        print(json.dumps(result, indent=2))
        return 1


async def cmd_export(args):
    """Export emails from a folder."""
    from ipfs_datasets_py.data_transformation.multimedia import EmailProcessor
    
    try:
        processor = EmailProcessor(
            protocol=args.protocol,
            server=args.server,
            port=args.port,
            username=args.username,
            password=args.password,
            use_ssl=not args.no_ssl,
            timeout=args.timeout
        )
        
        await processor.connect()
        result = await processor.export_folder(
            folder=args.folder,
            output_path=args.output,
            format=args.format,
            limit=args.limit,
            search_criteria=args.search
        )
        await processor.disconnect()
        
        print(json.dumps(result, indent=2))
        return 0 if result['status'] == 'success' else 1
        
    except Exception as e:
        result = {
            'status': 'error',
            'error': str(e),
            'folder': args.folder,
            'server': args.server
        }
        print(json.dumps(result, indent=2))
        return 1


async def cmd_parse(args):
    """Parse an .eml file."""
    from ipfs_datasets_py.data_transformation.multimedia import EmailProcessor
    
    try:
        processor = EmailProcessor(protocol='eml')
        result = await processor.parse_eml_file(
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
        
    except Exception as e:
        result = {
            'status': 'error',
            'error': str(e),
            'file_path': args.file_path
        }
        print(json.dumps(result, indent=2))
        return 1


async def cmd_fetch(args):
    """Fetch emails."""
    from ipfs_datasets_py.data_transformation.multimedia import EmailProcessor
    
    try:
        processor = EmailProcessor(
            protocol=args.protocol,
            server=args.server,
            port=args.port,
            username=args.username,
            password=args.password,
            use_ssl=not args.no_ssl,
            timeout=args.timeout
        )
        
        await processor.connect()
        result = await processor.fetch_emails(
            folder=args.folder,
            limit=args.limit,
            search_criteria=args.search,
            include_attachments=not args.no_attachments
        )
        await processor.disconnect()
        
    except Exception as e:
        result = {
            'status': 'error',
            'error': str(e),
            'folder': args.folder,
            'server': args.server
        }
    
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
    import json as json_module
    from collections import Counter
    
    try:
        # Read export file
        with open(args.file_path, 'r', encoding='utf-8') as f:
            data = json_module.load(f)
        
        if 'emails' not in data:
            result = {
                'status': 'error',
                'error': 'Invalid export file format. Expected "emails" key.',
                'file_path': args.file_path
            }
        else:
            emails = data['emails']
            
            if not emails:
                result = {
                    'status': 'success',
                    'file_path': args.file_path,
                    'total_emails': 0,
                    'message': 'No emails to analyze'
                }
            else:
                # Analyze emails
                senders = [email.get('from') for email in emails if email.get('from')]
                recipients = [email.get('to') for email in emails if email.get('to')]
                dates = [email.get('date') for email in emails if email.get('date')]
                lengths = [len(email.get('body_text', '') or email.get('body_html', '')) for email in emails]
                attachments_count = sum(len(email.get('attachments', [])) for email in emails)
                total_attachment_size = sum(
                    sum(att.get('size', 0) for att in email.get('attachments', []))
                    for email in emails
                )
                
                # Threading
                threads = {}
                for email in emails:
                    in_reply_to = email.get('in_reply_to', '')
                    if in_reply_to:
                        if in_reply_to not in threads:
                            threads[in_reply_to] = []
                        threads[in_reply_to].append(email.get('message_id_header', ''))
                
                sender_counts = Counter(senders)
                recipient_counts = Counter(recipients)
                
                sorted_dates = sorted(dates) if dates else []
                date_range = {
                    'earliest': sorted_dates[0],
                    'latest': sorted_dates[-1]
                } if sorted_dates else None
                
                avg_length = sum(lengths) / len(lengths) if lengths else 0
                
                result = {
                    'status': 'success',
                    'file_path': args.file_path,
                    'total_emails': len(emails),
                    'date_range': date_range,
                    'top_senders': [
                        {'sender': sender, 'count': count}
                        for sender, count in sender_counts.most_common(10)
                    ],
                    'top_recipients': [
                        {'recipient': recipient, 'count': count}
                        for recipient, count in recipient_counts.most_common(10)
                    ],
                    'attachment_stats': {
                        'total_attachments': attachments_count,
                        'total_size_bytes': total_attachment_size,
                        'average_per_email': attachments_count / len(emails) if emails else 0
                    },
                    'average_body_length': int(avg_length),
                    'thread_count': len(threads),
                    'threads_with_replies': len([t for t in threads.values() if len(t) > 1])
                }
        
        if args.output:
            with open(args.output, 'w') as f:
                json_module.dump(result, f, indent=2)
            print(f"Analysis saved to {args.output}")
        else:
            print(json_module.dumps(result, indent=2))
        
        return 0 if result['status'] == 'success' else 1
        
    except FileNotFoundError:
        result = {
            'status': 'error',
            'error': f'File not found: {args.file_path}',
            'file_path': args.file_path
        }
        print(json_module.dumps(result, indent=2))
        return 1
    except json_module.JSONDecodeError:
        result = {
            'status': 'error',
            'error': 'Invalid JSON file',
            'file_path': args.file_path
        }
        print(json_module.dumps(result, indent=2))
        return 1
    except Exception as e:
        result = {
            'status': 'error',
            'error': str(e),
            'file_path': args.file_path
        }
        print(json_module.dumps(result, indent=2))
        return 1


async def cmd_search(args):
    """Search emails in an export file."""
    import json as json_module
    
    try:
        # Read export file
        with open(args.file_path, 'r', encoding='utf-8') as f:
            data = json_module.load(f)
        
        if 'emails' not in data:
            result = {
                'status': 'error',
                'error': 'Invalid export file format. Expected "emails" key.',
                'file_path': args.file_path
            }
        else:
            emails = data['emails']
            query_lower = args.query.lower()
            
            # Search emails
            matches = []
            for email in emails:
                match = False
                
                if args.field == 'all':
                    search_text = ' '.join([
                        str(email.get('subject', '')),
                        str(email.get('from', '')),
                        str(email.get('to', '')),
                        str(email.get('body_text', '')),
                        str(email.get('body_html', ''))
                    ]).lower()
                    match = query_lower in search_text
                elif args.field == 'subject':
                    match = query_lower in str(email.get('subject', '')).lower()
                elif args.field == 'from':
                    match = query_lower in str(email.get('from', '')).lower()
                elif args.field == 'to':
                    match = query_lower in str(email.get('to', '')).lower()
                elif args.field == 'body':
                    body_text = str(email.get('body_text', '')) + str(email.get('body_html', ''))
                    match = query_lower in body_text.lower()
                
                if match:
                    matches.append(email)
            
            result = {
                'status': 'success',
                'file_path': args.file_path,
                'query': args.query,
                'field': args.field,
                'match_count': len(matches),
                'matches': matches
            }
        
        if args.output:
            with open(args.output, 'w') as f:
                json_module.dump(result, f, indent=2)
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
                print(json_module.dumps(result, indent=2))
        
        return 0 if result['status'] == 'success' else 1
        
    except FileNotFoundError:
        result = {
            'status': 'error',
            'error': f'File not found: {args.file_path}',
            'file_path': args.file_path
        }
        print(json_module.dumps(result, indent=2))
        return 1
    except json_module.JSONDecodeError:
        result = {
            'status': 'error',
            'error': 'Invalid JSON file',
            'file_path': args.file_path
        }
        print(json_module.dumps(result, indent=2))
        return 1
    except Exception as e:
        result = {
            'status': 'error',
            'error': str(e),
            'file_path': args.file_path,
            'query': args.query
        }
        print(json_module.dumps(result, indent=2))
        return 1


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
