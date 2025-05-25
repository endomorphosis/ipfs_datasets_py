import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class TestMCPExecutePythonSnippet(unittest.IsolatedAsyncioTestCase):

    @patch('ipfs_datasets_py.mcp_server.logger.logger.info')
    async def test_execute_python_snippet_success(self, mock_logger_info):
        from ipfs_datasets_py.mcp_server.tools.functions.execute_python_snippet import execute_python_snippet

        code_snippet = "print('Hello, world!')"
        timeout = 10
        context = {"var1": 123}

        result = execute_python_snippet(code=code_snippet, timeout_seconds=timeout, context=context)

        self.assertEqual(result["status"], "success")
        self.assertIn("Code snippet received", result["message"])
        self.assertIn(f"(length: {len(code_snippet)} chars)", result["message"])
        self.assertEqual(result["execution_time_ms"], 0)
        
        # Verify that the code execution was logged
        mock_logger_info.assert_called_once_with(f"Executing Python snippet (length: {len(code_snippet)} chars)")

    @patch('ipfs_datasets_py.mcp_server.logger.logger.error')
    @patch('ipfs_datasets_py.mcp_server.tools.functions.execute_python_snippet.logger.info', side_effect=Exception("Simulated error"))
    async def test_execute_python_snippet_error_handling(self, mock_logger_info, mock_logger_error):
        from ipfs_datasets_py.mcp_server.tools.functions.execute_python_snippet import execute_python_snippet

        code_snippet = "raise ValueError('Test error')"
        
        result = execute_python_snippet(code=code_snippet)

        self.assertEqual(result["status"], "error")
        self.assertIn("Simulated error", result["error"])
        
        # Verify that the error was logged
        mock_logger_error.assert_called_once()

if __name__ == '__main__':
    unittest.main()
