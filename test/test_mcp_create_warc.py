import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock
import tempfile

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class MockWebArchiveProcessor:
    def __init__(self):
        self.created_warcs = []

    def create_warc(self, url, output_path=None, options=None):
        if "fail" in url:
            raise Exception("Simulated WARC creation failure")
        
        # Simulate WARC creation
        if output_path:
            with open(output_path, 'w') as f:
                f.write(f"Mock WARC content for {url}")
            self.created_warcs.append(output_path)
            return output_path
        return "mock_warc_path.warc"

class TestMCPCreateWARC(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_processor = MockWebArchiveProcessor()
        self.patcher = patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor', return_value=self.mock_processor)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def test_create_warc_success(self):
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.create_warc import create_warc

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test.warc")
            url = "http://example.com"
            
            result = create_warc(url=url, output_path=output_path)

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["warc_path"], output_path)
            self.assertIn(output_path, self.mock_processor.created_warcs)
            self.assertTrue(os.path.exists(output_path))

    async def test_create_warc_failure(self):
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.create_warc import create_warc

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_fail.warc")
            url = "http://fail.com" # Trigger failure in mock
            
            result = create_warc(url=url, output_path=output_path)

            self.assertEqual(result["status"], "error")
            self.assertIn("Simulated WARC creation failure", result["error"])
            self.assertEqual(result["warc_path"], None) # warc_path should be None on error
            self.assertFalse(os.path.exists(output_path))

if __name__ == '__main__':
    unittest.main()
