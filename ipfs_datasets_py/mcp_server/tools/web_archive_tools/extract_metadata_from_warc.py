"""Extract metadata from WARC file.

This tool extracts metadata from a WARC file
using the WebArchiveProcessor from web_archive_utils.
"""
import os
from typing import Dict, Any

from ....web_archive import WebArchiveProcessor

def extract_metadata_from_warc(
    warc_path: str
) -> Dict[str, Any]:
    """Extract metadata from a WARC file.

    Args:
        warc_path: Path to the WARC file

    Returns:
        Dict containing:
            - status: "success" or "error"
            - metadata: Metadata about the WARC file (if successful)
            - error: Error message (if failed)
    """
    processor = WebArchiveProcessor()

    try:
        metadata = processor.extract_metadata_from_warc(warc_path)
        return {
            "status": "success",
            "metadata": metadata
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
