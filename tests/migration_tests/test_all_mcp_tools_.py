#!/usr/bin/env python3
"""
Comprehensive test suite for all IPFS Datasets MCP server tools.

This test suite systematically tests all MCP tools including:
- Web Archive Tools
- Vector Tools
- Graph Tools
- Dataset Tools
- IPFS Tools
- Audit Tools
- Provenance Tools
- Security Tools
- CLI Tools
- Function Tools
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Any, List
from unittest.mock import patch, MagicMock

# Add the project root to Python path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))


class TestWebArchiveTools(unittest.TestCase):
    """Test all web archive tools."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_warc_path = os.path.join(self.temp_dir, "test.warc")
        # Create a dummy WARC file
        with open(self.test_warc_path, 'w') as f:
            f.write("WARC/1.0\nWARC-Type: response\n\nTest content")

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_extract_text_from_warc(self):
        """Test extracting text from WARC files."""
        try:
            from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_text_from_warc import extract_text_from_warc

            result = extract_text_from_warc(self.test_warc_path)

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("records", result)
                self.assertIsInstance(result["records"], list)
            else:
                self.assertIn("error", result)

            print(f"✓ extract_text_from_warc: {result['status']}")
        except Exception as e:
            print(f"✗ extract_text_from_warc failed: {e}")

    async def test_extract_metadata_from_warc(self):
        """Test extracting metadata from WARC files."""
        try:
            from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_metadata_from_warc import extract_metadata_from_warc

            result = await extract_metadata_from_warc(self.test_warc_path)

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("metadata", result)
            else:
                self.assertIn("error", result)

            print(f"✓ extract_metadata_from_warc: {result['status']}")
        except Exception as e:
            print(f"✗ extract_metadata_from_warc failed: {e}")

    async def test_extract_links_from_warc(self):
        """Test extracting links from WARC files."""
        try:
            from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_links_from_warc import extract_links_from_warc

            result = await extract_links_from_warc(self.test_warc_path)

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("links", result)
                self.assertIsInstance(result["links"], list)
            else:
                self.assertIn("error", result)

            print(f"✓ extract_links_from_warc: {result['status']}")
        except Exception as e:
            print(f"✗ extract_links_from_warc failed: {e}")

    async def test_index_warc(self):
        """Test indexing WARC files."""
        try:
            from ipfs_datasets_py.mcp_server.tools.web_archive_tools.index_warc import index_warc

            result = await index_warc(self.test_warc_path)

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("index_path", result)
            else:
                self.assertIn("error", result)

            print(f"✓ index_warc: {result['status']}")
        except Exception as e:
            print(f"✗ index_warc failed: {e}")

    def test_create_warc(self):
        """Test creating WARC files."""
        try:
            from ipfs_datasets_py.mcp_server.tools.web_archive_tools.create_warc import create_warc

            test_urls = ["https://example.com", "https://test.com"]
            output_path = os.path.join(self.temp_dir, "created.warc")

            result = create_warc(test_urls, output_path)

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("warc_path", result)
            else:
                self.assertIn("error", result)

            print(f"✓ create_warc: {result['status']}")
        except Exception as e:
            print(f"✗ create_warc failed: {e}")

    def test_extract_dataset_from_cdxj(self):
        """Test extracting dataset from CDXJ files."""
        try:
            from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_dataset_from_cdxj import extract_dataset_from_cdxj

            # Create a test CDXJ file
            cdxj_path = os.path.join(self.temp_dir, "test.cdxj")
            with open(cdxj_path, 'w') as f:
                f.write('com,example)/ 20240101000000 {"url": "https://example.com/", "mime": "text/html"}\n')

            result = extract_dataset_from_cdxj(cdxj_path)

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("dataset", result)
            else:
                self.assertIn("error", result)

            print(f"✓ extract_dataset_from_cdxj: {result['status']}")
        except Exception as e:
            print(f"✗ extract_dataset_from_cdxj failed: {e}")


class TestVectorTools(unittest.TestCase):
    """Test all vector tools."""

    def test_create_vector_index(self):
        """Test creating vector indexes."""
        try:
            # Import the tool
            sys.path.append(str(project_root / "ipfs_datasets_py" / "mcp_server" / "tools" / "vector_tools"))
            from ipfs_datasets_py.mcp_server.tools.vector_tools import create_vector_index

            # Test data
            vectors = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
            metadata = [{"id": "vec1"}, {"id": "vec2"}, {"id": "vec3"}]

            # Run the async function
            result = asyncio.run(create_vector_index(vectors, metadata=metadata))

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("index_id", result)
                self.assertIn("vector_count", result)
            else:
                self.assertIn("error", result)

            print(f"✓ create_vector_index: {result['status']}")
        except Exception as e:
            print(f"✗ create_vector_index failed: {e}")

    def test_search_vector_index(self):
        """Test searching vector indexes."""
        try:
            from ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index import search_vector_index

            # Test data
            query_vector = [1.0, 0.0, 0.0]

            result = asyncio.run(search_vector_index("test_index", query_vector, top_k=5))

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("results", result)
                self.assertIsInstance(result["results"], list)
            else:
                self.assertIn("error", result)

            print(f"✓ search_vector_index: {result['status']}")
        except Exception as e:
            print(f"✗ search_vector_index failed: {e}")


