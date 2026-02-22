"""Email analysis engine — canonical domain module.

Provides functions for analyzing email export files.

Usage::

    from ipfs_datasets_py.processors.multimedia import email_analyze_export
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any, Dict, List

import anyio

logger = logging.getLogger(__name__)


async def email_analyze_export(file_path: str) -> Dict[str, Any]:
    """Analyze an email export file and generate statistics.

    Args:
        file_path: Path to email export file (JSON format).

    Returns:
        Dict with status, file_path, total_emails, date_range, top_senders,
        top_recipients, attachment_stats, average_body_length, thread_count,
        threads_with_replies. On failure: status='error', error=<message>.
    """
    try:
        def _read_file() -> Any:
            with open(file_path, "r", encoding="utf-8") as fh:
                return json.load(fh)

        data = await anyio.to_thread.run_sync(_read_file)

        if "emails" not in data:
            return {
                "status": "error",
                "error": "Invalid export file format. Expected 'emails' key.",
                "file_path": file_path,
            }

        emails: List[Dict[str, Any]] = data["emails"]

        if not emails:
            return {
                "status": "success",
                "file_path": file_path,
                "total_emails": 0,
                "message": "No emails to analyze",
            }

        senders: list[str] = []
        recipients: list[str] = []
        dates: list[str] = []
        lengths: list[int] = []
        attachments_count = 0
        total_attachment_size = 0
        threads: dict[str, list[str]] = {}

        for email in emails:
            if email.get("from"):
                senders.append(email["from"])
            if email.get("to"):
                recipients.append(email["to"])
            if email.get("date"):
                try:
                    dates.append(email["date"])
                except (KeyError, TypeError, ValueError):
                    pass

            body = email.get("body_text", "") or email.get("body_html", "")
            lengths.append(len(body))

            if email.get("attachments"):
                attachments_count += len(email["attachments"])
                for att in email["attachments"]:
                    total_attachment_size += att.get("size", 0)

            in_reply_to = email.get("in_reply_to", "")
            if in_reply_to:
                thread_id = in_reply_to
                threads.setdefault(thread_id, []).append(
                    email.get("message_id_header", "")
                )

        sender_counts = Counter(senders)
        recipient_counts = Counter(recipients)

        date_range = None
        if dates:
            sorted_dates = sorted(dates)
            date_range = {"earliest": sorted_dates[0], "latest": sorted_dates[-1]}

        avg_length = sum(lengths) / len(lengths) if lengths else 0

        return {
            "status": "success",
            "file_path": file_path,
            "total_emails": len(emails),
            "date_range": date_range,
            "top_senders": [
                {"sender": s, "count": c} for s, c in sender_counts.most_common(10)
            ],
            "top_recipients": [
                {"recipient": r, "count": c}
                for r, c in recipient_counts.most_common(10)
            ],
            "attachment_stats": {
                "total_attachments": attachments_count,
                "total_size_bytes": total_attachment_size,
                "average_per_email": (
                    attachments_count / len(emails) if emails else 0
                ),
            },
            "average_body_length": int(avg_length),
            "thread_count": len(threads),
            "threads_with_replies": len(
                [t for t in threads.values() if len(t) > 1]
            ),
        }

    except FileNotFoundError:
        return {
            "status": "error",
            "error": f"File not found: {file_path}",
            "file_path": file_path,
        }
    except json.JSONDecodeError:
        return {
            "status": "error",
            "error": "Invalid JSON file",
            "file_path": file_path,
        }
    except Exception as exc:
        logger.error("Failed to analyze email export: %s", exc)
        return {"status": "error", "error": str(exc), "file_path": file_path}


async def email_search_export(
    file_path: str,
    query: str,
    field: str = "all",
) -> Dict[str, Any]:
    """Search emails in an export file.

    Args:
        file_path: Path to email export file (JSON format).
        query: Search query string.
        field: Field to search — ``all``, ``subject``, ``from``, ``to``,
            ``body`` (default: ``all``).

    Returns:
        Dict with status, file_path, query, field, match_count, matches.
    """
    try:
        def _read_file() -> Any:
            with open(file_path, "r", encoding="utf-8") as fh:
                return json.load(fh)

        data = await anyio.to_thread.run_sync(_read_file)

        if "emails" not in data:
            return {
                "status": "error",
                "error": "Invalid export file format. Expected 'emails' key.",
                "file_path": file_path,
            }

        emails = data["emails"]
        query_lower = query.lower()
        matches: list[Dict[str, Any]] = []

        for email in emails:
            match = False
            if field == "all":
                search_text = " ".join(
                    [
                        str(email.get("subject", "")),
                        str(email.get("from", "")),
                        str(email.get("to", "")),
                        str(email.get("body_text", "")),
                        str(email.get("body_html", "")),
                    ]
                ).lower()
                match = query_lower in search_text
            elif field == "subject":
                match = query_lower in str(email.get("subject", "")).lower()
            elif field == "from":
                match = query_lower in str(email.get("from", "")).lower()
            elif field == "to":
                match = query_lower in str(email.get("to", "")).lower()
            elif field == "body":
                body_text = str(email.get("body_text", "")) + str(
                    email.get("body_html", "")
                )
                match = query_lower in body_text.lower()

            if match:
                matches.append(email)

        return {
            "status": "success",
            "file_path": file_path,
            "query": query,
            "field": field,
            "match_count": len(matches),
            "matches": matches,
        }

    except FileNotFoundError:
        return {
            "status": "error",
            "error": f"File not found: {file_path}",
            "file_path": file_path,
        }
    except json.JSONDecodeError:
        return {
            "status": "error",
            "error": "Invalid JSON file",
            "file_path": file_path,
        }
    except Exception as exc:
        logger.error("Failed to search email export: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "file_path": file_path,
            "query": query,
        }
