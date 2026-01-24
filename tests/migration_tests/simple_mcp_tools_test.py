#!/usr/bin/env python3
"""
Simple MCP Tools Test Suite

This script tests that all MCP tools can be imported and called successfully,
focusing on functionality rather than mocking specific dependencies.
"""
import anyio
import os
import sys
import json
import tempfile
import importlib
import unittest
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

# Expected tool categories and tools
EXPECTED_TOOLS = {
    "dataset_tools": [
        "load_dataset",
        "save_dataset",
        "process_dataset",
        "convert_dataset_format"
    ],
    "ipfs_tools": [
        "get_from_ipfs",
        "pin_to_ipfs"
    ],
    "vector_tools": [
        "create_vector_index",
        "search_vector_index"
    ],
    "graph_tools": [
        "query_knowledge_graph"
    ],
    "audit_tools": [
        "record_audit_event",
        "generate_audit_report"
    ],
    "security_tools": [
        "check_access_permission"
    ],
    "provenance_tools": [
        "record_provenance"
    ],
    "web_archive_tools": [
        "create_warc",
        "index_warc",
        "extract_dataset_from_cdxj",
        "extract_text_from_warc",
        "extract_links_from_warc",
        "extract_metadata_from_warc"
    ],
    "cli": [
        "execute_command"
    ],
    "functions": [
        "execute_python_snippet"
    ]
}

