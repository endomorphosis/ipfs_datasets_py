#!/usr/bin/env python3
"""
Email CLI Tool for IPFS Datasets.

Command-line interface for email ingestion and analysis including:
- IMAP and POP3 server connections
- Folder listing and email export
- .eml file parsing
- Email analysis and search
- Google Voice Takeout parsing
- Google Workspace Vault Voice export parsing
- Google Workspace Data Export/GCS staging
- local watch-folder hydration for newly arrived Voice exports

Usage:
    ipfs-datasets email [command] [options]
    python -m ipfs_datasets_py.email_cli [command] [options]
"""

import argparse
import anyio
import json
import sys
from pathlib import Path
from typing import Any
import shutil
import zipfile


def _add_google_voice_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('source', help='Path to source directory, zip archive, or gs:// URI for data-export mode')
    parser.add_argument('--output', '-o', help='Output JSON file')
    parser.add_argument('--summary-only', action='store_true', help='Print summary metadata without full event payloads')
    parser.add_argument('--materialize', action='store_true', help='Write normalized event bundles to an output directory')
    parser.add_argument('--output-dir', help='Directory for materialized event bundles')
    parser.add_argument('--staging-dir', help='Local staging directory for gs:// data export sources')


def _add_takeout_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--product-id', action='append', default=[], help='Takeout product data-id value (repeatable)')
    parser.add_argument('--page-source', help='Saved HTML source from takeout.google.com used to discover product data-id values')
    parser.add_argument(
        '--dest',
        default='drive',
        choices=['drive', 'email', 'dropbox', 'box', 'onedrive'],
        help='Takeout delivery destination',
    )
    parser.add_argument(
        '--frequency',
        default='one_time',
        choices=['one_time', '2_months'],
        help='Takeout export frequency',
    )
    parser.add_argument('--output', '-o', help='Write the computed plan to a JSON file')


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

    # Google Voice Takeout parse command
    voice_parser = subparsers.add_parser('google-voice', help='Parse a Google Voice Takeout directory or zip archive')
    _add_google_voice_common_args(voice_parser)

    vault_parser = subparsers.add_parser(
        'google-voice-vault',
        help='Parse a Google Workspace Vault Voice export directory or zip archive',
    )
    _add_google_voice_common_args(vault_parser)

    data_export_parser = subparsers.add_parser(
        'google-voice-data-export',
        help='Parse a Google Workspace Data Export bundle from a local path or gs:// URI',
    )
    _add_google_voice_common_args(data_export_parser)

    watch_parser = subparsers.add_parser(
        'google-voice-watch',
        help='Watch a local directory and hydrate newly arrived Google Voice exports into normalized bundles',
    )
    watch_parser.add_argument('watch_dir', help='Directory to poll for new Google Voice exports')
    watch_parser.add_argument('--output-dir', required=True, help='Directory where hydrated bundle manifests should be written')
    watch_parser.add_argument(
        '--source-kind',
        default='takeout',
        choices=['takeout', 'vault_export', 'data_export'],
        help='Interpret newly discovered exports as this source kind',
    )
    watch_parser.add_argument('--poll-interval', type=float, default=5.0, help='Seconds between directory scans')
    watch_parser.add_argument('--state-path', help='JSON file used to remember already processed exports')
    watch_parser.add_argument('--once', action='store_true', help='Scan once and exit instead of polling continuously')
    watch_parser.add_argument('--max-events', type=int, help='Stop after processing this many new exports')
    watch_parser.add_argument('--staging-dir', help='Optional staging directory used for data_export watch mode')

    takeout_url_parser = subparsers.add_parser(
        'google-voice-takeout-url',
        help='Build a documented custom Google Takeout URL for consumer Google Voice export selection',
    )
    _add_takeout_common_args(takeout_url_parser)

    takeout_open_parser = subparsers.add_parser(
        'google-voice-takeout-open',
        help='Open a custom Google Takeout URL in Playwright for human-in-the-loop export creation',
    )
    _add_takeout_common_args(takeout_open_parser)
    takeout_open_parser.add_argument(
        '--browser',
        default='chromium',
        choices=['chromium', 'firefox', 'webkit'],
        help='Playwright browser engine',
    )
    takeout_open_parser.add_argument('--headless', action='store_true', help='Run Playwright without opening a visible browser window')
    takeout_open_parser.add_argument('--auto-submit', action='store_true', help='Best-effort click of the final export button after page load')
    takeout_open_parser.add_argument('--user-data-dir', help='Persistent browser profile directory so Google login state can be reused')
    takeout_open_parser.add_argument('--save-storage-state', help='Write Playwright storage state JSON after page load')

    takeout_capture_parser = subparsers.add_parser(
        'google-voice-takeout-capture',
        help='Open the custom Takeout URL in Playwright and wait for an archive download to appear',
    )
    _add_takeout_common_args(takeout_capture_parser)
    takeout_capture_parser.add_argument(
        '--browser',
        default='chromium',
        choices=['chromium', 'firefox', 'webkit'],
        help='Playwright browser engine',
    )
    takeout_capture_parser.add_argument('--headless', action='store_true', help='Run Playwright without opening a visible browser window')
    takeout_capture_parser.add_argument('--auto-submit', action='store_true', help='Best-effort click of the final export button after page load')
    takeout_capture_parser.add_argument('--user-data-dir', help='Persistent browser profile directory so Google login state can be reused')
    takeout_capture_parser.add_argument('--save-storage-state', help='Write Playwright storage state JSON after page load')
    takeout_capture_parser.add_argument('--downloads-dir', help='Directory where Playwright should store/download the archive')
    takeout_capture_parser.add_argument('--download-timeout-ms', type=int, default=300000, help='How long to wait for an archive download')

    takeout_source_parser = subparsers.add_parser(
        'google-voice-takeout-source',
        help='Open takeout.google.com in Playwright and save page source for later data-id inference',
    )
    takeout_source_parser.add_argument('--output', '-o', required=True, help='Where to write the captured Takeout HTML page source')
    takeout_source_parser.add_argument(
        '--browser',
        default='chromium',
        choices=['chromium', 'firefox', 'webkit'],
        help='Playwright browser engine',
    )
    takeout_source_parser.add_argument('--headless', action='store_true', help='Run Playwright without opening a visible browser window')
    takeout_source_parser.add_argument('--user-data-dir', help='Persistent browser profile directory so Google login state can be reused')

    takeout_poll_parser = subparsers.add_parser(
        'google-voice-takeout-poll',
        help='Poll a local download directory until a completed Takeout archive appears',
    )
    takeout_poll_parser.add_argument('--downloads-dir', required=True, help='Directory to watch for Takeout archive downloads')
    takeout_poll_parser.add_argument('--archive-glob', default='*.zip', help='Glob used to match completed archive files')
    takeout_poll_parser.add_argument('--timeout-ms', type=int, default=300000, help='How long to wait for an archive')
    takeout_poll_parser.add_argument('--poll-interval-ms', type=int, default=2000, help='How often to scan the directory')
    takeout_poll_parser.add_argument('--output', '-o', help='Write the poll result to JSON')

    takeout_drive_parser = subparsers.add_parser(
        'google-voice-takeout-drive',
        help='Poll Google Drive for a Takeout artifact and optionally download it locally',
    )
    takeout_drive_parser.add_argument('--client-secrets', required=True, help='Google OAuth client secrets JSON for Drive API access')
    takeout_drive_parser.add_argument('--account-hint', required=True, help='Google account email/login hint for the Drive OAuth flow')
    takeout_drive_parser.add_argument('--token-cache', help='Optional Drive OAuth token cache path')
    takeout_drive_parser.add_argument('--no-browser', action='store_true', help='Do not auto-open the OAuth browser during Drive auth')
    takeout_drive_parser.add_argument('--name-contains', default='takeout', help='Drive file name substring to poll for')
    takeout_drive_parser.add_argument('--modified-after', help='Only match Drive artifacts modified after this ISO timestamp')
    takeout_drive_parser.add_argument('--timeout-ms', type=int, default=300000, help='How long to wait for a Drive artifact')
    takeout_drive_parser.add_argument('--poll-interval-ms', type=int, default=5000, help='How often to poll Drive')
    takeout_drive_parser.add_argument('--download-dir', help='If provided, download the matching Drive file into this directory')
    takeout_drive_parser.add_argument('--output', '-o', help='Write the Drive poll/download result to JSON')

    takeout_status_parser = subparsers.add_parser(
        'google-voice-takeout-status',
        help='Summarize a saved consumer Takeout acquisition manifest',
    )
    takeout_status_parser.add_argument('manifest', help='Path to takeout_acquisition_manifest.json')
    takeout_status_parser.add_argument('--json', action='store_true', help='Print the full summary as JSON')

    takeout_doctor_parser = subparsers.add_parser(
        'google-voice-takeout-doctor',
        help='Diagnose the current state of a saved consumer Takeout acquisition manifest and suggest the next step',
    )
    takeout_doctor_parser.add_argument('manifest', help='Path to takeout_acquisition_manifest.json')
    takeout_doctor_parser.add_argument('--json', action='store_true', help='Print the diagnosis as JSON')

    takeout_history_parser = subparsers.add_parser(
        'google-voice-takeout-history',
        help='List archived snapshot history for a Takeout acquisition manifest directory',
    )
    takeout_history_parser.add_argument('path', help='Path to a manifest file or takeout_acquisition_history directory')
    takeout_history_parser.add_argument('--json', action='store_true', help='Print history as JSON')

    takeout_prune_parser = subparsers.add_parser(
        'google-voice-takeout-prune',
        help='Prune old archived snapshot history for a Takeout acquisition manifest directory',
    )
    takeout_prune_parser.add_argument('path', help='Path to a manifest file or takeout_acquisition_history directory')
    takeout_prune_parser.add_argument('--keep', type=int, default=20, help='Number of newest snapshots to keep')
    takeout_prune_parser.add_argument('--apply', action='store_true', help='Actually delete old snapshots (default is dry-run)')
    takeout_prune_parser.add_argument('--json', action='store_true', help='Print prune result as JSON')

    takeout_case_parser = subparsers.add_parser(
        'google-voice-takeout-case-summary',
        help='Show a concise summary for a Takeout case/download directory or acquisition manifest',
    )
    takeout_case_parser.add_argument('path', help='Path to a manifest file or Takeout downloads/case directory')
    takeout_case_parser.add_argument('--json', action='store_true', help='Print summary as JSON')

    takeout_report_parser = subparsers.add_parser(
        'google-voice-takeout-case-report',
        help='Export a markdown or HTML report for a Takeout case/download directory or acquisition manifest',
    )
    takeout_report_parser.add_argument('path', help='Path to a manifest file or Takeout downloads/case directory')
    takeout_report_parser.add_argument('--format', default='markdown', choices=['markdown', 'html'], help='Report output format')
    takeout_report_parser.add_argument('--output', '-o', required=True, help='Where to write the report')

    takeout_bundle_parser = subparsers.add_parser(
        'google-voice-takeout-case-bundle',
        help='Collect the latest manifest, history snapshots, and case reports into one archival folder',
    )
    takeout_bundle_parser.add_argument('path', help='Path to a manifest file or Takeout downloads/case directory')
    takeout_bundle_parser.add_argument('--output-dir', required=True, help='Directory where the bundle folder should be created')
    takeout_bundle_parser.add_argument('--history-limit', type=int, default=10, help='Maximum number of recent history snapshots to copy into the bundle')
    takeout_bundle_parser.add_argument(
        '--bundle-format',
        action='append',
        choices=['dir', 'zip', 'parquet', 'car'],
        default=[],
        help='Additional portable bundle artifact(s) to create; repeatable. Defaults to dir only.',
    )
    
    return parser


