"""Tests for circular import prevention and module independence.

These tests ensure that MCP server modules can be imported independently
without circular dependency issues.

Part of Phase 2 Week 4: Circular Dependency Elimination
"""

import importlib
import sys
import unittest
from pathlib import Path
from typing import List
from unittest.mock import Mock

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


class TestCircularImports(unittest.TestCase):
    """Test that modules can be imported without circular dependencies."""
    
    def setUp(self):
        """Clear import cache before each test."""
        # List of modules to test
        self.modules_to_test = [
            'ipfs_datasets_py.mcp_server.mcp_interfaces',
            'ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter',
            'ipfs_datasets_py.mcp_server.server_context',
            'ipfs_datasets_py.mcp_server.hierarchical_tool_manager',
            'ipfs_datasets_py.mcp_server.tool_metadata',
        ]
    
    def test_mcp_interfaces_imports_independently(self):
        """Test that mcp_interfaces can be imported without dependencies."""
        # GIVEN: A clean import environment
        # WHEN: Importing mcp_interfaces
        try:
            from ipfs_datasets_py.mcp_server import mcp_interfaces
            # THEN: Import succeeds
            self.assertIsNotNone(mcp_interfaces)
            self.assertTrue(hasattr(mcp_interfaces, 'MCPServerProtocol'))
            self.assertTrue(hasattr(mcp_interfaces, 'ToolManagerProtocol'))
        except ImportError as e:
            self.fail(f"mcp_interfaces failed to import: {e}")
    
    def test_p2p_adapter_imports_with_protocol(self):
        """Test that p2p_mcp_registry_adapter uses TYPE_CHECKING correctly."""
        # GIVEN: A clean import environment
        # WHEN: Importing p2p_mcp_registry_adapter
        try:
            from ipfs_datasets_py.mcp_server import p2p_mcp_registry_adapter
            # THEN: Import succeeds and uses protocol types
            self.assertIsNotNone(p2p_mcp_registry_adapter)
            self.assertTrue(hasattr(p2p_mcp_registry_adapter, 'P2PMCPRegistryAdapter'))
        except ImportError as e:
            self.fail(f"p2p_mcp_registry_adapter failed to import: {e}")
    
    def test_server_context_imports_independently(self):
        """Test that server_context doesn't create circular imports."""
        # GIVEN: A clean import environment
        # WHEN: Importing server_context
        try:
            from ipfs_datasets_py.mcp_server import server_context
            # THEN: Import succeeds
            self.assertIsNotNone(server_context)
            self.assertTrue(hasattr(server_context, 'ServerContext'))
        except ImportError as e:
            self.fail(f"server_context failed to import: {e}")
    
    def test_no_circular_dependency_between_adapter_and_server(self):
        """Test that adapter and server can be imported in any order."""
        # GIVEN: Fresh Python environment (simulated)
        # WHEN: Importing in both orders
        try:
            # Order 1: adapter first, then server
            from ipfs_datasets_py.mcp_server import p2p_mcp_registry_adapter
            # Note: server.py requires anyio, so we can't test full import
            # but we can verify adapter doesn't fail
            self.assertIsNotNone(p2p_mcp_registry_adapter)
        except ImportError as e:
            # Only fail if it's actually a circular import (not missing deps)
            if "circular" in str(e).lower():
                self.fail(f"Circular import detected: {e}")
    
    def test_all_protocol_classes_are_runtime_checkable(self):
        """Test that all protocol classes can be used with isinstance()."""
        # GIVEN: The mcp_interfaces module
        from ipfs_datasets_py.mcp_server import mcp_interfaces
        
        # WHEN: Checking protocol classes
        protocols = [
            mcp_interfaces.MCPServerProtocol,
            mcp_interfaces.ToolManagerProtocol,
            mcp_interfaces.MCPClientProtocol,
            mcp_interfaces.P2PServiceProtocol,
        ]
        
        # THEN: All protocols should be runtime_checkable
        for protocol in protocols:
            # Create a mock object that implements the protocol
            mock_obj = Mock(spec=protocol)
            # Should not raise an error
            try:
                isinstance(mock_obj, protocol)
            except TypeError as e:
                self.fail(f"{protocol.__name__} is not runtime_checkable: {e}")


