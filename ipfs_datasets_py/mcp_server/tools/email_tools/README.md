# Email Tools

MCP tools for connecting to email servers (IMAP/POP3), listing messages, exporting emails,
and analysing email data.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `email_connect.py` | `connect_imap()`, `connect_pop3()`, `list_folders()`, `test_connection()` | Connect to IMAP/POP3 servers, list mail folders |
| `email_export.py` | `export_emails()`, `export_folder()`, `parse_eml_file()` | Export emails to JSON/JSONL/CSV; parse `.eml` files |
| `email_analyze.py` | `analyze_inbox()`, `sender_statistics()`, `attachment_summary()` | Volume analysis, sender stats, attachment types |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.email_tools import (
    connect_imap, export_emails, analyze_inbox
)

# Connect to IMAP
conn = await connect_imap(
    host="imap.gmail.com",
    port=993,
    username="user@gmail.com",
    password="app_password",
    use_ssl=True
)

# Export a folder
export = await export_emails(
    connection_id=conn["connection_id"],
    folder="INBOX",
    output_path="/data/emails.jsonl",
    output_format="jsonl",
    date_after="2024-01-01",
    max_count=1000
)

# Analyse inbox
analysis = await analyze_inbox(
    connection_id=conn["connection_id"],
    folder="INBOX"
)
# Returns: {"total_messages": 5231, "top_senders": [...], "attachments": {...}}
```

## Dependencies

- `imaplib` / `poplib` — stdlib email clients
- Standard library: `email`, `mailbox`

## Status

| Tool | Status |
|------|--------|
| `email_connect` | ✅ Production ready |
| `email_export` | ✅ Production ready |
| `email_analyze` | ✅ Production ready |
