
# Test for ipfs_tools/get_from_ipfs
def test_get_from_ipfs(self):
    """Test get_from_ipfs tool."""
    tool_func = self.get_tool_func("ipfs_tools", "get_from_ipfs")
    if not tool_func:
        self.skipTest("get_from_ipfs tool not found")

    async def run_test():
        # Mock the IPFS client used in the actual implementation
        with patch('subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = b"File downloaded successfully"
            mock_result.stderr = b""
            mock_run.return_value = mock_result

            result = await tool_func("QmTest123", "/tmp/output_file")
            self.assertEqual(result["status"], "success")
            self.assertIn("output_path", result)

    self.async_test(run_test())
