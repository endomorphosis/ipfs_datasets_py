# Email Ingestion and Analysis - Usage Guide

This guide demonstrates how to use the email ingestion and analysis features in IPFS Datasets Python.

## Integration Pattern

The email functionality follows the correct integration pattern where all interfaces (CLI, MCP tools, JavaScript SDK) import directly from the core Python package:

```
Python Package (multimedia/email_processor.py)
    ├── EmailProcessor class
    └── create_email_processor factory
         ↓
    ┌────┼────┬────────┐
    │         │        │
   CLI    MCP Tools  JS SDK
```

**All interfaces are peer consumers of the core package**, not hierarchical dependencies.

## Overview

The email functionality provides a unified interface for:
- **IMAP** server connections (e.g., Gmail, Outlook, Yahoo)
- **POP3** server connections
- **.eml file** parsing and analysis
- Email export in multiple formats (JSON, HTML, CSV, TXT)
- Email analysis and statistics
- Email search and filtering

## Installation

### Basic Installation

```bash
pip install ipfs_datasets_py
```

### With Email Support (Optional Dependencies)

```bash
pip install ipfs_datasets_py[email]
```

This installs optional dependencies like `beautifulsoup4` for enhanced HTML email parsing.

## Authentication Setup

### Environment Variables (Recommended)

Set your email credentials as environment variables:

```bash
export EMAIL_USER="your.email@gmail.com"
export EMAIL_PASS="your_app_password"
```