async def cmd_test(args):
    """Test email server connection."""
    from ipfs_datasets_py.processors.multimedia import EmailProcessor
    
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
    from ipfs_datasets_py.processors.multimedia import EmailProcessor
    
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
    from ipfs_datasets_py.processors.multimedia import EmailProcessor
    
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
    from ipfs_datasets_py.processors.multimedia import EmailProcessor
    
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
    from ipfs_datasets_py.processors.multimedia import EmailProcessor
    
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


def _google_voice_summary(result: dict) -> dict:
    return {
        'status': result.get('status'),
        'source': result.get('source'),
        'source_kind': result.get('source_kind'),
        'event_count': result.get('event_count', 0),
        'event_types': sorted({str(item.get('event_type') or '') for item in result.get('events', []) if item.get('event_type')}),
    }


def _emit_json_payload(payload: dict, output_path: str | None) -> None:
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"Google Voice data saved to {output_path}")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))


async def _run_google_voice_mode(args, *, mode: str):
    from ipfs_datasets_py.processors.multimedia import GoogleVoiceProcessor

    processor = GoogleVoiceProcessor()
    try:
        if args.materialize:
            if not args.output_dir:
                payload = {
                    'status': 'error',
                    'error': '--materialize requires --output-dir',
                    'source': args.source,
                }
                print(json.dumps(payload, indent=2))
                return 1
            if mode == 'vault_export':
                result = processor.export_vault_bundles(args.source, output_dir=args.output_dir)
            elif mode == 'data_export':
                result = processor.export_data_export_bundles(
                    args.source,
                    output_dir=args.output_dir,
                    staging_dir=args.staging_dir,
                )
            else:
                result = processor.export_bundles(args.source, output_dir=args.output_dir)
        else:
            if mode == 'vault_export':
                result = processor.parse_vault_export(args.source)
            elif mode == 'data_export':
                result = processor.parse_data_export(args.source, staging_dir=args.staging_dir)
            else:
                result = processor.parse_takeout(args.source)
    except FileNotFoundError:
        payload = {
            'status': 'error',
            'error': f'Source not found: {args.source}',
            'source': args.source,
        }
        print(json.dumps(payload, indent=2))
        return 1
    except Exception as e:
        payload = {
            'status': 'error',
            'error': str(e),
            'source': args.source,
        }
        print(json.dumps(payload, indent=2))
        return 1
    finally:
        processor.close()

    payload = result
    if args.summary_only and not args.materialize:
        payload = _google_voice_summary(result)

    _emit_json_payload(payload, args.output)

    return 0 if result.get('status') == 'success' else 1


