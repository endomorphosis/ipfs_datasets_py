"""Extract text content from WARC file.

This tool extracts text content from a WARC file
using the WebArchiveProcessor from web_archive.
"""
import os
from typing import Dict, List, Any

from ....web_archive import WebArchiveProcessor

def extract_text_from_warc(
    warc_path: str
) -> Dict[str, Any]:
    """Extract text content from a WARC file.

    Args:
        warc_path: Path to the WARC file

    Returns:
        Dict containing:
            - status: "success" or "error"
            - records: List of records with URI and text content (if successful)
            - error: Error message (if failed)
    """
    processor = WebArchiveProcessor()

    try:
        records = processor.extract_text_from_warc(warc_path)
        return {
            "status": "success",
            "records": records
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
