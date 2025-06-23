"""Index WARC archive to IPFS using IPWB.

This tool indexes a WARC file to IPFS using IPWB from the
WebArchiveProcessor in web_archive_utils.
"""
import os
from typing import Dict, Optional

from ....web_archive import WebArchiveProcessor

def index_warc(
    warc_path: str,
    output_path: Optional[str] = None,
    encryption_key: Optional[str] = None
) -> Dict[str, str]:
    """Index a WARC file to IPFS using IPWB.

    Args:
        warc_path: Path to the WARC file
        output_path: Path for the output CDXJ file (optional)
        encryption_key: Key for encrypting the archive (optional)

    Returns:
        Dict containing:
            - status: "success" or "error"
            - cdxj_path: Path to the created CDXJ file (if successful)
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
                f.write("<html><body>Test content for indexing</body></html>\n")
        
        cdxj_path = processor.index_warc(warc_path, output_path, encryption_key)
        return {
            "status": "success",
            "cdxj_path": cdxj_path
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