async def cmd_google_voice(args):
    """Parse Google Voice Takeout data."""
    return await _run_google_voice_mode(args, mode='takeout')


async def cmd_google_voice_vault(args):
    """Parse Google Workspace Vault Voice export data."""
    return await _run_google_voice_mode(args, mode='vault_export')


async def cmd_google_voice_data_export(args):
    """Parse Google Workspace Data Export / GCS staged Voice data."""
    return await _run_google_voice_mode(args, mode='data_export')


async def cmd_google_voice_watch(args):
    """Watch a local directory for newly arrived Google Voice exports."""
    from ipfs_datasets_py.processors.multimedia import GoogleVoiceProcessor

    processor = GoogleVoiceProcessor()
    try:
        result = processor.watch_and_materialize(
            args.watch_dir,
            output_dir=args.output_dir,
            source_kind=args.source_kind,
            poll_interval=args.poll_interval,
            once=args.once,
            max_events=args.max_events,
            state_path=args.state_path,
            staging_dir=args.staging_dir,
        )
    except Exception as e:
        payload = {
            'status': 'error',
            'error': str(e),
            'watch_dir': args.watch_dir,
        }
        print(json.dumps(payload, indent=2))
        return 1
    finally:
        processor.close()

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get('status') == 'success' else 1


async def cmd_google_voice_takeout_url(args):
    """Build a documented custom Google Takeout URL."""
    from ipfs_datasets_py.processors.multimedia.google_takeout_automation import (
        build_google_voice_takeout_plan,
        save_takeout_plan,
    )

    try:
        payload = build_google_voice_takeout_plan(
            product_ids=list(args.product_id or []),
            page_source_path=args.page_source,
            destination=args.dest,
            frequency=args.frequency,
        )
    except Exception as e:
        payload = {
            'status': 'error',
            'error': str(e),
        }
        print(json.dumps(payload, indent=2))
        return 1

    if args.output:
        save_takeout_plan(payload, args.output)
        print(f"Google Voice Takeout plan saved to {args.output}")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


async def cmd_google_voice_takeout_open(args):
    """Open a Google Takeout URL in Playwright for human-in-the-loop export creation."""
    from ipfs_datasets_py.processors.multimedia.google_takeout_automation import (
        build_google_voice_takeout_plan,
        launch_takeout_in_browser,
        save_takeout_plan,
    )

    try:
        plan = build_google_voice_takeout_plan(
            product_ids=list(args.product_id or []),
            page_source_path=args.page_source,
            destination=args.dest,
            frequency=args.frequency,
        )
        browser_launch = await anyio.to_thread.run_sync(
            lambda: launch_takeout_in_browser(
                url=plan["takeout_url"],
                browser=args.browser,
                headed=not args.headless,
                user_data_dir=args.user_data_dir,
                auto_submit=args.auto_submit,
                save_storage_state=args.save_storage_state,
            )
        )
        payload = {
            **plan,
            "browser_launch": browser_launch,
        }
    except Exception as e:
        payload = {
            'status': 'error',
            'error': str(e),
        }
        print(json.dumps(payload, indent=2))
        return 1

    if args.output:
        save_takeout_plan(payload, args.output)
        print(f"Google Voice Takeout browser plan saved to {args.output}")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


