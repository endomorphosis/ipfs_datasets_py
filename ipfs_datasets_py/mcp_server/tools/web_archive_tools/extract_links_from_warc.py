"""Extract links from WARC file.

This tool extracts links from a WARC file
using the WebArchiveProcessor from web_archive_utils.
"""
import os
from typing import Dict, List, Any

from ....web_archive_utils import WebArchiveProcessor

def extract_links_from_warc(
    warc_path: str
) -> Dict[str, Any]:
    """Extract links from a WARC file.
    
    Args:
        warc_path: Path to the WARC file
            
    Returns:
        Dict containing:
            - status: "success" or "error"
            - links: List of records with source and target URIs (if successful)
            - error: Error message (if failed)
    """
    processor = WebArchiveProcessor()
    
    try:
        links = processor.extract_links_from_warc(warc_path)
        return {
            "status": "success",
            "links": links
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
