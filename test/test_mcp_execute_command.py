import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class TestMCPExecuteCommand(unittest.IsolatedAsyncioTestCase):

    @patch('ipfs_datasets_py.mcp_server.logger.logger.info')
    async def test_execute_command_success(self, mock_logger_info):
        from ipfs_datasets_py.mcp_server.tools.cli.execute_command import execute_command

        command = "ls"
        args = ["-l", "/tmp"]
        timeout = 30

        result = await execute_command(command=command, args=args, timeout_seconds=timeout) # Added await back

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["command"], command)
        self.assertEqual(result["args"], args)
        self.assertIn("Command 'ls' received but not executed for security reasons", result["message"])
        
        # Verify that the command was logged
        mock_logger_info.assert_called_once_with("Executing command: ls -l /tmp")

    @patch('ipfs_datasets_py.mcp_server.logger.logger.error')
    @patch('ipfs_datasets_py.mcp_server.tools.cli.execute_command.logger.info', side_effect=Exception("Simulated error"))
    async def test_execute_command_error_handling(self, mock_logger_info, mock_logger_error):
        from ipfs_datasets_py.mcp_server.tools.cli.execute_command import execute_command

        command = "invalid_command"
        
        result = await execute_command(command=command) # Added await back

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["command"], command)
        self.assertIn("Simulated error", result["error"])
        
        # Verify that the error was logged
        mock_logger_error.assert_called_once()

if __name__ == '__main__':
    unittest.main()