async def cmd_google_voice_takeout_capture(args):
    """Open a Google Takeout URL and wait for an archive download."""
    from ipfs_datasets_py.processors.multimedia.google_takeout_automation import (
        build_google_voice_takeout_plan,
        open_takeout_and_capture_download,
        save_takeout_plan,
    )

    try:
        plan = build_google_voice_takeout_plan(
            product_ids=list(args.product_id or []),
            page_source_path=args.page_source,
            destination=args.dest,
            frequency=args.frequency,
        )
        browser_capture = await anyio.to_thread.run_sync(
            lambda: open_takeout_and_capture_download(
                url=plan["takeout_url"],
                browser=args.browser,
                headed=not args.headless,
                user_data_dir=args.user_data_dir,
                auto_submit=args.auto_submit,
                save_storage_state=args.save_storage_state,
                downloads_dir=args.downloads_dir,
                download_timeout_ms=args.download_timeout_ms,
            )
        )
        payload = {
            **plan,
            "browser_capture": browser_capture,
        }
    except Exception as e:
        payload = {
            'status': 'error',
            'error': str(e),
        }
        print(json.dumps(payload, indent=2))
        return 1

    if args.output:
        save_takeout_plan(payload, args.output)
        print(f"Google Voice Takeout capture plan saved to {args.output}")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    capture_status = payload.get("browser_capture", {}).get("status")
    return 0 if capture_status in {"success", "pending"} else 1


async def cmd_google_voice_takeout_source(args):
    """Capture the Takeout page source for later product-id inference."""
    from ipfs_datasets_py.processors.multimedia.google_takeout_automation import (
        capture_takeout_page_source,
        save_takeout_plan,
    )

    try:
        payload = await anyio.to_thread.run_sync(
            lambda: capture_takeout_page_source(
                browser=args.browser,
                headed=not args.headless,
                user_data_dir=args.user_data_dir,
                output_path=args.output,
            )
        )
    except Exception as e:
        payload = {
            'status': 'error',
            'error': str(e),
        }
        print(json.dumps(payload, indent=2))
        return 1

    save_takeout_plan(payload, args.output)
    print(f"Google Voice Takeout page source saved to {args.output}")
    return 0


async def cmd_google_voice_takeout_poll(args):
    """Poll a local directory until a completed Takeout archive appears."""
    from ipfs_datasets_py.processors.multimedia.google_takeout_automation import (
        poll_for_takeout_archive,
        save_takeout_plan,
    )

    try:
        payload = poll_for_takeout_archive(
            downloads_dir=args.downloads_dir,
            archive_glob=args.archive_glob,
            timeout_ms=args.timeout_ms,
            poll_interval_ms=args.poll_interval_ms,
        )
    except Exception as e:
        payload = {
            'status': 'error',
            'error': str(e),
        }
        print(json.dumps(payload, indent=2))
        return 1

    if args.output:
        save_takeout_plan(payload, args.output)
        print(f"Google Voice Takeout poll result saved to {args.output}")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload.get("status") in {"success", "pending"} else 1


async def cmd_google_voice_takeout_drive(args):
    """Poll Google Drive for a Takeout artifact and optionally download it."""
    from ipfs_datasets_py.processors.multimedia.google_takeout_automation import (
        poll_drive_and_optionally_download,
        save_takeout_plan,
    )

    try:
        payload = poll_drive_and_optionally_download(
            client_secrets_path=args.client_secrets,
            account_hint=args.account_hint,
            token_cache_path=args.token_cache,
            open_browser=not args.no_browser,
            name_contains=args.name_contains,
            modified_after=args.modified_after,
            timeout_ms=args.timeout_ms,
            poll_interval_ms=args.poll_interval_ms,
            download_dir=args.download_dir,
        )
    except Exception as e:
        payload = {
            'status': 'error',
            'error': str(e),
        }
        print(json.dumps(payload, indent=2))
        return 1

    if args.output:
        save_takeout_plan(payload, args.output)
        print(f"Google Voice Takeout Drive result saved to {args.output}")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload.get("status") in {"success", "pending"} else 1


async def cmd_google_voice_takeout_status(args):
    """Summarize a saved consumer Takeout acquisition manifest."""
    try:
        manifest_path = Path(args.manifest).expanduser().resolve()
        payload = json.loads(manifest_path.read_text(encoding='utf-8'))
    except Exception as e:
        error_payload = {
            'status': 'error',
            'error': str(e),
            'manifest': args.manifest,
        }
        print(json.dumps(error_payload, indent=2))
        return 1

    events = list(payload.get('events') or [])
    latest_event = events[-1] if events else {}
    summary = {
        'status': payload.get('status'),
        'case_slug': payload.get('case_slug'),
        'product_ids': list(payload.get('product_ids') or []),
        'delivery_destination': payload.get('delivery_destination'),
        'downloads_dir': payload.get('downloads_dir'),
        'capture_json_path': payload.get('capture_json_path'),
        'page_source_path': payload.get('page_source_path'),
        'final_archive_path': payload.get('final_archive_path'),
        'latest_event_type': latest_event.get('type'),
        'latest_event_timestamp': latest_event.get('timestamp'),
        'drive_fallback_enabled': bool((payload.get('drive_fallback') or {}).get('enabled')),
        'event_count': len(events),
        'manifest_path': str(manifest_path),
    }

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"Status: {summary['status'] or 'unknown'}")
        print(f"Case slug: {summary['case_slug'] or 'unknown'}")
        print(f"Destination: {summary['delivery_destination'] or 'unknown'}")
        print(f"Products: {', '.join(summary['product_ids']) if summary['product_ids'] else 'none'}")
        print(f"Latest event: {summary['latest_event_type'] or 'none'}")
        print(f"Downloads dir: {summary['downloads_dir'] or 'unknown'}")
        if summary['final_archive_path']:
            print(f"Final archive: {summary['final_archive_path']}")
        print(f"Manifest: {summary['manifest_path']}")
    return 0


