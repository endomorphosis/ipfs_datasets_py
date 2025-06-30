import unittest
import os
import sys
from unittest.mock import patch, MagicMock
import tempfile

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Correct import for the tool function
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_text_from_warc import extract_text_from_warc

class MockWebArchiveProcessor:
    def extract_text_from_warc(self, warc_path):
        if "fail" in warc_path:
            raise Exception("Simulated text extraction failure")

        if warc_path == "test.warc":
            return [{"uri": "http://example.com", "text": "This is some test content from the WARC."}]
        return []

@patch('ipfs_datasets_py.web_archive.WebArchiveProcessor', new=MockWebArchiveProcessor)
class TestMCPExtractTextFromWARC(unittest.TestCase): # Changed to unittest.TestCase

    # Removed asyncSetUp as it's not needed for synchronous tests

    def test_extract_text_from_warc_success(self): # Changed to synchronous test method
        # The tool function will now use MockWebArchiveProcessor when it instantiates WebArchiveProcessor
        warc_path = "test.warc"

        result = extract_text_from_warc(warc_path=warc_path)

        self.assertEqual(result["status"], "success")
        self.assertIn("records", result)
        self.assertIsInstance(result["records"], list)
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["text"], "This is some test content from the WARC.")

    def test_extract_text_from_warc_failure(self): # Changed to synchronous test method
        warc_path = "fail.warc"
        # The MockWebArchiveProcessor's own logic handles the "fail" case by raising an exception.
        # The tool function catches this and returns an error status.

        result = extract_text_from_warc(warc_path=warc_path)

        self.assertEqual(result["status"], "error")
        self.assertIn("error", result)
        self.assertIn("Simulated text extraction failure", result["error"]) # Expecting the mock's exception message

if __name__ == '__main__':
    unittest.main()
