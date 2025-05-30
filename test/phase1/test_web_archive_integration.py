import os
import sys
import unittest
import tempfile
import shutil
import json
from typing import Dict, List, Any, Optional
from unittest.mock import patch, MagicMock

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(parent_dir)

# Import the module to test
try:
    from ipfs_datasets_py.web_archive_utils import WebArchiveProcessor
except ImportError:
    # Mock class for testing structure before implementation
    class WebArchiveProcessor:
        def __init__(self):
            pass

        def index_warc(self, warc_path, output_path=None, encryption_key=None):
            """Index a WARC file using IPWB"""
            if output_path:
                with open(output_path, 'w') as f:
                    f.write("mock CDXJ index")
            return output_path or "mock_index.cdxj"

        def extract_dataset_from_cdxj(self, cdxj_path, output_format="arrow"):
            """Extract dataset from CDXJ index"""
            if output_format == "arrow":
                # Return a mock Arrow table
                class MockTable:
                    def __init__(self):
                        self.num_rows = 10
                        self.column_names = ["uri", "timestamp", "mime", "status", "text"]

                    def to_pydict(self):
                        return {
                            "uri": ["https://example.com/"] * 10,
                            "timestamp": ["20200101120000"] * 10,
                            "mime": ["text/html"] * 10,
                            "status": ["200"] * 10,
                            "text": [f"Content {i}" for i in range(10)]
                        }
                return MockTable()
            elif output_format == "huggingface":
                # Return a mock dataset
                class MockDataset:
                    def __init__(self):
                        self.num_rows = 10
                        self.column_names = ["uri", "timestamp", "mime", "status", "text"]

                    def __len__(self):
                        return self.num_rows

                    def __getitem__(self, idx):
                        return {
                            "uri": "https://example.com/",
                            "timestamp": "20200101120000",
                            "mime": "text/html",
                            "status": "200",
                            "text": f"Content {idx}"
                        }
                return MockDataset()
            else:
                return {"mock": "dataset"}

        def create_warc(self, url, output_path=None, options=None):
            """Create a WARC file using ArchiveNow"""
            if output_path:
                with open(output_path, 'wb') as f:
                    f.write(b"mock WARC file")
            return output_path or "mock.warc"

        def extract_text_from_warc(self, warc_path):
            """Extract text content from WARC file"""
            return [
                {"uri": "https://example.com/", "text": "Example content 1"},
                {"uri": "https://example.com/page2", "text": "Example content 2"}
            ]

        def extract_links_from_warc(self, warc_path):
            """Extract links from WARC file"""
            return [
                {"source": "https://example.com/", "target": "https://example.com/page2"},
                {"source": "https://example.com/", "target": "https://external.com/"}
            ]


# Try to import testing dependencies, skip tests if not available
try:
    # Check if we have archivenow
    import archivenow
    HAVE_ARCHIVENOW = True
except ImportError:
    HAVE_ARCHIVENOW = False

try:
    # Check if we have ipwb
    import ipwb
    HAVE_IPWB = True
except ImportError:
    HAVE_IPWB = False