def _doctor_takeout_manifest(payload: dict, manifest_path: Path) -> dict:
    status = str(payload.get('status') or '')
    downloads_dir = str(payload.get('downloads_dir') or '')
    final_archive_path = str(payload.get('final_archive_path') or '')
    page_source_path = str(payload.get('page_source_path') or '')
    drive_fallback = dict(payload.get('drive_fallback') or {})
    capture = dict(payload.get('capture') or {})
    browser_capture = dict(capture.get('browser_capture') or {})
    drive_result = dict(payload.get('drive_result') or {})

    diagnosis = "unknown"
    next_step = "Inspect the acquisition manifest and rerun the appropriate capture or resume command."

    if status == 'hydrated' and final_archive_path:
        diagnosis = "complete"
        next_step = "No action needed. The Takeout archive was already hydrated."
    elif final_archive_path:
        diagnosis = "ready_to_hydrate"
        next_step = (
            f"./run-google-voice-ingest.sh --source {final_archive_path} --source-mode takeout"
        )
    elif status in {'initialized', 'page_source_captured'} and page_source_path:
        diagnosis = "ready_for_capture"
        next_step = (
            f"./run-consumer-google-voice-takeout.sh --page-source {page_source_path}"
        )
    elif status in {'capture_attempted', 'pending_archive'}:
        diagnosis = "waiting_for_archive"
        if downloads_dir:
            next_step = (
                f"./run-consumer-google-voice-takeout.sh --resume-from-downloads {downloads_dir} --skip-index"
            )
        elif manifest_path:
            next_step = (
                f"./run-consumer-google-voice-takeout.sh --resume-from-manifest {manifest_path} --skip-index"
            )
    elif status == 'drive_fallback_attempted':
        diagnosis = "waiting_for_drive_artifact"
        if drive_fallback.get('enabled') and manifest_path:
            next_step = (
                f"./run-consumer-google-voice-takeout.sh --resume-from-manifest {manifest_path} --skip-index"
            )
        else:
            next_step = "Configure Drive fallback or wait for a local archive download before resuming."

    if browser_capture.get('download_path'):
        diagnosis = "ready_to_hydrate"
        next_step = (
            f"./run-google-voice-ingest.sh --source {browser_capture['download_path']} --source-mode takeout"
        )
    elif (drive_result.get('download') or {}).get('output_path'):
        diagnosis = "ready_to_hydrate"
        next_step = (
            f"./run-google-voice-ingest.sh --source {drive_result['download']['output_path']} --source-mode takeout"
        )

    return {
        'status': status or 'unknown',
        'diagnosis': diagnosis,
        'next_step': next_step,
        'manifest_path': str(manifest_path),
        'downloads_dir': downloads_dir or None,
        'page_source_path': page_source_path or None,
        'final_archive_path': final_archive_path or None,
        'drive_fallback_enabled': bool(drive_fallback.get('enabled')),
    }


async def cmd_google_voice_takeout_doctor(args):
    """Diagnose a saved consumer Takeout acquisition manifest and suggest the next step."""
    try:
        manifest_path = Path(args.manifest).expanduser().resolve()
        payload = json.loads(manifest_path.read_text(encoding='utf-8'))
    except Exception as e:
        error_payload = {
            'status': 'error',
            'error': str(e),
            'manifest': args.manifest,
        }
        print(json.dumps(error_payload, indent=2))
        return 1

    diagnosis = _doctor_takeout_manifest(payload, manifest_path)
    if args.json:
        print(json.dumps(diagnosis, indent=2, ensure_ascii=False))
    else:
        print(f"Diagnosis: {diagnosis['diagnosis']}")
        print(f"Status: {diagnosis['status']}")
        print(f"Next step: {diagnosis['next_step']}")
        print(f"Manifest: {diagnosis['manifest_path']}")
    return 0


async def cmd_google_voice_takeout_history(args):
    """List archived snapshot history for a Takeout acquisition manifest."""
    try:
        target = Path(args.path).expanduser().resolve()
        history_dir = target if target.is_dir() else target.parent / "takeout_acquisition_history"
        entries = []
        if history_dir.exists():
            for path in sorted(history_dir.glob("*.json")):
                try:
                    payload = json.loads(path.read_text(encoding='utf-8'))
                except Exception:
                    payload = {}
                entries.append(
                    {
                        'snapshot_path': str(path),
                        'status': payload.get('status'),
                        'updated_at': payload.get('updated_at'),
                        'final_archive_path': payload.get('final_archive_path'),
                    }
                )
        result = {
            'status': 'success',
            'history_dir': str(history_dir),
            'snapshot_count': len(entries),
            'snapshots': entries,
        }
    except Exception as e:
        result = {
            'status': 'error',
            'error': str(e),
            'path': args.path,
        }
        print(json.dumps(result, indent=2))
        return 1

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"History dir: {result['history_dir']}")
        print(f"Snapshots: {result['snapshot_count']}")
        for item in result['snapshots'][-10:]:
            print(f"- {item['status'] or 'unknown'} :: {item['snapshot_path']}")
    return 0


async def cmd_google_voice_takeout_prune(args):
    """Prune old archived snapshot history for a Takeout acquisition manifest."""
    try:
        target = Path(args.path).expanduser().resolve()
        history_dir = target if target.is_dir() else target.parent / "takeout_acquisition_history"
        snapshots = sorted(history_dir.glob("*.json")) if history_dir.exists() else []
        keep_count = max(0, int(args.keep))
        to_delete = snapshots[:-keep_count] if keep_count < len(snapshots) else []
        deleted: list[str] = []
        if args.apply:
            for path in to_delete:
                path.unlink(missing_ok=True)
                deleted.append(str(path))
        result = {
            'status': 'success',
            'history_dir': str(history_dir),
            'total_snapshots': len(snapshots),
            'keep': keep_count,
            'would_delete_count': len(to_delete),
            'deleted_count': len(deleted),
            'deleted': deleted,
            'dry_run': not args.apply,
        }
    except Exception as e:
        result = {
            'status': 'error',
            'error': str(e),
            'path': args.path,
        }
        print(json.dumps(result, indent=2))
        return 1

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        mode = "Dry-run" if result["dry_run"] else "Applied"
        print(f"{mode}: keep={result['keep']} total={result['total_snapshots']} prune={result['would_delete_count']}")
        print(f"History dir: {result['history_dir']}")
        if result["deleted"]:
            for item in result["deleted"]:
                print(f"- deleted {item}")
    return 0


