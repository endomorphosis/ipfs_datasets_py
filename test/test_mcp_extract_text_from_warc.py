import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock
import tempfile

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class MockWebArchiveProcessor:
    def extract_text_from_warc(self, warc_path):
        if "fail" in warc_path:
            raise Exception("Simulated text extraction failure")
        
        if warc_path == "test.warc":
            return [{"uri": "http://example.com", "text": "This is some test content from the WARC."}]
        return []

class TestMCPExtractTextFromWARC(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_processor = MockWebArchiveProcessor()
        self.patcher = patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor', return_value=self.mock_processor)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def test_extract_text_from_warc_success(self):
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_text_from_warc import extract_text_from_warc

        warc_path = "test.warc"
        
        result = extract_text_from_warc(warc_path=warc_path)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["warc_path"], warc_path)
        self.assertIn("text_content", result)
        self.assertEqual(result["text_content"][0]["text"], "This is some test content from the WARC.")

    async def test_extract_text_from_warc_failure(self):
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_text_from_warc import extract_text_from_warc

        warc_path = "fail.warc"
        self.mock_processor.extract_text_from_warc = MagicMock(side_effect=Exception("Extraction failed"))

        result = extract_text_from_warc(warc_path=warc_path)

        self.assertEqual(result["status"], "error")
        self.assertIn("Extraction failed", result["error"])
        self.assertEqual(result["warc_path"], warc_path)

if __name__ == '__main__':
    unittest.main()
