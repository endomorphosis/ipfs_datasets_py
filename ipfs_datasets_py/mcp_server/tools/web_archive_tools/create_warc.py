"""Create WARC archive from a URL.

This tool creates a Web ARChive (WARC) file from a specified URL
using the WebArchiveProcessor from web_archive_utils.
"""
import os
from typing import Dict, Optional, Any

from ....web_archive import WebArchiveProcessor

async def create_warc(
    url: str,
    output_path: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Create a WARC file from a URL.

    Args:
        url: URL to archive
        output_path: Path for the output WARC file (optional)
        options: Options for the archiving tool (optional)
            - agent: "wget" or "squidwarc"
            - depth: crawl depth (for squidwarc)

    Returns:
        Dict containing:
            - status: "success" or "error"
            - warc_path: Path to the created WARC file (if successful)
            - error: Error message (if failed)
    """
    processor = WebArchiveProcessor()

    try:
        # Convert single URL to list if needed
        urls = [url] if isinstance(url, str) else url
        warc_data = processor.create_warc(urls, output_path or f"/tmp/archive_{url.replace('://', '_').replace('/', '_')}.warc", options)
        return {
            "status": "success",
            "warc_path": warc_data.get("output_file", output_path),
            "details": warc_data
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