async def cmd_google_voice_takeout_case_summary(args):
    """Show a concise summary for a Takeout case/download directory or acquisition manifest."""
    try:
        target = Path(args.path).expanduser().resolve()
        if target.is_file():
            manifest_path = target
            downloads_dir = target.parent
        else:
            downloads_dir = target
            manifest_path = downloads_dir / "takeout_acquisition_manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Acquisition manifest not found: {manifest_path}")

        payload = json.loads(manifest_path.read_text(encoding='utf-8'))
        history_dir = downloads_dir / "takeout_acquisition_history"
        history_count = len(list(history_dir.glob("*.json"))) if history_dir.exists() else 0
        capture_payload = dict(payload.get("capture") or {})
        browser_capture = dict(capture_payload.get("browser_capture") or {})
        drive_result = dict(payload.get("drive_result") or {})
        summary = {
            'status': payload.get('status'),
            'case_slug': payload.get('case_slug'),
            'delivery_destination': payload.get('delivery_destination'),
            'product_ids': list(payload.get('product_ids') or []),
            'downloads_dir': str(downloads_dir),
            'manifest_path': str(manifest_path),
            'history_dir': str(history_dir),
            'history_snapshot_count': history_count,
            'latest_event_type': (list(payload.get('events') or [])[-1:] or [{}])[0].get('type'),
            'final_archive_path': payload.get('final_archive_path'),
            'local_download_path': browser_capture.get('download_path'),
            'drive_download_path': (drive_result.get('download') or {}).get('output_path'),
            'drive_fallback_enabled': bool((payload.get('drive_fallback') or {}).get('enabled')),
        }
    except Exception as e:
        summary = {
            'status': 'error',
            'error': str(e),
            'path': args.path,
        }
        print(json.dumps(summary, indent=2))
        return 1

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"Case slug: {summary['case_slug'] or 'unknown'}")
        print(f"Status: {summary['status'] or 'unknown'}")
        print(f"Destination: {summary['delivery_destination'] or 'unknown'}")
        print(f"Products: {', '.join(summary['product_ids']) if summary['product_ids'] else 'none'}")
        print(f"Latest event: {summary['latest_event_type'] or 'none'}")
        print(f"History snapshots: {summary['history_snapshot_count']}")
        if summary['final_archive_path']:
            print(f"Final archive: {summary['final_archive_path']}")
        elif summary['drive_download_path']:
            print(f"Drive download: {summary['drive_download_path']}")
        elif summary['local_download_path']:
            print(f"Local download: {summary['local_download_path']}")
        print(f"Manifest: {summary['manifest_path']}")
    return 0


def _build_takeout_case_summary(target: Path) -> dict[str, Any]:
    if target.is_file():
        manifest_path = target
        downloads_dir = target.parent
    else:
        downloads_dir = target
        manifest_path = downloads_dir / "takeout_acquisition_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Acquisition manifest not found: {manifest_path}")

    payload = json.loads(manifest_path.read_text(encoding='utf-8'))
    history_dir = downloads_dir / "takeout_acquisition_history"
    history_count = len(list(history_dir.glob("*.json"))) if history_dir.exists() else 0
    capture_payload = dict(payload.get("capture") or {})
    browser_capture = dict(capture_payload.get("browser_capture") or {})
    drive_result = dict(payload.get("drive_result") or {})
    return {
        'status': payload.get('status'),
        'case_slug': payload.get('case_slug'),
        'delivery_destination': payload.get('delivery_destination'),
        'product_ids': list(payload.get('product_ids') or []),
        'downloads_dir': str(downloads_dir),
        'manifest_path': str(manifest_path),
        'history_dir': str(history_dir),
        'history_snapshot_count': history_count,
        'latest_event_type': (list(payload.get('events') or [])[-1:] or [{}])[0].get('type'),
        'final_archive_path': payload.get('final_archive_path'),
        'local_download_path': browser_capture.get('download_path'),
        'drive_download_path': (drive_result.get('download') or {}).get('output_path'),
        'drive_fallback_enabled': bool((payload.get('drive_fallback') or {}).get('enabled')),
    }