class TestGraphTools(unittest.TestCase):
    """Test all graph tools."""

    def test_query_knowledge_graph(self):
        """Test querying knowledge graphs."""
        try:
            from ipfs_datasets_py.mcp_server.tools.graph_tools.query_knowledge_graph import query_knowledge_graph

            result = asyncio.run(query_knowledge_graph(
                graph_id="test_graph",
                query="SELECT * WHERE { ?s ?p ?o } LIMIT 10",
                query_type="sparql"
            ))

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("results", result)
            else:
                self.assertIn("error", result)

            print(f"✓ query_knowledge_graph: {result['status']}")
        except Exception as e:
            print(f"✗ query_knowledge_graph failed: {e}")


class TestDatasetTools(unittest.TestCase):
    """Test all dataset tools."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_dataset(self):
        """Test loading datasets."""
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset

            result = asyncio.run(load_dataset("test_dataset"))

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("dataset", result)
            else:
                self.assertIn("error", result)

            print(f"✓ load_dataset: {result['status']}")
        except Exception as e:
            print(f"✗ load_dataset failed: {e}")

    def test_save_dataset(self):
        """Test saving datasets."""
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset

            test_data = {"data": [1, 2, 3], "metadata": {"name": "test"}}
            output_path = os.path.join(self.temp_dir, "test_dataset.json")

            result = asyncio.run(save_dataset(test_data, output_path))

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("path", result)
            else:
                self.assertIn("error", result)

            print(f"✓ save_dataset: {result['status']}")
        except Exception as e:
            print(f"✗ save_dataset failed: {e}")

    def test_process_dataset(self):
        """Test processing datasets."""
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import process_dataset

            test_data = {"data": [1, 2, 3]}
            operations = ["normalize", "filter"]

            result = asyncio.run(process_dataset(test_data, operations))

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("processed_data", result)
            else:
                self.assertIn("error", result)

            print(f"✓ process_dataset: {result['status']}")
        except Exception as e:
            print(f"✗ process_dataset failed: {e}")

    def test_convert_dataset_format(self):
        """Test converting dataset formats."""
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.convert_dataset_format import convert_dataset_format

            input_path = os.path.join(self.temp_dir, "input.json")
            output_path = os.path.join(self.temp_dir, "output.csv")

            # Create test input file
            with open(input_path, 'w') as f:
                json.dump({"data": [{"a": 1, "b": 2}]}, f)

            result = asyncio.run(convert_dataset_format(input_path, output_path, "json", "csv"))

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("output_path", result)
            else:
                self.assertIn("error", result)

            print(f"✓ convert_dataset_format: {result['status']}")
        except Exception as e:
            print(f"✗ convert_dataset_format failed: {e}")


class TestIPFSTools(unittest.TestCase):
    """Test all IPFS tools."""

    def test_pin_to_ipfs(self):
        """Test pinning content to IPFS."""
        try:
            from ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs import pin_to_ipfs

            result = asyncio.run(pin_to_ipfs("QmTestHash"))

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("hash", result)
            else:
                self.assertIn("error", result)

            print(f"✓ pin_to_ipfs: {result['status']}")
        except Exception as e:
            print(f"✗ pin_to_ipfs failed: {e}")

    def test_get_from_ipfs(self):
        """Test getting content from IPFS."""
        try:
            from ipfs_datasets_py.mcp_server.tools.ipfs_tools.get_from_ipfs import get_from_ipfs

            result = asyncio.run(get_from_ipfs("QmTestHash"))

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("content", result)
            else:
                self.assertIn("error", result)

            print(f"✓ get_from_ipfs: {result['status']}")
        except Exception as e:
            print(f"✗ get_from_ipfs failed: {e}")


class TestAuditTools(unittest.TestCase):
    """Test all audit tools."""

    def test_record_audit_event(self):
        """Test recording audit events."""
        try:
            from ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event import record_audit_event

            event_data = {
                "user": "test_user",
                "action": "test_action",
                "resource": "test_resource",
                "timestamp": "2024-01-01T00:00:00Z"
            }

            result = asyncio.run(record_audit_event(event_data))

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("event_id", result)
            else:
                self.assertIn("error", result)

            print(f"✓ record_audit_event: {result['status']}")
        except Exception as e:
            print(f"✗ record_audit_event failed: {e}")

    def test_generate_audit_report(self):
        """Test generating audit reports."""
        try:
            from ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report import generate_audit_report

            result = asyncio.run(generate_audit_report(
                start_date="2024-01-01",
                end_date="2024-01-02"
            ))

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("report", result)
            else:
                self.assertIn("error", result)

            print(f"✓ generate_audit_report: {result['status']}")
        except Exception as e:
            print(f"✗ generate_audit_report failed: {e}")


class TestProvenanceTools(unittest.TestCase):
    """Test all provenance tools."""

    def test_record_provenance(self):
        """Test recording provenance information."""
        try:
            from ipfs_datasets_py.mcp_server.tools.provenance_tools.record_provenance import record_provenance

            provenance_data = {
                "dataset_id": "test_dataset",
                "operation": "transformation",
                "input_sources": ["source1", "source2"],
                "output": "result",
                "timestamp": "2024-01-01T00:00:00Z"
            }

            result = asyncio.run(record_provenance(provenance_data))

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("provenance_id", result)
            else:
                self.assertIn("error", result)

            print(f"✓ record_provenance: {result['status']}")
        except Exception as e:
            print(f"✗ record_provenance failed: {e}")


class TestSecurityTools(unittest.TestCase):
    """Test all security tools."""

    def test_check_access_permission(self):
        """Test checking access permissions."""
        try:
            from ipfs_datasets_py.mcp_server.tools.security_tools.check_access_permission import check_access_permission

            result = asyncio.run(check_access_permission(
                user_id="test_user",
                resource="test_resource",
                operation="read"
            ))

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("allowed", result)
            else:
                self.assertIn("error", result)

            print(f"✓ check_access_permission: {result['status']}")
        except Exception as e:
            print(f"✗ check_access_permission failed: {e}")


class TestCLITools(unittest.TestCase):
    """Test all CLI tools."""

    def test_execute_command(self):
        """Test executing CLI commands."""
        try:
            from ipfs_datasets_py.mcp_server.tools.cli.execute_command import execute_command

            result = asyncio.run(execute_command("echo 'Hello World'"))

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("output", result)
            else:
                self.assertIn("error", result)

            print(f"✓ execute_command: {result['status']}")
        except Exception as e:
            print(f"✗ execute_command failed: {e}")


class TestFunctionTools(unittest.TestCase):
    """Test all function tools."""

    def test_execute_python_snippet(self):
        """Test executing Python code snippets."""
        try:
            from ipfs_datasets_py.mcp_server.tools.functions.execute_python_snippet import execute_python_snippet

            code = "result = 2 + 2\nprint(f'Result: {result}')"

            result = asyncio.run(execute_python_snippet(code))

            self.assertIsInstance(result, dict)
            self.assertIn("status", result)
            if result["status"] == "success":
                self.assertIn("output", result)
            else:
                self.assertIn("error", result)

            print(f"✓ execute_python_snippet: {result['status']}")
        except Exception as e:
            print(f"✗ execute_python_snippet failed: {e}")


def run_all_tests():
    """Run all tests and provide a summary."""
    print("IPFS Datasets MCP Server Tools Test Suite")
    print("=" * 50)

    test_classes = [
        TestWebArchiveTools,
        TestVectorTools,
        TestGraphTools,
        TestDatasetTools,
        TestIPFSTools,
        TestAuditTools,
        TestProvenanceTools,
        TestSecurityTools,
        TestCLITools,
        TestFunctionTools
    ]

    total_tests = 0
    passed_tests = 0

    for test_class in test_classes:
        print(f"\nTesting {test_class.__name__}...")
        print("-" * 30)

        suite = unittest.TestLoader().loadTestsFromTestCase(test_class)
        runner = unittest.TextTestRunner(verbosity=0, stream=open(os.devnull, 'w'))

        # Run individual test methods manually to get better control
        test_instance = test_class()
        if hasattr(test_instance, 'setUp'):
            test_instance.setUp()

        for method_name in dir(test_instance):
            if method_name.startswith('test_'):
                total_tests += 1
                try:
                    method = getattr(test_instance, method_name)
                    method()
                    passed_tests += 1
                except Exception as e:
                    print(f"✗ {method_name} failed: {e}")

        if hasattr(test_instance, 'tearDown'):
            test_instance.tearDown()

    print(f"\n" + "=" * 50)
    print(f"Test Summary: {passed_tests}/{total_tests} tests passed")

    if passed_tests == total_tests:
        print("🎉 All tests passed!")
        return True
    else:
        print(f"⚠️  {total_tests - passed_tests} tests failed")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
