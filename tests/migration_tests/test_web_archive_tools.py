#!/usr/bin/env python3
"""
Unit tests for MCP Web Archive Tools.

This script tests the functionality of the web archive tools in the MCP server.
"""
import os
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

print("Starting test_web_archive_tools.py")

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))
print(f"Python path: {sys.path}")

# Import tools to test
try:
    print("Attempting to import web archive tools...")
    from ipfs_datasets_py.mcp_server.tools.web_archive_tools import (
        create_warc, index_warc, extract_dataset_from_cdxj,
        extract_text_from_warc, extract_links_from_warc, extract_metadata_from_warc
    )
    from ipfs_datasets_py.web_archive_utils import WebArchiveProcessor
    print("Successfully imported web archive tools")
except ImportError as e:
    print(f"Error importing web archive tools: {e}")
    sys.exit(1)

class WebArchiveToolsTest(unittest.TestCase):
    """Test cases for web archive tools."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path("/tmp/web_archive_test")
        os.makedirs(self.test_dir, exist_ok=True)

        # Sample paths
        self.warc_path = self.test_dir / "sample.warc"
        self.cdxj_path = self.test_dir / "sample.cdxj"
        self.output_path = self.test_dir / "output.json"

        # Touch files to create them
        self.warc_path.touch()
        self.cdxj_path.touch()

    def tearDown(self):
        """Clean up test environment."""
        import shutil
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    @patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor')
    def test_create_warc(self, mock_processor_class):
        """Test create_warc tool."""
        # Set up mock
        mock_processor = MagicMock()
        mock_processor_class.return_value = mock_processor
        mock_processor.create_warc.return_value = str(self.warc_path)

        # Call the function
        result = create_warc(
            url="https://example.com",
            output_path=str(self.warc_path)
        )

        # Check results
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["warc_path"], str(self.warc_path))
        mock_processor.create_warc.assert_called_once_with(
            "https://example.com", str(self.warc_path), None
        )

    @patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor')
    def test_index_warc(self, mock_processor_class):
        """Test index_warc tool."""
        # Set up mock
        mock_processor = MagicMock()
        mock_processor_class.return_value = mock_processor
        mock_processor.index_warc.return_value = str(self.cdxj_path)

        # Call the function
        result = index_warc(
            warc_path=str(self.warc_path),
            output_path=str(self.cdxj_path)
        )

        # Check results
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["cdxj_path"], str(self.cdxj_path))
        mock_processor.index_warc.assert_called_once_with(
            str(self.warc_path), str(self.cdxj_path), None
        )

    @patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor')
    def test_extract_dataset_from_cdxj(self, mock_processor_class):
        """Test extract_dataset_from_cdxj tool."""
        # Set up mock
        mock_processor = MagicMock()
        mock_processor_class.return_value = mock_processor
        sample_dataset = {"data": [{"id": 1, "text": "Sample"}]}
        mock_processor.extract_dataset_from_cdxj.return_value = sample_dataset

        # Call the function
        result = extract_dataset_from_cdxj(
            cdxj_path=str(self.cdxj_path),
            output_path=str(self.output_path)
        )

        # Check results
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["dataset"], sample_dataset)
        mock_processor.extract_dataset_from_cdxj.assert_called_once()

    @patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor')
    def test_extract_text_from_warc(self, mock_processor_class):
        """Test extract_text_from_warc tool."""
        # Set up mock
        mock_processor = MagicMock()
        mock_processor_class.return_value = mock_processor
        sample_text = {"text": "Sample extracted text"}
        mock_processor.extract_text_from_warc.return_value = sample_text

        # Call the function
        result = extract_text_from_warc(
            warc_path=str(self.warc_path),
            output_path=str(self.output_path)
        )

        # Check results
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["text"], sample_text)
        mock_processor.extract_text_from_warc.assert_called_once_with(
            str(self.warc_path), str(self.output_path)
        )

    @patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor')
    def test_extract_links_from_warc(self, mock_processor_class):
        """Test extract_links_from_warc tool."""
        # Set up mock
        mock_processor = MagicMock()
        mock_processor_class.return_value = mock_processor
        sample_links = ["https://example.com/page1", "https://example.com/page2"]
        mock_processor.extract_links_from_warc.return_value = sample_links

        # Call the function
        result = extract_links_from_warc(
            warc_path=str(self.warc_path),
            output_path=str(self.output_path)
        )

        # Check results
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["links"], sample_links)
        mock_processor.extract_links_from_warc.assert_called_once()

    @patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor')
    def test_extract_metadata_from_warc(self, mock_processor_class):
        """Test extract_metadata_from_warc tool."""
        # Set up mock
        mock_processor = MagicMock()
        mock_processor_class.return_value = mock_processor
        sample_metadata = {"title": "Example Page", "description": "Sample description"}
        mock_processor.extract_metadata_from_warc.return_value = sample_metadata

        # Call the function
        result = extract_metadata_from_warc(
            warc_path=str(self.warc_path),
            output_path=str(self.output_path)
        )

        # Check results
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["metadata"], sample_metadata)
        mock_processor.extract_metadata_from_warc.assert_called_once()

if __name__ == "__main__":
    unittest.main()