class TestWebArchiveIntegration(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test"""
        self.temp_dir = tempfile.mkdtemp()
        self.processor = WebArchiveProcessor()

    def tearDown(self):
        """Clean up test fixtures after each test"""
        shutil.rmtree(self.temp_dir)

    def test_create_warc(self):
        """Test creating a WARC file with ArchiveNow"""
        if not HAVE_ARCHIVENOW:
            self.skipTest("ArchiveNow not installed")

        # Replace with a mock URL for testing
        test_url = "https://example.com/"
        output_path = os.path.join(self.temp_dir, "test_archive.warc")

        # Mock the actual archive call to avoid network requests
        with patch('archivenow.archivenow.push', return_value=output_path) as mock_push:
            warc_path = self.processor.create_warc(
                test_url,
                output_path=output_path,
                options={"agent": "wget"}
            )

            # Verify the function was called with correct arguments
            mock_push.assert_called_once()
            args, kwargs = mock_push.call_args
            self.assertEqual(args[0], test_url)
            self.assertEqual(args[1], "warc")

            # Check output path
            self.assertEqual(warc_path, output_path)

    def test_index_warc(self):
        """Test indexing a WARC file with IPWB"""
        if not HAVE_IPWB:
            self.skipTest("IPWB not installed")

        # Create a mock WARC file
        warc_path = os.path.join(self.temp_dir, "test_archive.warc")
        with open(warc_path, 'wb') as f:
            f.write(b"WARC/1.0\r\n\r\nMock WARC content")

        cdxj_path = os.path.join(self.temp_dir, "test_index.cdxj")

        # Mock the actual indexing function to avoid IPFS communication
        with patch('ipwb.indexer.index_file_at', return_value=["com,example)/ 20200101120000 {}"]) as mock_index:
            indexed_path = self.processor.index_warc(warc_path, output_path=cdxj_path)

            # Verify the function was called with correct arguments
            mock_index.assert_called_once()
            args, kwargs = mock_index.call_args
            self.assertEqual(args[0], warc_path)

            # Check output path
            self.assertEqual(indexed_path, cdxj_path)

    def test_extract_dataset_arrow(self):
        """Test extracting an Arrow dataset from CDXJ index"""
        # Skip if IPWB is not available
        if not HAVE_IPWB:
            self.skipTest("IPWB not installed")

        # Create a mock CDXJ file
        cdxj_path = os.path.join(self.temp_dir, "test_index.cdxj")
        with open(cdxj_path, 'w') as f:
            f.write('com,example)/ 20200101120000 {"uri": "https://example.com/", "mime": "text/html"}\n')
            f.write('com,example)/page2 20200101120005 {"uri": "https://example.com/page2", "mime": "text/html"}\n')

        # Mock the IPFS communication
        try:
            with patch('ipwb.util.pull_from_ipfs', return_value=b"<html><body>Content</body></html>"):
                # Extract as Arrow table
                table = self.processor.extract_dataset_from_cdxj(cdxj_path, output_format="arrow")

                # Verify structure
                self.assertTrue(hasattr(table, 'num_rows'))
                self.assertTrue(hasattr(table, 'column_names'))
        except ImportError:
            self.skipTest("Error with IPWB modules")

    def test_extract_dataset_huggingface(self):
        """Test extracting a HuggingFace dataset from CDXJ index"""
        # Skip if IPWB is not available
        if not HAVE_IPWB:
            self.skipTest("IPWB not installed")

        # Create a mock CDXJ file
        cdxj_path = os.path.join(self.temp_dir, "test_index.cdxj")
        with open(cdxj_path, 'w') as f:
            f.write('com,example)/ 20200101120000 {"uri": "https://example.com/", "mime": "text/html"}\n')
            f.write('com,example)/page2 20200101120005 {"uri": "https://example.com/page2", "mime": "text/html"}\n')

        # Mock the IPFS communication
        try:
            with patch('ipwb.util.pull_from_ipfs', return_value=b"<html><body>Content</body></html>"):
                # Extract as HuggingFace dataset
                dataset = self.processor.extract_dataset_from_cdxj(cdxj_path, output_format="huggingface")

                # Verify structure
                self.assertTrue(hasattr(dataset, '__len__'))
                self.assertTrue(hasattr(dataset, '__getitem__'))
        except ImportError:
            self.skipTest("Error with IPWB or HuggingFace modules")

    def test_text_extraction(self):
        """Test extracting text content from WARC file"""
        try:
            # Try to import required dependencies
            from warcio.archiveiterator import ArchiveIterator
            from bs4 import BeautifulSoup
        except ImportError:
            self.skipTest("warcio or BeautifulSoup not installed")

        # Create a mock WARC file
        warc_path = os.path.join(self.temp_dir, "text_archive.warc")
        with open(warc_path, 'wb') as f:
            f.write(b"WARC/1.0\r\n\r\nMock WARC with HTML content")

        # Extract text
        text_data = self.processor.extract_text_from_warc(warc_path)

        # Verify structure
        self.assertTrue(isinstance(text_data, list))
        if text_data:
            self.assertTrue(isinstance(text_data[0], dict))
            self.assertIn('uri', text_data[0])
            self.assertIn('text', text_data[0])

    def test_link_extraction(self):
        """Test extracting links from WARC file"""
        try:
            # Try to import required dependencies
            from warcio.archiveiterator import ArchiveIterator
            from bs4 import BeautifulSoup
        except ImportError:
            self.skipTest("warcio or BeautifulSoup not installed")

        # Create a mock WARC file
        warc_path = os.path.join(self.temp_dir, "link_archive.warc")
        with open(warc_path, 'wb') as f:
            f.write(b"WARC/1.0\r\n\r\nMock WARC with links")

        # Extract links
        link_data = self.processor.extract_links_from_warc(warc_path)

        # Verify structure
        self.assertTrue(isinstance(link_data, list))
        if link_data:
            self.assertTrue(isinstance(link_data[0], dict))
            self.assertIn('source', link_data[0])
            self.assertIn('target', link_data[0])


if __name__ == '__main__':
    unittest.main()
