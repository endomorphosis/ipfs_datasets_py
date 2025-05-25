import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class MockIPFSClient:
    def add(self, file_path):
        if file_path == "test_file.txt":
            return [{"Hash": "QmTestHash", "Name": "test_file.txt", "Size": "100"}]
        raise Exception("File not found in mock IPFS client")

    def pin(self, cid):
        if cid == "QmTestHash":
            return {"Pins": ["QmTestHash"]}
        raise Exception("CID not found in mock IPFS client")

class TestMCPPinToIPFS(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_ipfs_client = MockIPFSClient()
        self.patcher = patch('ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs.ipfshttpclient.connect', return_value=self.mock_ipfs_client)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def test_pin_to_ipfs_success(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs import pin_to_ipfs

        file_path = "test_file.txt"
        
        # Mock the add method to return a CID
        self.mock_ipfs_client.add = MagicMock(return_value=[{"Hash": "QmTestHash", "Name": "test_file.txt", "Size": "100"}])
        self.mock_ipfs_client.pin = MagicMock(return_value={"Pins": ["QmTestHash"]})

        result = await pin_to_ipfs(file_path=file_path)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["file_path"], file_path)
        self.assertEqual(result["cid"], "QmTestHash")
        self.assertTrue(result["is_pinned"])
        self.mock_ipfs_client.add.assert_called_once_with(file_path)
        self.mock_ipfs_client.pin.assert_called_once_with("QmTestHash")

    async def test_pin_to_ipfs_add_failure(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs import pin_to_ipfs

        file_path = "non_existent_file.txt"
        self.mock_ipfs_client.add = MagicMock(side_effect=Exception("Add failed"))

        result = await pin_to_ipfs(file_path=file_path)

        self.assertEqual(result["status"], "error")
        self.assertIn("Add failed", result["message"])
        self.assertEqual(result["file_path"], file_path)
        self.assertIsNone(result.get("cid"))
        self.assertFalse(result.get("is_pinned", False))
        self.mock_ipfs_client.add.assert_called_once_with(file_path)
        self.mock_ipfs_client.pin.assert_not_called()

    async def test_pin_to_ipfs_pin_failure(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs import pin_to_ipfs

        file_path = "test_file.txt"
        self.mock_ipfs_client.add = MagicMock(return_value=[{"Hash": "QmTestHash", "Name": "test_file.txt", "Size": "100"}])
        self.mock_ipfs_client.pin = MagicMock(side_effect=Exception("Pin failed"))

        result = await pin_to_ipfs(file_path=file_path)

        self.assertEqual(result["status"], "error")
        self.assertIn("Pin failed", result["message"])
        self.assertEqual(result["file_path"], file_path)
        self.assertEqual(result["cid"], "QmTestHash")
        self.assertFalse(result["is_pinned"])
        self.mock_ipfs_client.add.assert_called_once_with(file_path)
        self.mock_ipfs_client.pin.assert_called_once_with("QmTestHash")

if __name__ == '__main__':
    unittest.main()
