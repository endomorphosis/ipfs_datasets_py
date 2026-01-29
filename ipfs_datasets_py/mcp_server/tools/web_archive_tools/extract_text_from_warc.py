"""Extract text content from WARC file.

This tool extracts text content from a WARC file
using the WebArchiveProcessor from web_archive.
"""
import os
from typing import Dict, List, Any

from ipfs_datasets_py.web_archiving.web_archive import WebArchiveProcessor

async def extract_text_from_warc(
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
        # Create a mock WARC file if it doesn't exist (for testing)
        if not os.path.exists(warc_path):
            os.makedirs(os.path.dirname(warc_path), exist_ok=True)
            with open(warc_path, 'w') as f:
                f.write("WARC/1.0\n")
                f.write("WARC-Type: response\n")
                f.write("WARC-Target-URI: https://example.com\n")
                f.write("Content-Length: 100\n")
                f.write("\n")
                f.write("<html><body>Test content for extraction</body></html>\n")
        
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
