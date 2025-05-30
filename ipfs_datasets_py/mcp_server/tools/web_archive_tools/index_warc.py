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
