import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class MockIPFSClient:
    def cat(self, cid):
        if cid == "QmTestHash":
            return b"file content"
        raise Exception("CID not found in mock IPFS client")

class TestMCPGetFromIPFS(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_ipfs_client = MockIPFSClient()
        self.patcher = patch('ipfs_datasets_py.mcp_server.tools.ipfs_tools.get_from_ipfs.ipfshttpclient.connect', return_value=self.mock_ipfs_client)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def test_get_from_ipfs_success(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_tools.get_from_ipfs import get_from_ipfs

        cid = "QmTestHash"
        
        # Mock the cat method to return file content
        self.mock_ipfs_client.cat = MagicMock(return_value=b"file content")

        result = await get_from_ipfs(cid=cid)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["cid"], cid)
        self.assertEqual(result["content"], "file content")
        self.mock_ipfs_client.cat.assert_called_once_with(cid)

    async def test_get_from_ipfs_failure(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_tools.get_from_ipfs import get_from_ipfs

        cid = "QmNonExistentHash"
        self.mock_ipfs_client.cat = MagicMock(side_effect=Exception("Cat failed"))

        result = await get_from_ipfs(cid=cid)

        self.assertEqual(result["status"], "error")
        self.assertIn("Cat failed", result["message"])
        self.assertEqual(result["cid"], cid)
        self.assertIsNone(result.get("content"))
        self.mock_ipfs_client.cat.assert_called_once_with(cid)

if __name__ == '__main__':
    unittest.main()