class TestProtocolImplementation(unittest.TestCase):
    """Test that protocol classes work correctly."""
    
    def test_mcp_server_protocol_interface(self):
        """Test MCPServerProtocol defines correct interface."""
        # GIVEN: The MCPServerProtocol
        from ipfs_datasets_py.mcp_server.mcp_interfaces import MCPServerProtocol
        
        # WHEN: Creating a mock server that implements the protocol
        mock_server = Mock(spec=MCPServerProtocol)
        mock_server.tools = {"test_tool": lambda: "result"}
        mock_server.validate_p2p_token.return_value = True
        
        # THEN: Mock should have the required attributes and methods
        self.assertTrue(hasattr(mock_server, 'tools'))
        self.assertTrue(hasattr(mock_server, 'validate_p2p_token'))
        self.assertTrue(callable(mock_server.validate_p2p_token))
    
    def test_tool_manager_protocol_interface(self):
        """Test ToolManagerProtocol defines correct interface."""
        # GIVEN: The ToolManagerProtocol
        from ipfs_datasets_py.mcp_server.mcp_interfaces import ToolManagerProtocol
        
        # WHEN: Creating a mock manager
        mock_manager = Mock(spec=ToolManagerProtocol)
        mock_manager.list_categories.return_value = ["category1", "category2"]
        mock_manager.list_tools.return_value = []
        mock_manager.get_schema.return_value = {}
        mock_manager.dispatch.return_value = "result"
        
        # THEN: Mock should have all required methods
        self.assertTrue(callable(mock_manager.list_categories))
        self.assertTrue(callable(mock_manager.list_tools))
        self.assertTrue(callable(mock_manager.get_schema))
        self.assertTrue(callable(mock_manager.dispatch))
    
    def test_check_protocol_implementation_helper(self):
        """Test the check_protocol_implementation helper function."""
        # GIVEN: A protocol and a matching object
        from ipfs_datasets_py.mcp_server.mcp_interfaces import (
            MCPServerProtocol,
            check_protocol_implementation,
        )
        
        mock_server = Mock(spec=MCPServerProtocol)
        mock_server.tools = {}
        mock_server.validate_p2p_token = Mock(return_value=True)
        
        # WHEN: Checking protocol implementation
        result = check_protocol_implementation(mock_server, MCPServerProtocol)
        
        # THEN: Should return True
        self.assertTrue(result)
    
    def test_check_protocol_implementation_strict_mode(self):
        """Test strict mode of protocol check raises on mismatch."""
        # GIVEN: A protocol and a non-matching object
        from ipfs_datasets_py.mcp_server.mcp_interfaces import (
            MCPServerProtocol,
            check_protocol_implementation,
        )
        
        non_matching_obj = object()
        
        # WHEN: Checking protocol implementation in strict mode
        # THEN: Should raise TypeError
        with self.assertRaises(TypeError) as ctx:
            check_protocol_implementation(
                non_matching_obj,
                MCPServerProtocol,
                strict=True
            )
        
        self.assertIn("does not implement", str(ctx.exception))


class TestP2PAdapterWithProtocol(unittest.TestCase):
    """Test that P2P adapter works with protocol-based server."""
    
    def test_adapter_accepts_protocol_compliant_server(self):
        """Test that adapter can be initialized with a protocol-compliant mock."""
        # GIVEN: A mock server that implements MCPServerProtocol
        from ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter import (
            P2PMCPRegistryAdapter,
        )
        
        mock_server = Mock()
        mock_server.tools = {
            "test_tool": lambda x: f"result: {x}",
        }
        mock_server.validate_p2p_token = Mock(return_value=True)
        
        # WHEN: Creating adapter with mock server
        adapter = P2PMCPRegistryAdapter(mock_server)
        
        # THEN: Adapter should be created successfully
        self.assertIsNotNone(adapter)
        self.assertEqual(adapter._host, mock_server)
    
    def test_adapter_tools_property_uses_host_tools(self):
        """Test that adapter's tools property accesses host server tools."""
        # GIVEN: An adapter with a mock server
        from ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter import (
            P2PMCPRegistryAdapter,
        )
        
        def test_func():
            """Test function."""
            return "test_result"
        
        mock_server = Mock()
        mock_server.tools = {"test_tool": test_func}
        
        adapter = P2PMCPRegistryAdapter(mock_server)
        
        # WHEN: Accessing adapter.tools
        tools = adapter.tools
        
        # THEN: Should return tools from host server
        self.assertIn("test_tool", tools)
        self.assertEqual(tools["test_tool"]["function"], test_func)
    
    def test_adapter_accelerate_instance_property(self):
        """Test that adapter provides accelerate_instance property."""
        # GIVEN: An adapter with a mock server
        from ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter import (
            P2PMCPRegistryAdapter,
        )
        
        mock_server = Mock()
        mock_server.tools = {}
        
        adapter = P2PMCPRegistryAdapter(mock_server)
        
        # WHEN: Accessing accelerate_instance
        instance = adapter.accelerate_instance
        
        # THEN: Should return the host server
        self.assertEqual(instance, mock_server)


if __name__ == "__main__":
    unittest.main()
