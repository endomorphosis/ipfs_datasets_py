import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock
import tempfile

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class MockWARCProcessor:
    def index_warc(self, warc_path, output_path):
        if warc_path == "test.warc" and output_path == "test.cdxj":
            return {"status": "success", "cdxj_path": output_path, "num_records": 10}
        raise Exception("Failed to index WARC in mock processor")

class TestMCPIndexWARC(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_warc_processor = MockWARCProcessor()
        self.patcher = patch('ipfs_datasets_py.web_archive.warc_processor.WARCProcessor', return_value=self.mock_warc_processor)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def test_index_warc_success(self):
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.index_warc import index_warc

        warc_path = "test.warc"
        output_path = "test.cdxj"
        
        result = await index_warc(warc_path=warc_path, output_path=output_path)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["warc_path"], warc_path)
        self.assertEqual(result["cdxj_path"], output_path)
        self.assertEqual(result["num_records"], 10)

    async def test_index_warc_failure(self):
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.index_warc import index_warc

        warc_path = "fail.warc"
        output_path = "fail.cdxj"
        self.mock_warc_processor.index_warc = MagicMock(side_effect=Exception("Indexing failed"))

        result = await index_warc(warc_path=warc_path, output_path=output_path)

        self.assertEqual(result["status"], "error")
        self.assertIn("Indexing failed", result["message"])
        self.assertEqual(result["warc_path"], warc_path)

if __name__ == '__main__':
    unittest.main()