def _render_takeout_case_report(summary: dict[str, Any], fmt: str) -> str:
    products = ", ".join(summary.get('product_ids') or []) or "none"
    archive_path = (
        summary.get('final_archive_path')
        or summary.get('drive_download_path')
        or summary.get('local_download_path')
        or ""
    )
    if fmt == 'markdown':
        lines = [
            f"# Google Voice Takeout Case Report: {summary.get('case_slug') or 'unknown'}",
            "",
            f"- Status: {summary.get('status') or 'unknown'}",
            f"- Destination: {summary.get('delivery_destination') or 'unknown'}",
            f"- Products: {products}",
            f"- Latest event: {summary.get('latest_event_type') or 'none'}",
            f"- History snapshots: {summary.get('history_snapshot_count') or 0}",
            f"- Drive fallback enabled: {'yes' if summary.get('drive_fallback_enabled') else 'no'}",
            f"- Manifest: {summary.get('manifest_path') or ''}",
            f"- Downloads dir: {summary.get('downloads_dir') or ''}",
        ]
        if archive_path:
            lines.append(f"- Archive: {archive_path}")
        return "\n".join(lines) + "\n"

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Google Voice Takeout Case Report</title>
    <style>
      body {{ font-family: Georgia, serif; margin: 2rem auto; max-width: 860px; line-height: 1.5; color: #1f2937; }}
      h1 {{ font-size: 1.8rem; }}
      dl {{ display: grid; grid-template-columns: 220px 1fr; gap: 0.75rem 1rem; }}
      dt {{ font-weight: 700; }}
      dd {{ margin: 0; word-break: break-word; }}
      .muted {{ color: #6b7280; }}
    </style>
  </head>
  <body>
    <h1>Google Voice Takeout Case Report</h1>
    <p class="muted">{summary.get('case_slug') or 'unknown'}</p>
    <dl>
      <dt>Status</dt><dd>{summary.get('status') or 'unknown'}</dd>
      <dt>Destination</dt><dd>{summary.get('delivery_destination') or 'unknown'}</dd>
      <dt>Products</dt><dd>{products}</dd>
      <dt>Latest event</dt><dd>{summary.get('latest_event_type') or 'none'}</dd>
      <dt>History snapshots</dt><dd>{summary.get('history_snapshot_count') or 0}</dd>
      <dt>Drive fallback</dt><dd>{"enabled" if summary.get('drive_fallback_enabled') else "disabled"}</dd>
      <dt>Manifest</dt><dd>{summary.get('manifest_path') or ''}</dd>
      <dt>Downloads dir</dt><dd>{summary.get('downloads_dir') or ''}</dd>
      <dt>Archive</dt><dd>{archive_path or 'not yet available'}</dd>
    </dl>
  </body>
</html>
"""


def _resolve_takeout_bundle_formats(raw_formats: list[str] | None) -> list[str]:
    formats = list(raw_formats or [])
    if not formats:
        return ["dir"]
    resolved: list[str] = []
    for fmt in formats:
        if fmt not in resolved:
            resolved.append(fmt)
    if "dir" not in resolved:
        resolved.insert(0, "dir")
    return resolved


def _create_takeout_bundle_zip(bundle_dir: Path) -> Path:
    zip_path = bundle_dir.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for child in sorted(bundle_dir.rglob("*")):
            if child.is_file():
                archive.write(child, child.relative_to(bundle_dir.parent))
    return zip_path


def _build_takeout_bundle_rows(
    summary: dict[str, Any],
    copied_history: list[str],
    markdown_report: Path,
    html_report: Path,
    manifest_copy: Path,
) -> list[dict[str, Any]]:
    archive_path = (
        summary.get('final_archive_path')
        or summary.get('drive_download_path')
        or summary.get('local_download_path')
        or ''
    )
    rows: list[dict[str, Any]] = [
        {
            'record_type': 'case_summary',
            'case_slug': str(summary.get('case_slug') or ''),
            'status': str(summary.get('status') or ''),
            'delivery_destination': str(summary.get('delivery_destination') or ''),
            'latest_event_type': str(summary.get('latest_event_type') or ''),
            'history_snapshot_count': int(summary.get('history_snapshot_count') or 0),
            'product_ids_json': json.dumps(list(summary.get('product_ids') or []), ensure_ascii=False),
            'artifact_kind': 'manifest',
            'artifact_path': str(manifest_copy),
            'artifact_name': manifest_copy.name,
            'archive_path': str(archive_path),
            'raw_json': json.dumps(summary, ensure_ascii=False),
        },
        {
            'record_type': 'report',
            'case_slug': str(summary.get('case_slug') or ''),
            'status': str(summary.get('status') or ''),
            'delivery_destination': str(summary.get('delivery_destination') or ''),
            'latest_event_type': str(summary.get('latest_event_type') or ''),
            'history_snapshot_count': int(summary.get('history_snapshot_count') or 0),
            'product_ids_json': json.dumps(list(summary.get('product_ids') or []), ensure_ascii=False),
            'artifact_kind': 'markdown_report',
            'artifact_path': str(markdown_report),
            'artifact_name': markdown_report.name,
            'archive_path': str(archive_path),
            'raw_json': json.dumps({'report_format': 'markdown'}, ensure_ascii=False),
        },
        {
            'record_type': 'report',
            'case_slug': str(summary.get('case_slug') or ''),
            'status': str(summary.get('status') or ''),
            'delivery_destination': str(summary.get('delivery_destination') or ''),
            'latest_event_type': str(summary.get('latest_event_type') or ''),
            'history_snapshot_count': int(summary.get('history_snapshot_count') or 0),
            'product_ids_json': json.dumps(list(summary.get('product_ids') or []), ensure_ascii=False),
            'artifact_kind': 'html_report',
            'artifact_path': str(html_report),
            'artifact_name': html_report.name,
            'archive_path': str(archive_path),
            'raw_json': json.dumps({'report_format': 'html'}, ensure_ascii=False),
        },
    ]
    for snapshot_path_str in copied_history:
        snapshot_path = Path(snapshot_path_str)
        try:
            snapshot_payload = json.loads(snapshot_path.read_text(encoding='utf-8'))
        except Exception:
            snapshot_payload = {}
        rows.append(
            {
                'record_type': 'history_snapshot',
                'case_slug': str(summary.get('case_slug') or ''),
                'status': str(snapshot_payload.get('status') or ''),
                'delivery_destination': str(summary.get('delivery_destination') or ''),
                'latest_event_type': str((list(snapshot_payload.get('events') or [])[-1:] or [{}])[0].get('type') or ''),
                'history_snapshot_count': int(summary.get('history_snapshot_count') or 0),
                'product_ids_json': json.dumps(list(snapshot_payload.get('product_ids') or summary.get('product_ids') or []), ensure_ascii=False),
                'artifact_kind': 'history_snapshot',
                'artifact_path': str(snapshot_path),
                'artifact_name': snapshot_path.name,
                'archive_path': str(snapshot_payload.get('final_archive_path') or archive_path),
                'raw_json': json.dumps(snapshot_payload, ensure_ascii=False),
            }
        )
    return rows


def _create_takeout_bundle_parquet(
    bundle_dir: Path,
    summary: dict[str, Any],
    copied_history: list[str],
    markdown_report: Path,
    html_report: Path,
    manifest_copy: Path,
) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq

    parquet_path = bundle_dir / "takeout-case-bundle.parquet"
    rows = _build_takeout_bundle_rows(
        summary=summary,
        copied_history=copied_history,
        markdown_report=markdown_report,
        html_report=html_report,
        manifest_copy=manifest_copy,
    )
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, parquet_path)
    return parquet_path


def _create_takeout_bundle_car(bundle_dir: Path) -> tuple[Path, dict[str, Any]]:
    try:
        from ipfs_kit_py.mcp.storage_manager.formats import CARManager
    except ImportError:
        import importlib.util

        package_root = Path(__file__).resolve().parents[2]
        car_manager_path = (
            package_root
            / "ipfs_kit_py"
            / "ipfs_kit_py"
            / "mcp"
            / "storage_manager"
            / "formats"
            / "car_manager.py"
        )
        spec = importlib.util.spec_from_file_location(
            "takeout_bundle_car_manager",
            car_manager_path,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load CAR manager from {car_manager_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        CARManager = module.CARManager

    car_path = bundle_dir.with_suffix(".car")
    manager = CARManager()
    result = manager.create_car(str(bundle_dir), str(car_path))
    if not result.get("success"):
        raise RuntimeError(str(result.get("error") or "Failed to create CAR bundle"))
    return car_path, result


async def cmd_google_voice_takeout_case_report(args):
    """Export a markdown or HTML report for a Takeout case/download directory or manifest."""
    try:
        target = Path(args.path).expanduser().resolve()
        summary = _build_takeout_case_summary(target)
        rendered = _render_takeout_case_report(summary, args.format)
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding='utf-8')
    except Exception as e:
        payload = {
            'status': 'error',
            'error': str(e),
            'path': args.path,
            'output': args.output,
        }
        print(json.dumps(payload, indent=2))
        return 1

    print(f"Takeout case report saved to {output_path}")
    return 0


async def cmd_google_voice_takeout_case_bundle(args):
    """Collect the latest manifest, history snapshots, and case reports into one archival folder."""
    try:
        target = Path(args.path).expanduser().resolve()
        summary = _build_takeout_case_summary(target)
        case_slug = str(summary.get('case_slug') or 'takeout-case')
        requested_formats = _resolve_takeout_bundle_formats(getattr(args, 'bundle_format', None))
        output_root = Path(args.output_dir).expanduser().resolve()
        bundle_dir = output_root / case_slug
        bundle_dir.mkdir(parents=True, exist_ok=True)

        manifest_path = Path(summary['manifest_path'])
        downloads_dir = Path(summary['downloads_dir'])
        history_dir = Path(summary['history_dir'])
        manifest_copy = bundle_dir / manifest_path.name
        shutil.copy2(manifest_path, manifest_copy)

        copied_history: list[str] = []
        if history_dir.exists():
            destination_history = bundle_dir / "takeout_acquisition_history"
            destination_history.mkdir(parents=True, exist_ok=True)
            snapshots = sorted(history_dir.glob("*.json"))[-max(0, int(args.history_limit)) :]
            for snapshot in snapshots:
                target_path = destination_history / snapshot.name
                shutil.copy2(snapshot, target_path)
                copied_history.append(str(target_path))

        markdown_report = bundle_dir / "takeout-case-report.md"
        html_report = bundle_dir / "takeout-case-report.html"
        markdown_report.write_text(_render_takeout_case_report(summary, "markdown"), encoding='utf-8')
        html_report.write_text(_render_takeout_case_report(summary, "html"), encoding='utf-8')

        bundle_artifacts: dict[str, Any] = {
            'dir': str(bundle_dir),
        }
        if 'zip' in requested_formats:
            bundle_artifacts['zip'] = str(_create_takeout_bundle_zip(bundle_dir))
        if 'parquet' in requested_formats:
            bundle_artifacts['parquet'] = str(
                _create_takeout_bundle_parquet(
                    bundle_dir=bundle_dir,
                    summary=summary,
                    copied_history=copied_history,
                    markdown_report=markdown_report,
                    html_report=html_report,
                    manifest_copy=manifest_copy,
                )
            )
        if 'car' in requested_formats:
            car_path, car_result = _create_takeout_bundle_car(bundle_dir)
            bundle_artifacts['car'] = str(car_path)
            bundle_artifacts['car_result'] = car_result

        payload = {
            'status': 'success',
            'case_slug': case_slug,
            'bundle_formats': requested_formats,
            'bundle_dir': str(bundle_dir),
            'bundle_artifacts': bundle_artifacts,
            'manifest_copy': str(manifest_copy),
            'history_snapshot_count': len(copied_history),
            'history_copies': copied_history,
            'markdown_report': str(markdown_report),
            'html_report': str(html_report),
            'downloads_dir': str(downloads_dir),
        }
    except Exception as e:
        payload = {
            'status': 'error',
            'error': str(e),
            'path': args.path,
            'output_dir': args.output_dir,
        }
        print(json.dumps(payload, indent=2))
        return 1

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


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
        'google-voice': cmd_google_voice,
        'google-voice-vault': cmd_google_voice_vault,
        'google-voice-data-export': cmd_google_voice_data_export,
        'google-voice-watch': cmd_google_voice_watch,
        'google-voice-takeout-url': cmd_google_voice_takeout_url,
        'google-voice-takeout-open': cmd_google_voice_takeout_open,
        'google-voice-takeout-capture': cmd_google_voice_takeout_capture,
        'google-voice-takeout-source': cmd_google_voice_takeout_source,
        'google-voice-takeout-poll': cmd_google_voice_takeout_poll,
        'google-voice-takeout-drive': cmd_google_voice_takeout_drive,
        'google-voice-takeout-status': cmd_google_voice_takeout_status,
        'google-voice-takeout-doctor': cmd_google_voice_takeout_doctor,
        'google-voice-takeout-history': cmd_google_voice_takeout_history,
        'google-voice-takeout-prune': cmd_google_voice_takeout_prune,
        'google-voice-takeout-case-summary': cmd_google_voice_takeout_case_summary,
        'google-voice-takeout-case-report': cmd_google_voice_takeout_case_report,
        'google-voice-takeout-case-bundle': cmd_google_voice_takeout_case_bundle,
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