class SimpleMCPToolsTest(unittest.TestCase):
    """Simple functional tests for MCP tools."""

    def get_tool_func(self, category, tool_name):
        """Get the tool function."""
        import_path = f"ipfs_datasets_py.mcp_server.tools.{category}.{tool_name}"
        try:
            module = importlib.import_module(import_path)
            if hasattr(module, tool_name):
                return getattr(module, tool_name)
            return None
        except ImportError:
            return None

    def run_async_test(self, func, *args, **kwargs):
        """Helper method to run async functions or regular functions in tests."""
        try:
            result = func(*args, **kwargs)
            # If it's a coroutine, run it with asyncio
            if hasattr(result, '__await__'):
                return anyio.run(result)
            else:
                return result
        except Exception as e:
            print(f"Error running test: {e}")
            raise

    # Dataset Tools Tests
    def test_load_dataset_functionality(self):
        """Test that load_dataset can be called and returns expected structure."""
        tool_func = self.get_tool_func("dataset_tools", "load_dataset")
        self.assertIsNotNone(tool_func, "load_dataset tool not found")

        result = self.run_async_test(tool_func, "test_dataset", format="json")

        # Check basic structure
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)
        self.assertIn("dataset_id", result)
        self.assertIn("metadata", result)
        self.assertIn("summary", result)

    def test_save_dataset_functionality(self):
        """Test that save_dataset can be called and returns expected structure."""
        tool_func = self.get_tool_func("dataset_tools", "save_dataset")
        self.assertIsNotNone(tool_func, "save_dataset tool not found")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            result = self.run_async_test(tool_func, "test_dataset", tmp_path, format="json")

            # Check basic structure
            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            self.assertIn("dataset_id", result)
            self.assertIn("destination", result)
        finally:
            # Clean up
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_process_dataset_functionality(self):
        """Test that process_dataset can be called and returns expected structure."""
        tool_func = self.get_tool_func("dataset_tools", "process_dataset")
        self.assertIsNotNone(tool_func, "process_dataset tool not found")

        operations = [{"type": "filter", "field": "text", "value": "test"}]
        result = self.run_async_test(tool_func, "test_dataset", operations)

        # Check basic structure
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)
        self.assertIn("dataset_id", result)

    def test_convert_dataset_format_functionality(self):
        """Test that convert_dataset_format can be called and returns expected structure."""
        tool_func = self.get_tool_func("dataset_tools", "convert_dataset_format")
        self.assertIsNotNone(tool_func, "convert_dataset_format tool not found")

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            result = self.run_async_test(tool_func, "test_dataset", "csv", output_path=tmp_path)

            # Check basic structure
            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            self.assertIn("dataset_id", result)
        finally:
            # Clean up
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # IPFS Tools Tests
    def test_get_from_ipfs_functionality(self):
        """Test that get_from_ipfs can be called and returns expected structure."""
        tool_func = self.get_tool_func("ipfs_tools", "get_from_ipfs")
        self.assertIsNotNone(tool_func, "get_from_ipfs tool not found")

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            result = self.run_async_test(tool_func, "QmTest123", tmp_path)

            # Check basic structure
            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            self.assertIn("cid", result)
        finally:
            # Clean up
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_pin_to_ipfs_functionality(self):
        """Test that pin_to_ipfs can be called and returns expected structure."""
        tool_func = self.get_tool_func("ipfs_tools", "pin_to_ipfs")
        self.assertIsNotNone(tool_func, "pin_to_ipfs tool not found")

        # Test with a data dictionary
        test_data = {"test": "data", "number": 42}
        result = self.run_async_test(tool_func, test_data)

        # Check basic structure
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)
        self.assertIn("cid", result)

    # Vector Tools Tests
    def test_create_vector_index_functionality(self):
        """Test that create_vector_index can be called and returns expected structure."""
        tool_func = self.get_tool_func("vector_tools", "create_vector_index")
        self.assertIsNotNone(tool_func, "create_vector_index tool not found")

        with tempfile.NamedTemporaryFile(suffix=".faiss", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            test_vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
            result = self.run_async_test(tool_func, test_vectors, tmp_path)

            # Check basic structure
            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
        finally:
            # Clean up
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_search_vector_index_functionality(self):
        """Test that search_vector_index can be called and returns expected structure."""
        tool_func = self.get_tool_func("vector_tools", "search_vector_index")
        self.assertIsNotNone(tool_func, "search_vector_index tool not found")

        result = self.run_async_test(tool_func, "dummy_index_path", [0.1, 0.2, 0.3], top_k=5)

        # Check basic structure
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)

    # Graph Tools Tests
    def test_query_knowledge_graph_functionality(self):
        """Test that query_knowledge_graph can be called and returns expected structure."""
        tool_func = self.get_tool_func("graph_tools", "query_knowledge_graph")
        self.assertIsNotNone(tool_func, "query_knowledge_graph tool not found")

        result = self.run_async_test(tool_func, "dummy_graph_path", "test query")

        # Check basic structure
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)

    # Audit Tools Tests
    def test_record_audit_event_functionality(self):
        """Test that record_audit_event can be called and returns expected structure."""
        tool_func = self.get_tool_func("audit_tools", "record_audit_event")
        self.assertIsNotNone(tool_func, "record_audit_event tool not found")

        event = {
            "user_id": "test_user",
            "action": "test_action",
            "resource": "test_resource",
            "timestamp": "2025-01-01T00:00:00Z"
        }
        result = self.run_async_test(tool_func, event)

        # Check basic structure
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)

    def test_generate_audit_report_functionality(self):
        """Test that generate_audit_report can be called and returns expected structure."""
        tool_func = self.get_tool_func("audit_tools", "generate_audit_report")
        self.assertIsNotNone(tool_func, "generate_audit_report tool not found")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            result = self.run_async_test(tool_func, "2025-01-01", "2025-01-31", tmp_path)

            # Check basic structure
            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
        finally:
            # Clean up
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # Security Tools Tests
    def test_check_access_permission_functionality(self):
        """Test that check_access_permission can be called and returns expected structure."""
        tool_func = self.get_tool_func("security_tools", "check_access_permission")
        self.assertIsNotNone(tool_func, "check_access_permission tool not found")

        result = self.run_async_test(tool_func, "test_user", "test_resource", "read")

        # Check basic structure - use actual field name from output
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)
        self.assertIn("allowed", result)  # The actual field name is "allowed", not "access_allowed"

    # Provenance Tools Tests
    def test_record_provenance_functionality(self):
        """Test that record_provenance can be called and returns expected structure."""
        tool_func = self.get_tool_func("provenance_tools", "record_provenance")
        self.assertIsNotNone(tool_func, "record_provenance tool not found")

        # Use correct parameters for the actual function signature
        result = self.run_async_test(
            tool_func,
            "test_dataset_id",  # dataset_id
            "test_operation",   # operation
            ["input1"],         # inputs
            {"param1": "value1"}, # parameters
            "Test provenance record", # description
            "test_agent",       # agent_id
            "2025-01-01T00:00:00Z", # timestamp
            ["tag1", "tag2"]    # tags
        )

        # Check basic structure
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)

    # Web Archive Tools Tests
    def test_create_warc_functionality(self):
        """Test that create_warc can be called and returns expected structure."""
        tool_func = self.get_tool_func("web_archive_tools", "create_warc")
        self.assertIsNotNone(tool_func, "create_warc tool not found")

        with tempfile.NamedTemporaryFile(suffix=".warc", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            result = self.run_async_test(tool_func, "https://example.com", tmp_path)

            # Check basic structure
            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
        finally:
            # Clean up
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # CLI Tools Tests
    def test_execute_command_functionality(self):
        """Test that execute_command can be called and returns expected structure."""
        tool_func = self.get_tool_func("cli", "execute_command")
        self.assertIsNotNone(tool_func, "execute_command tool not found")

        result = self.run_async_test(tool_func, "echo 'test'")

        # Check basic structure
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)

    # Function Tools Tests
    def test_execute_python_snippet_functionality(self):
        """Test that execute_python_snippet can be called and returns expected structure."""
        tool_func = self.get_tool_func("functions", "execute_python_snippet")
        self.assertIsNotNone(tool_func, "execute_python_snippet tool not found")

        result = self.run_async_test(tool_func, "print('Hello, World!')")

        # Check basic structure
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
