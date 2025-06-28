import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock
import tempfile

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class MockWebArchiveProcessor:
    def extract_dataset_from_cdxj(self, cdxj_path, output_format):
        if "fail" in cdxj_path:
            raise Exception("Simulated CDXJ extraction failure")

        if cdxj_path == "test.cdxj" and output_format == "dict":
            return [{"url": "http://example.com", "timestamp": "2023-01-01T00:00:00Z"}]
        return []

class TestMCPExtractDatasetFromCDXJ(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_processor = MockWebArchiveProcessor()
        self.patcher = patch('ipfs_datasets_py.web_archive.WebArchiveProcessor', return_value=self.mock_processor)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def test_extract_dataset_from_cdxj_success(self):
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_dataset_from_cdxj import extract_dataset_from_cdxj

        cdxj_path = "test.cdxj"
        output_format = "dict"

        result = extract_dataset_from_cdxj(cdxj_path=cdxj_path, output_format=output_format)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["cdxj_path"], cdxj_path)
        self.assertEqual(result["output_format"], output_format)
        self.assertIn("dataset", result)
        self.assertEqual(result["dataset"][0]["url"], "http://example.com")

    async def test_extract_dataset_from_cdxj_failure(self):
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_dataset_from_cdxj import extract_dataset_from_cdxj

        cdxj_path = "fail.cdxj"
        output_format = "dict"
        self.mock_processor.extract_dataset_from_cdxj = MagicMock(side_effect=Exception("Extraction failed"))

        result = extract_dataset_from_cdxj(cdxj_path=cdxj_path, output_format=output_format)

        self.assertEqual(result["status"], "error")
        self.assertIn("Extraction failed", result["error"])
        self.assertEqual(result["cdxj_path"], cdxj_path)

if __name__ == '__main__':
    unittest.main()
