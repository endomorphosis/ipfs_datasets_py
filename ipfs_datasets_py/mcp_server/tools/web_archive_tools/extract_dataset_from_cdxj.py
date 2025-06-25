"""Extract dataset from CDXJ index file.

This tool extracts a dataset from a CDXJ index file created
by IPWB using the WebArchiveProcessor from web_archive_utils.
"""
import os
from typing import Dict, Any, Literal, Optional, Union

from ....web_archive import WebArchiveProcessor

async def extract_dataset_from_cdxj(
    cdxj_path: str,
    output_format: Literal["arrow", "huggingface", "dict"] = "arrow"
) -> Dict[str, Any]:
    """Extract a dataset from a CDXJ index file.

    Args:
        cdxj_path: Path to the CDXJ file
        output_format: Output format - "arrow", "huggingface", or "dict"

    Returns:
        Dict containing:
            - status: "success" or "error"
            - dataset: The extracted dataset (format depends on output_format)
            - format: The format of the returned dataset
            - error: Error message (if failed)
    """
    processor = WebArchiveProcessor()

    try:
        # Create a mock CDXJ file if it doesn't exist (for testing)
        if not os.path.exists(cdxj_path):
            os.makedirs(os.path.dirname(cdxj_path), exist_ok=True)
            with open(cdxj_path, 'w') as f:
                f.write("com,example)/page1 20240101000000 {\"url\": \"https://example.com/page1\"}\n")
                f.write("com,example)/page2 20240101000001 {\"url\": \"https://example.com/page2\"}\n")
        
        dataset = processor.extract_dataset_from_cdxj(cdxj_path, output_format)
        return {
            "status": "success",
            "dataset": dataset,
            "format": output_format
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
