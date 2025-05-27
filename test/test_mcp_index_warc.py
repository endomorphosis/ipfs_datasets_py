import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock
import tempfile

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class MockWebArchiveProcessor:
    def index_warc(self, warc_path, output_path=None, encryption_key=None):
        if warc_path == "test.warc":
            return output_path or "test.cdxj"
        raise Exception("Failed to index WARC in mock processor")

class TestMCPIndexWARC(unittest.TestCase):

    def setUp(self):
        self.mock_processor = MockWebArchiveProcessor()
        self.patcher = patch('ipfs_datasets_py.web_archive.WebArchiveProcessor', return_value=self.mock_processor)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_index_warc_success(self):
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.index_warc import index_warc

        warc_path = "test.warc"
        output_path = "test.cdxj"
        
        result = index_warc(warc_path=warc_path, output_path=output_path)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["cdxj_path"], output_path)

    def test_index_warc_failure(self):
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.index_warc import index_warc

        warc_path = "fail.warc"
        
        result = index_warc(warc_path=warc_path)

        self.assertEqual(result["status"], "error")
        self.assertIn("error", result)

if __name__ == '__main__':
    unittest.main()
