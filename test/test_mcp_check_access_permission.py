import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class MockAccessControlManager:
    def check_access(self, resource_id: str, access_type: str) -> bool:
        if resource_id == "data_record_123" and access_type == "read":
            return True
        elif resource_id == "error_resource" and access_type == "error_action":
            raise Exception("Permission check failed")
        return False

class TestMCPCheckAccessPermission(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_access_control_manager = MockAccessControlManager()
        self.patcher = patch('ipfs_datasets_py.security.SecurityManager', return_value=self.mock_access_control_manager)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def test_check_access_permission_granted(self):
        from ipfs_datasets_py.mcp_server.tools.security_tools.check_access_permission import check_access_permission

        user_id = "admin"
        resource_id = "data_record_123"
        permission_type = "read"
        
        result = await check_access_permission(user_id=user_id, resource_id=resource_id, permission_type=permission_type)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["user_id"], user_id)
        self.assertEqual(result["resource_id"], resource_id)
        self.assertEqual(result["permission_type"], permission_type)
        self.assertTrue(result["allowed"])
        self.assertIn("Admin user has full access", result["reason"])

    async def test_check_access_permission_denied(self):
        from ipfs_datasets_py.mcp_server.tools.security_tools.check_access_permission import check_access_permission

        user_id = "guest"
        resource_id = "data_record_123"
        permission_type = "read"
        
        result = await check_access_permission(user_id=user_id, resource_id=resource_id, permission_type=permission_type)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["user_id"], user_id)
        self.assertEqual(result["resource_id"], resource_id)
        self.assertEqual(result["permission_type"], permission_type)
        self.assertFalse(result["allowed"])
        self.assertIn("Guest user has no access to this resource", result["reason"])

    async def test_check_access_permission_error_handling(self):
        from ipfs_datasets_py.mcp_server.tools.security_tools.check_access_permission import check_access_permission

        user_id = "error_user"
        resource_id = "error_resource"
        permission_type = "error_action"
        self.mock_access_control_manager.check_permission = MagicMock(side_effect=Exception("Permission check failed"))

        result = await check_access_permission(user_id=user_id, resource_id=resource_id, permission_type=permission_type)

        self.assertEqual(result["status"], "error")
        self.assertIn("Permission check failed", result["message"])
        self.assertEqual(result["user_id"], user_id)
        self.assertEqual(result["resource_id"], resource_id)
        self.assertEqual(result["permission_type"], permission_type)

if __name__ == '__main__':
    unittest.main()