**Important for Gmail Users:**
- You MUST use an [App Password](https://support.google.com/accounts/answer/185833), not your regular password
- Enable 2-factor authentication on your Google account first
- Generate an app-specific password for this application

## CLI Usage

### 1. Test Email Server Connection

Test your IMAP or POP3 connection:

```bash
# Test IMAP connection (uses EMAIL_USER and EMAIL_PASS env vars)
ipfs-datasets email test --server imap.gmail.com --protocol imap

# Test with explicit credentials
ipfs-datasets email test \
  --server imap.gmail.com \
  --username your.email@gmail.com \
  --password your_app_password

# Test POP3 connection
ipfs-datasets email test --server pop.gmail.com --protocol pop3
```

### 2. List Mailbox Folders

List all available folders in your mailbox (IMAP only):

```bash
# List folders
ipfs-datasets email folders --server imap.gmail.com

# Save folder list to JSON
ipfs-datasets email folders --server imap.gmail.com --output folders.json
```

### 3. Export Emails

Export emails from a folder:

```bash
# Export inbox to JSON (default format)
ipfs-datasets email export \
  --server imap.gmail.com \
  --folder INBOX \
  --output inbox_export.json

# Export with limit
ipfs-datasets email export \
  --server imap.gmail.com \
  --folder INBOX \
  --limit 100 \
  --output inbox_100.json

# Export to HTML
ipfs-datasets email export \
  --server imap.gmail.com \
  --folder INBOX \
  --format html \
  --output inbox.html

# Export to CSV
ipfs-datasets email export \
  --server imap.gmail.com \
  --folder "Sent Mail" \
  --format csv \
  --output sent_emails.csv

# Export with search criteria (IMAP only)
ipfs-datasets email export \
  --server imap.gmail.com \
  --folder INBOX \
  --search "UNSEEN" \
  --output unread_emails.json
```

**IMAP Search Criteria Examples:**
- `ALL` - All messages
- `UNSEEN` - Unread messages
- `SEEN` - Read messages
- `FROM "sender@example.com"` - From specific sender
- `SUBJECT "meeting"` - Subject contains "meeting"
- `SINCE "01-Jan-2024"` - Since specific date
- `BEFORE "31-Dec-2023"` - Before specific date

### 4. Parse .eml Files

Parse individual .eml files:

```bash
# Parse .eml file
ipfs-datasets email parse message.eml

# Parse and save to JSON
ipfs-datasets email parse message.eml --output parsed.json

# Parse without extracting attachment metadata
ipfs-datasets email parse message.eml --no-attachments
```

### 5. Fetch Emails (No Export)

Fetch emails without saving to file:

```bash
# Fetch 10 most recent emails
ipfs-datasets email fetch \
  --server imap.gmail.com \
  --folder INBOX \
  --limit 10

# Fetch and save to JSON
ipfs-datasets email fetch \
  --server imap.gmail.com \
  --folder INBOX \
  --limit 50 \
  --output emails.json
```

### 6. Analyze Email Export

Generate statistics from an export file:

```bash
# Analyze export
ipfs-datasets email analyze inbox_export.json

# Save analysis to JSON
ipfs-datasets email analyze inbox_export.json --output analysis.json
```

**Analysis includes:**
- Total email count
- Date range (earliest/latest)
- Top senders and recipients
- Attachment statistics
- Average email length
- Thread/conversation count

### 7. Search Emails

Search within an export file:

```bash
# Search all fields
ipfs-datasets email search inbox_export.json "project update"

# Search specific field
ipfs-datasets email search inbox_export.json "meeting" --field subject

# Search and save results
ipfs-datasets email search inbox_export.json "urgent" --output results.json
```

**Search fields:**
- `all` - Search all fields (default)
- `subject` - Search subject only
- `from` - Search sender only
- `to` - Search recipients only
- `body` - Search email body only

## Python Package Usage

### Basic Email Processing

```python
import anyio
from ipfs_datasets_py.multimedia import EmailProcessor, create_email_processor

async def main():
    # Create IMAP processor
    processor = create_email_processor(
        protocol='imap',
        server='imap.gmail.com',
        username='your.email@gmail.com',
        password='your_app_password'
    )
    
    # Connect to server
    await processor.connect()
    
    # List folders
    folders_result = await processor.list_folders()
    print(f"Found {folders_result['folder_count']} folders")
    
    # Fetch emails
    emails_result = await processor.fetch_emails(
        folder='INBOX',
        limit=10,
        search_criteria='UNSEEN'
    )
    
    print(f"Fetched {emails_result['email_count']} emails")
    for email in emails_result['emails']:
        print(f"  - {email['subject']} from {email['from']}")
    
    # Export to file
    export_result = await processor.export_folder(
        folder='INBOX',
        output_path='inbox_export.json',
        format='json',
        limit=100
    )
    
    print(f"Exported {export_result['email_count']} emails to {export_result['output_path']}")
    
    # Disconnect
    await processor.disconnect()

# Run
anyio.run(main)
```

### Parse .eml Files

```python
import anyio
from ipfs_datasets_py.multimedia import EmailProcessor

async def parse_eml():
    processor = EmailProcessor(protocol='eml')
    
    result = await processor.parse_eml_file('message.eml')
    
    if result['status'] == 'success':
        email = result['email']
        print(f"Subject: {email['subject']}")
        print(f"From: {email['from']}")
        print(f"To: {email['to']}")
        print(f"Date: {email['date']}")
        print(f"Attachments: {len(email['attachments'])}")
        print(f"\nBody:\n{email['body_text']}")

anyio.run(parse_eml)
```

### Using Environment Variables

```python
import os
import anyio
from ipfs_datasets_py.multimedia import EmailProcessor

# Set environment variables
os.environ['EMAIL_USER'] = 'your.email@gmail.com'
os.environ['EMAIL_PASS'] = 'your_app_password'

async def main():
    # Credentials automatically loaded from environment
    processor = EmailProcessor(
        protocol='imap',
        server='imap.gmail.com'
    )
    
    await processor.connect()
    result = await processor.fetch_emails(folder='INBOX', limit=5)
    await processor.disconnect()
    
    return result

result = anyio.run(main)
print(f"Fetched {result['email_count']} emails")
```

## MCP Server Tool Usage

Use the email tools via the MCP server:

```python
import anyio
from ipfs_datasets_py.mcp_server.tools.email_tools import (
    email_test_connection,
    email_list_folders,
    email_export_folder,
    email_parse_eml,
    email_fetch_emails,
    email_analyze_export,
    email_search_export
)

async def main():
    # Test connection
    test_result = await email_test_connection(
        protocol='imap',
        server='imap.gmail.com',
        username='your.email@gmail.com',
        password='your_app_password'
    )
    print(f"Connection test: {test_result['status']}")
    
    # List folders
    folders_result = await email_list_folders(
        server='imap.gmail.com',
        username='your.email@gmail.com',
        password='your_app_password'
    )
    print(f"Folders: {folders_result['folder_count']}")
    
    # Export folder
    export_result = await email_export_folder(
        folder='INBOX',
        server='imap.gmail.com',
        username='your.email@gmail.com',
        password='your_app_password',
        output_path='inbox.json',
        format='json',
        limit=50
    )
    print(f"Exported: {export_result['email_count']} emails")
    
    # Parse .eml file
    parse_result = await email_parse_eml('message.eml')
    if parse_result['status'] == 'success':
        print(f"Parsed: {parse_result['email']['subject']}")
    
    # Analyze export
    analysis = await email_analyze_export('inbox.json')
    print(f"Total emails: {analysis['total_emails']}")
    print(f"Top sender: {analysis['top_senders'][0] if analysis['top_senders'] else 'None'}")
    
    # Search export
    search_result = await email_search_export(
        file_path='inbox.json',
        query='meeting',
        field='subject'
    )
    print(f"Search matches: {search_result['match_count']}")

anyio.run(main)
```

## Common Email Server Settings

### Gmail (IMAP)
- **Server:** `imap.gmail.com`
- **Port:** 993 (SSL)
- **Auth:** App Password required (not regular password)
- **2FA:** Must be enabled

### Gmail (POP3)
- **Server:** `pop.gmail.com`
- **Port:** 995 (SSL)
- **Note:** Must enable POP3 in Gmail settings

### Outlook/Hotmail (IMAP)
- **Server:** `outlook.office365.com`
- **Port:** 993 (SSL)

### Yahoo Mail (IMAP)
- **Server:** `imap.mail.yahoo.com`
- **Port:** 993 (SSL)
- **Note:** Generate app password in Yahoo Account Security

### Office 365 (IMAP)
- **Server:** `outlook.office365.com`
- **Port:** 993 (SSL)

## Export Format Examples

### JSON Format
```json
{
  "metadata": {
    "folder": "INBOX",
    "export_date": "2024-01-01T12:00:00",
    "email_count": 2,
    "protocol": "imap",
    "server": "imap.gmail.com"
  },
  "emails": [
    {
      "subject": "Meeting Tomorrow",
      "from": "alice@example.com",
      "to": "bob@example.com",
      "date": "2024-01-01T10:00:00",
      "body_text": "Let's meet tomorrow at 3pm.",
      "body_html": "",
      "attachments": [],
      "headers": { ... },
      "message_id_header": "<msg1@example.com>",
      "in_reply_to": "",
      "references": ""
    }
  ]
}
```

### CSV Format
Simplified format with key fields:
- Date
- From
- To
- Subject
- Body (truncated)

### HTML Format
Styled HTML view with:
- Email list with subjects
- Sender/recipient metadata
- Full body content
- Attachment information

### TXT Format
Plain text format with:
- Email separator lines
- All metadata
- Full text body
- One email per section

## Tips and Best Practices

1. **Use App Passwords**: Never use your regular email password. Always create app-specific passwords.

2. **Limit Results**: Start with small limits (`--limit 10`) when testing to avoid long wait times.

3. **Search First**: Use IMAP search criteria to filter before exporting large mailboxes.

4. **Choose Format Wisely**:
   - JSON: Best for programmatic access and analysis
   - HTML: Best for human-readable archives
   - CSV: Best for spreadsheet import
   - TXT: Best for simple text viewing

5. **Handle Rate Limits**: Some email providers rate limit connections. Add delays between large exports.

6. **Secure Credentials**: Use environment variables or encrypted config files, never hardcode passwords.

7. **Thread Tracking**: Use `in_reply_to` and `references` headers to reconstruct email threads.

## Troubleshooting

### Connection Errors

**Problem:** "Connection refused" or timeout
- **Solution:** Check server hostname and port. Verify SSL is enabled (default).

**Problem:** "Authentication failed"
- **Solution:** 
  - For Gmail: Use app password, not regular password
  - Verify 2FA is enabled
  - Check username format (full email address)

**Problem:** "IMAP/POP3 not enabled"
- **Solution:** Enable IMAP/POP3 in your email provider's settings

### Export Issues

**Problem:** Large exports timing out
- **Solution:** Use `--limit` to export in batches

**Problem:** Missing emails
- **Solution:** Check `--search` criteria, verify folder name

**Problem:** Encoding errors in body
- **Solution:** Email processor handles encoding automatically, but some rare encodings may have issues

## Security Considerations

1. **App Passwords**: Always use app-specific passwords, never your main account password
2. **Secure Storage**: Store credentials in environment variables or secure vaults
3. **SSL/TLS**: Always use SSL (enabled by default)
4. **Minimal Permissions**: Use read-only IMAP access when possible
5. **Local Storage**: Exported emails contain sensitive data - protect them accordingly
6. **Clean Up**: Delete temporary export files after processing

## Advanced Usage

### Batch Processing Multiple Folders

```python
import anyio
from ipfs_datasets_py.multimedia import EmailProcessor

async def export_all_folders():
    processor = EmailProcessor(
        protocol='imap',
        server='imap.gmail.com'
    )
    
    await processor.connect()
    
    # Get folder list
    folders_result = await processor.list_folders()
    
    for folder_info in folders_result['folders']:
        folder_name = folder_info['name']
        
        # Skip system folders
        if folder_name.startswith('['):
            continue
        
        print(f"Exporting {folder_name}...")
        
        await processor.export_folder(
            folder=folder_name,
            output_path=f'exports/{folder_name}.json',
            format='json',
            limit=None  # Export all
        )
    
    await processor.disconnect()

anyio.run(export_all_folders)
```

### Combining Analysis and Search

```python
import anyio
from ipfs_datasets_py.mcp_server.tools.email_tools import (
    email_analyze_export,
    email_search_export
)

async def analyze_and_filter():
    # First, analyze
    analysis = await email_analyze_export('inbox_export.json')
    
    print(f"Total emails: {analysis['total_emails']}")
    print(f"Date range: {analysis['date_range']}")
    
    # Find emails from top sender
    if analysis['top_senders']:
        top_sender = analysis['top_senders'][0]['sender']
        
        search_result = await email_search_export(
            file_path='inbox_export.json',
            query=top_sender,
            field='from'
        )
        
        print(f"\nEmails from {top_sender}: {search_result['match_count']}")

anyio.run(analyze_and_filter)
```

## See Also

- [Discord Integration](discord_usage_examples.md) - Similar message ingestion for Discord
- [Finance Data Tools](finance_usage_examples.md) - Financial data collection and analysis
- [Multimedia Processing](../../ipfs_datasets_py/multimedia/README.md) - Overview of multimedia tools
- [MCP Server](../../ipfs_datasets_py/mcp_server/README.md) - Model Context Protocol server documentation
