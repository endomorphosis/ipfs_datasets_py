#!/usr/bin/env python3
"""
Comprehensive MCP Tools Test Suite

This script verifies that all the expected MCP tools are present and properly
implemented, and tests their functionality using mock data and dependencies.
"""
import os
import sys
import json
import time
import inspect
import unittest
import importlib
import logging
import anyio # Import asyncio for async tests
from pathlib import Path
from unittest.mock import patch, MagicMock

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("mcp_tool_test")

# Add project root to path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

# Paths
MCP_SERVER_PATH = project_root / "ipfs_datasets_py" / "mcp_server"
TOOLS_PATH = MCP_SERVER_PATH / "tools"

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

class MCPToolsVerifier:
    """Verifies and tests MCP tools."""

    def __init__(self):
        self.results = {}
        self.is_async = {}

    def check_directory_structure(self):
        """Check if all expected tool directories exist."""
        logger.info("Checking directory structure...")

        missing_dirs = []
        for category in EXPECTED_TOOLS:
            category_path = TOOLS_PATH / category
            if not category_path.exists():
                missing_dirs.append(category)
                logger.warning(f"Missing tool category directory: {category}")

        if missing_dirs:
            logger.warning(f"Found {len(missing_dirs)} missing tool categories")
        else:
            logger.info("All expected tool category directories exist")

        return missing_dirs

    def check_tool_files(self):
        """Check if all expected tool files exist."""
        logger.info("Checking tool files...")

        results = {}
        for category, tools in EXPECTED_TOOLS.items():
            category_path = TOOLS_PATH / category
            if not category_path.exists():
                results[category] = {"missing": tools, "present": []}
                continue

            present = []
            missing = []
            for tool in tools:
                tool_file = category_path / f"{tool}.py"
                if tool_file.exists():
                    present.append(tool)
                else:
                    missing.append(tool)

            results[category] = {"missing": missing, "present": present}

        # Count totals
        total_tools = sum(len(tools) for tools in EXPECTED_TOOLS.values())
        total_present = sum(len(result["present"]) for result in results.values())
        total_missing = sum(len(result["missing"]) for result in results.values())

        logger.info(f"Found {total_present}/{total_tools} expected tool files")
        if total_missing > 0:
            logger.warning(f"Missing {total_missing} tool files")

        self.results["files"] = results
        return results

    def check_tool_implementations(self):
        """Check if tools are properly implemented."""
        logger.info("Checking tool implementations...")

        results = {}
        self.is_async = {}

        for category, tools in EXPECTED_TOOLS.items():
            category_results = {}

            for tool in tools:
                tool_file = TOOLS_PATH / category / f"{tool}.py"
                if not tool_file.exists():
                    category_results[tool] = {"status": "missing", "errors": ["File not found"]}
                    continue

                # Try to import the module
                import_path = f"ipfs_datasets_py.mcp_server.tools.{category}.{tool}"
                try:
                    module = importlib.import_module(import_path)

                    # Check if tool function exists
                    if hasattr(module, tool):
                        func = getattr(module, tool)

                        # Check if it's callable
                        if callable(func):
                            is_async = inspect.iscoroutinefunction(func)

                            # Store whether the function is async
                            self.is_async[(category, tool)] = is_async

                            # Get function signature
                            sig = inspect.signature(func)
                            params = list(sig.parameters.keys())

                            category_results[tool] = {
                                "status": "valid",
                                "type": "async" if is_async else "sync",
                                "params": params,
                                "errors": []
                            }
                        else:
                            category_results[tool] = {
                                "status": "invalid",
                                "errors": [f"{tool} attribute is not callable"]
                            }
                    else:
                        category_results[tool] = {
                            "status": "invalid",
                            "errors": [f"No {tool} function found in module"]
                        }

                except ImportError as e:
                    category_results[tool] = {"status": "import_error", "errors": [str(e)]}
                except Exception as e:
                    category_results[tool] = {"status": "error", "errors": [str(e)]}

            results[category] = category_results

        # Count implementation status
        status_counts = {"valid": 0, "invalid": 0, "missing": 0, "import_error": 0, "error": 0}

        for category_results in results.values():
            for tool_result in category_results.values():
                status = tool_result["status"]
                status_counts[status] = status_counts.get(status, 0) + 1

        logger.info(f"Implementation check results: {status_counts}")

        self.results["implementations"] = results
        return results

    def write_results_to_file(self, output_path):
        """Write verification results to a JSON file."""
        results = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tool_counts": {
                category: len(tools)
                for category, tools in EXPECTED_TOOLS.items()
            },
            "results": self.results
        }

        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)

        logger.info(f"Results written to {output_path}")

    def print_summary(self):
        """Print a summary of the verification results."""
        if "files" not in self.results or "implementations" not in self.results:
            logger.error("Cannot print summary: verification not completed")
            return

        print("\nMCP TOOLS VERIFICATION SUMMARY")
        print("=" * 40)

        # File existence summary
        files = self.results["files"]
        total_tools = sum(len(tools) for tools in EXPECTED_TOOLS.values())
        total_present = sum(len(result["present"]) for result in files.values())

        print(f"\nTool Files: {total_present}/{total_tools} ({total_present/total_tools*100:.1f}%)")

        # Implementation summary
        implementations = self.results["implementations"]
        status_counts = {"valid": 0, "invalid": 0, "missing": 0, "import_error": 0, "error": 0}

        for category_results in implementations.values():
            for tool_result in category_results.values():
                status = tool_result["status"]
                status_counts[status] = status_counts.get(status, 0) + 1

        print("\nImplementation Status:")
        for status, count in status_counts.items():
            print(f"  {status}: {count}")

        # Category breakdown
        print("\nCategory Breakdown:")
        for category, tools in EXPECTED_TOOLS.items():
            present = len(files.get(category, {}).get("present", []))
            total = len(tools)
            valid_count = sum(1 for tool, result in implementations.get(category, {}).items()
                             if result["status"] == "valid")

            print(f"  {category}: {present}/{total} files, {valid_count}/{total} valid implementations")

    def verify_all(self):
        """Run all verification checks."""
        self.check_directory_structure()
        self.check_tool_files()
        self.check_tool_implementations()
        self.print_summary()
        self.write_results_to_file("mcp_tools_verification.json")

# Unit test class for each tool category
class BaseToolTester(unittest.TestCase):
    """Base class for MCP tool tests."""

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

    def run_async_test(self, async_func, *args, **kwargs):
        """Helper method to run async functions in tests."""
        return anyio.run(async_func(*args, **kwargs))

# Dataset Tools Tests
class DatasetToolsTest(BaseToolTester):
    """Tests for dataset tools."""

    @patch('datasets.load_dataset') # Patch the actual imported function
    def test_load_dataset(self, mock_hf_load_dataset):
        """Test load_dataset tool."""
        tool_func = self.get_tool_func("dataset_tools", "load_dataset")
        if not tool_func:
            self.skipTest("load_dataset tool not found")

        # Set up mock return value
        mock_hf_load_dataset.return_value = MagicMock(
            id="test_dataset",
            info=MagicMock(to_dict=lambda: {"description": "Test dataset"}),
            features={"text": "string"},
            __len__=lambda: 1 # Mock length for len() call
        )

        # Set up test data
        source = "test_dataset_source"
        format = "json"

        # Call function with test data (await since it's async)
        result = anyio.run(tool_func(source, format=format))

        # Assertions
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["dataset_id"], f"mock_{source}")
        self.assertIn("metadata", result)
        self.assertIn("summary", result)
        self.assertEqual(result["summary"]["num_records"], 100)
        mock_hf_load_dataset.assert_called_once_with(source, format=format)

    @patch('ipfs_datasets_py.dataset_manager.DatasetManager') # Patch the DatasetManager class
    def test_save_dataset(self, MockDatasetManager):
        """Test save_dataset tool."""
        tool_func = self.get_tool_func("dataset_tools", "save_dataset")
        if not tool_func:
            self.skipTest("save_dataset tool not found")

        # Set up mock instance and methods
        mock_manager = MagicMock()
        MockDatasetManager.return_value = mock_manager

        mock_dataset = MagicMock(format="json")
        mock_manager.get_dataset.return_value = mock_dataset

        # Create an async mock function
        async def mock_save_async(*args, **kwargs):
            return {"location": "/tmp/saved.json", "size": 100}

        mock_dataset.save_async = mock_save_async

        # Set up test data
        dataset_id = "test_dataset_id"
        destination = "/tmp/saved.json"
        format = "json"

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, dataset_id, destination, format=format)

        # Assertions
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["dataset_id"], dataset_id)
        self.assertEqual(result["destination"], destination)
        self.assertEqual(result["format"], format)
        self.assertIn("location", result)
        self.assertIn("size", result)
        MockDatasetManager.assert_called_once()
        mock_manager.get_dataset.assert_called_once_with(dataset_id)
        mock_dataset.save_async.assert_called_once_with(destination, format=format)

    @patch('ipfs_datasets_py.dataset_manager.DatasetManager') # Patch the DatasetManager class
    def test_process_dataset(self, MockDatasetManager):
        """Test process_dataset tool."""
        tool_func = self.get_tool_func("dataset_tools", "process_dataset")
        if not tool_func:
            self.skipTest("process_dataset tool not found")

        # Set up mock instance and methods
        mock_manager = MagicMock()
        MockDatasetManager.return_value = mock_manager

        mock_dataset = MagicMock()
        mock_manager.get_dataset.return_value = mock_dataset

        mock_dataset.process = MagicMock(return_value=MagicMock()) # Mock the processed dataset

        # Set up test data
        dataset_id = "test_dataset_id"
        operations = [{"type": "filter", "field": "text", "value": "sample"}]

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, dataset_id, operations)

        # Assertions
        self.assertEqual(result["status"], "success")
        self.assertIn("dataset_id", result) # The function returns the new dataset_id, not processed_dataset_id
        MockDatasetManager.assert_called_once()
        mock_manager.get_dataset.assert_called_once_with(dataset_id)
        mock_dataset.process.assert_called_once_with(operations)

    @patch('ipfs_datasets_py.dataset_manager.DatasetManager') # Patch the DatasetManager class
    def test_convert_dataset_format(self, MockDatasetManager):
        """Test convert_dataset_format tool."""
        tool_func = self.get_tool_func("dataset_tools", "convert_dataset_format")
        if not tool_func:
            self.skipTest("convert_dataset_format tool not found")

        # Set up mock instance and methods
        mock_manager = MagicMock()
        MockDatasetManager.return_value = mock_manager

        mock_manager.convert_dataset_format = MagicMock(return_value={"location": "/tmp/converted.csv"})

        # Set up test data
        dataset_id = "test_dataset_id"
        target_format = "csv"
        output_path = "/tmp/converted.csv"

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, dataset_id, target_format, output_path=output_path)

        # Assertions
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["dataset_id"], dataset_id)
        self.assertEqual(result["target_format"], target_format)
        MockDatasetManager.assert_called_once() # Assuming convert_dataset_format is a static method or class method on Manager
        # Note: We don't assert the method call since the function doesn't use DatasetManager for conversion

# IPFS Tools Tests
class IPFSToolsTest(BaseToolTester):
    """Tests for IPFS tools."""

    @patch('ipfs_datasets_py.mcp_server.configs.configs')
    def test_get_from_ipfs(self, mock_configs):
        """Test get_from_ipfs tool."""
        tool_func = self.get_tool_func("ipfs_tools", "get_from_ipfs")
        if not tool_func:
            self.skipTest("get_from_ipfs tool not found")

        # Mock the configs to avoid IPFS integration
        mock_configs.ipfs_kit_integration = "mcp"

        # Set up test data
        cid = "QmXyZ123"
        output_path = "/tmp/output.json"

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, cid, output_path)

        # Assertions - should get a mock/fallback response
        self.assertEqual(result["status"], "success")
        self.assertIn("cid", result)

    @patch('ipfs_datasets_py.mcp_server.configs.configs')
    def test_pin_to_ipfs(self, mock_configs):
        """Test pin_to_ipfs tool."""
        tool_func = self.get_tool_func("ipfs_tools", "pin_to_ipfs")
        if not tool_func:
            self.skipTest("pin_to_ipfs tool not found")

        # Mock the configs to avoid IPFS integration
        mock_configs.ipfs_kit_integration = "mcp"

        # Set up test data
        file_path = "/tmp/file.json"

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, file_path)

        # Assertions - should get a mock/fallback response
        self.assertEqual(result["status"], "success")
        self.assertIn("cid", result)

# Vector Tools Tests
class VectorToolsTest(BaseToolTester):
    """Tests for vector tools."""

    @patch('ipfs_datasets_py.ml.embeddings.ipfs_knn_index.IPFSKnnIndex') # Patch the IPFSFaiss class
    def test_create_vector_index(self, MockIPFSKnnIndex):
        """Test create_vector_index tool."""
        tool_func = self.get_tool_func("vector_tools", "create_vector_index")
        if not tool_func:
            self.skipTest("create_vector_index tool not found")

        # Set up mock instance and methods
        mock_faiss = MagicMock()
        MockIPFSKnnIndex.return_value = mock_faiss

        mock_faiss.create_index = MagicMock()

        # Set up test data
        vectors = [[0.1, 0.2], [0.3, 0.4]]
        output_path = "/tmp/vectors.index"

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, vectors, output_path)

        # Assertions
        self.assertEqual(result["status"], "success")
        MockIPFSKnnIndex.assert_called_once()
        mock_faiss.create_index.assert_called_once_with(vectors, output_path)

    @patch('ipfs_datasets_py.ml.embeddings.ipfs_knn_index.IPFSKnnIndex') # Patch the IPFSFaiss class
    def test_search_vector_index(self, MockIPFSKnnIndex):
        """Test search_vector_index tool."""
        tool_func = self.get_tool_func("vector_tools", "search_vector_index")
        if not tool_func:
            self.skipTest("search_vector_index tool not found")

        # Set up mock instance and methods
        mock_faiss = MagicMock()
        MockIPFSKnnIndex.return_value = mock_faiss

        mock_faiss.search_index = MagicMock(return_value={
            "indices": [0, 1],
            "distances": [0.1, 0.2]
        })

        # Set up test data
        index_path = "/tmp/vectors.index"
        query_vector = [0.1, 0.2]
        k = 5

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, index_path, query_vector, k)

        # Assertions
        self.assertEqual(result["status"], "success")
        self.assertIn("results", result)
        MockIPFSKnnIndex.assert_called_once()
        mock_faiss.search_index.assert_called_once_with(index_path, query_vector, k)

# Graph Tools Tests
class GraphToolsTest(BaseToolTester):
    """Tests for graph tools."""

    @patch('ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction.KnowledgeGraph') # Patch the KnowledgeGraph class
    def test_query_knowledge_graph(self, MockKnowledgeGraph):
        """Test query_knowledge_graph tool."""
        tool_func = self.get_tool_func("graph_tools", "query_knowledge_graph")
        if not tool_func:
            self.skipTest("query_knowledge_graph tool not found")

        # Set up mock instance and methods
        mock_graph = MagicMock()
        MockKnowledgeGraph.return_value = mock_graph

        mock_graph.query = MagicMock(return_value={
            "results": [{"node": "value"}]
        })

        # Set up test data
        graph_path = "/tmp/graph.json"
        query = "MATCH (n) RETURN n LIMIT 10"

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, graph_path, query)

        # Assertions
        self.assertEqual(result["status"], "success")
        self.assertIn("results", result)
        MockKnowledgeGraph.assert_called_once_with(graph_path)
        mock_graph.query.assert_called_once_with(query)

# Audit Tools Tests
class AuditToolsTest(BaseToolTester):
    """Tests for audit tools."""

    @patch('ipfs_datasets_py.audit.AuditLogger') # Patch the AuditLogger class
    def test_record_audit_event(self, MockAuditLogger):
        """Test record_audit_event tool."""
        tool_func = self.get_tool_func("audit_tools", "record_audit_event")
        if not tool_func:
            self.skipTest("record_audit_event tool not found")

        # Set up mock instance and methods
        mock_logger = MagicMock()
        MockAuditLogger.return_value = mock_logger

        mock_logger.log_event = MagicMock()

        # Set up test data
        event = {
            "user_id": "user1",
            "action": "access",
            "resource": "dataset1",
            "timestamp": "2025-05-21T12:34:56Z"
        }

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, event)

        # Assertions
        self.assertEqual(result["status"], "success")
        MockAuditLogger.assert_called_once()
        mock_logger.log_event.assert_called_once_with(event)

    @patch('ipfs_datasets_py.audit.audit_reporting.AuditReportGenerator') # Patch the AuditReportGenerator class
    def test_generate_audit_report(self, MockReportGenerator):
        """Test generate_audit_report tool."""
        tool_func = self.get_tool_func("audit_tools", "generate_audit_report")
        if not tool_func:
            self.skipTest("generate_audit_report tool not found")

        # Set up mock instance and methods
        mock_generator = MagicMock()
        MockReportGenerator.return_value = mock_generator

        mock_generator.generate_report = MagicMock(return_value={
            "events": [{"user_id": "user1", "action": "access"}]
        })

        # Set up test data
        start_date = "2025-05-01"
        end_date = "2025-05-21"
        output_path = "/tmp/audit_report.json"

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, start_date, end_date, output_path)

        # Assertions
        self.assertEqual(result["status"], "success")
        self.assertIn("events", result)
        MockReportGenerator.assert_called_once()
        mock_generator.generate_report.assert_called_once_with(start_date, end_date, output_path)

# Security Tools Tests
class SecurityToolsTest(BaseToolTester):
    """Tests for security tools."""

    @patch('ipfs_datasets_py.security.SecurityManager') # Patch the SecurityManager class
    def test_check_access_permission(self, MockSecurityManager):
        """Test check_access_permission tool."""
        tool_func = self.get_tool_func("security_tools", "check_access_permission")
        if not tool_func:
            self.skipTest("check_access_permission tool not found")

        # Set up mock instance and methods
        mock_manager = MagicMock()
        MockSecurityManager.return_value = mock_manager

        mock_manager.check_permission = MagicMock(return_value=True)

        # Set up test data
        user_id = "user1"
        resource_id = "dataset1"
        action = "read"

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, user_id, resource_id, action)

        # Assertions
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["allowed"])
        MockSecurityManager.assert_called_once()
        mock_manager.check_permission.assert_called_once_with(user_id, resource_id, action)

# Provenance Tools Tests
class ProvenanceToolsTest(BaseToolTester):
    """Tests for provenance tools."""

    @patch('ipfs_datasets_py.data_provenance.ProvenanceManager') # Patch the ProvenanceManager class
    def test_record_provenance(self, MockProvenanceRecorder):
        """Test record_provenance tool."""
        tool_func = self.get_tool_func("provenance_tools", "record_provenance")
        if not tool_func:
            self.skipTest("record_provenance tool not found")

        # Set up mock instance and methods
        mock_recorder = MagicMock()
        MockProvenanceRecorder.return_value = mock_recorder

        mock_recorder.record_provenance = MagicMock()

        # Set up test data
        provenance_data = {
            "entity_id": "dataset1",
            "entity_type": "dataset",
            "derivation": {"source_id": "source1", "process": "transformation"}
        }

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, provenance_data)

        # Assertions
        self.assertEqual(result["status"], "success")
        MockProvenanceRecorder.assert_called_once()
        mock_recorder.record_provenance.assert_called_once_with(provenance_data)

# Web Archive Tools Tests
class WebArchiveToolsTest(BaseToolTester):
    """Tests for web archive tools."""

    @patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor') # Patch the WebArchiveProcessor class
    def test_create_warc(self, MockProcessor):
        """Test create_warc tool."""
        tool_func = self.get_tool_func("web_archive_tools", "create_warc")
        if not tool_func:
            self.skipTest("create_warc tool not found")

        # Set up mock instance
        mock_processor = MagicMock()
        MockProcessor.return_value = mock_processor

        # Set up mock return value
        mock_processor.create_warc = MagicMock(return_value="/tmp/archive.warc")

        # Set up test data
        url = "https://example.com"
        output_path = "/tmp/archive.warc"

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, url, output_path)

        # Assertions
        self.assertEqual(result["status"], "success")
        mock_processor.create_warc.assert_called_once_with(url, output_path)

    @patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor') # Patch the WebArchiveProcessor class
    def test_index_warc(self, MockProcessor):
        """Test index_warc tool."""
        tool_func = self.get_tool_func("web_archive_tools", "index_warc")
        if not tool_func:
            self.skipTest("index_warc tool not found")

        # Set up mock instance
        mock_processor = MagicMock()
        MockProcessor.return_value = mock_processor

        # Set up mock return value
        mock_processor.index_warc = MagicMock(return_value="/tmp/index.cdxj")

        # Set up test data
        warc_path = "/tmp/archive.warc"
        output_path = "/tmp/index.cdxj"

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, warc_path, output_path)

        # Assertions
        self.assertEqual(result["status"], "success")
        mock_processor.index_warc.assert_called_once_with(warc_path, output_path)

    @patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor') # Patch the WebArchiveProcessor class
    def test_extract_dataset_from_cdxj(self, MockProcessor):
        """Test extract_dataset_from_cdxj tool."""
        tool_func = self.get_tool_func("web_archive_tools", "extract_dataset_from_cdxj")
        if not tool_func:
            self.skipTest("extract_dataset_from_cdxj tool not found")

        # Set up mock instance
        mock_processor = MagicMock()
        MockProcessor.return_value = mock_processor

        # Set up mock return value
        mock_processor.extract_dataset_from_cdxj = MagicMock(return_value={"data": [{"url": "example.com"}]})

        # Set up test data
        cdxj_path = "/tmp/index.cdxj"
        output_path = "/tmp/dataset.json"

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, cdxj_path, output_path)

        # Assertions
        self.assertEqual(result["status"], "success")
        mock_processor.extract_dataset_from_cdxj.assert_called_once_with(cdxj_path, output_path)

    @patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor') # Patch the WebArchiveProcessor class
    def test_extract_text_from_warc(self, MockProcessor):
        """Test extract_text_from_warc tool."""
        tool_func = self.get_tool_func("web_archive_tools", "extract_text_from_warc")
        if not tool_func:
            self.skipTest("extract_text_from_warc tool not found")

        # Set up mock instance
        mock_processor = MagicMock()
        MockProcessor.return_value = mock_processor

        # Set up mock return value
        mock_processor.extract_text_from_warc = MagicMock(return_value={"texts": ["Sample text"]})

        # Set up test data
        warc_path = "/tmp/archive.warc"
        output_path = "/tmp/texts.json"

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, warc_path, output_path)

        # Assertions
        self.assertEqual(result["status"], "success")
        mock_processor.extract_text_from_warc.assert_called_once_with(warc_path, output_path)

    @patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor') # Patch the WebArchiveProcessor class
    def test_extract_links_from_warc(self, MockProcessor):
        """Test extract_links_from_warc tool."""
        tool_func = self.get_tool_func("web_archive_tools", "extract_links_from_warc")
        if not tool_func:
            self.skipTest("extract_links_from_warc tool not found")

        # Set up mock instance
        mock_processor = MagicMock()
        MockProcessor.return_value = mock_processor

        # Set up mock return value
        mock_processor.extract_links_from_warc = MagicMock(return_value=["https://example.com/page1"])

        # Set up test data
        warc_path = "/tmp/archive.warc"
        output_path = "/tmp/links.json"

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, warc_path, output_path)

        # Assertions
        self.assertEqual(result["status"], "success")
        mock_processor.extract_links_from_warc.assert_called_once_with(warc_path, output_path)

    @patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor') # Patch the WebArchiveProcessor class
    def test_extract_metadata_from_warc(self, MockProcessor):
        """Test extract_metadata_from_warc tool."""
        tool_func = self.get_tool_func("web_archive_tools", "extract_metadata_from_warc")
        if not tool_func:
            self.skipTest("extract_metadata_from_warc tool not found")

        # Set up mock instance
        mock_processor = MagicMock()
        MockProcessor.return_value = mock_processor

        # Set up mock return value
        mock_processor.extract_metadata_from_warc = MagicMock(return_value={
                "title": "Example Page",
                "description": "This is a sample page"
            })

        # Set up test data
        warc_path = "/tmp/archive.warc"
        output_path = "/tmp/metadata.json"

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, warc_path, output_path)

        # Assertions
        self.assertEqual(result["status"], "success")
        mock_processor.extract_metadata_from_warc.assert_called_once_with(warc_path, output_path)

# CLI Tools Tests
class CLIToolsTest(BaseToolTester):
    """Tests for CLI tools."""

    @patch('subprocess.run') # Patch subprocess.run
    def test_execute_command(self, mock_run):
        """Test execute_command tool."""
        tool_func = self.get_tool_func("cli", "execute_command")
        if not tool_func:
            self.skipTest("execute_command tool not found")

        # Set up mock return value
        mock_process = MagicMock()
        mock_process.stdout = "Command output".encode('utf-8') # Mock stdout as bytes
        mock_process.stderr = "".encode('utf-8') # Mock stderr as bytes
        mock_process.returncode = 0
        # Adjusted mock return value to include 'output' key
        mock_run.return_value = MagicMock(stdout="Command output".encode('utf-8'), stderr="".encode('utf-8'), returncode=0)

        # Set up test data
        command = "echo 'Hello World'"

        # Call function (await since it's async)
        result = self.run_async_test(tool_func, command)

        # Assertions
        self.assertEqual(result["status"], "success")
        self.assertIn("output", result)
        self.assertEqual(result["output"], "Command output")
        mock_run.assert_called_once_with(command, capture_output=True, text=False, check=False) # Check expected args

# Function Tools Tests
class FunctionToolsTest(BaseToolTester):
    """Tests for function tools."""

    @patch('builtins.exec') # Patch builtins.exec
    def test_execute_python_snippet(self):
        """Test execute_python_snippet tool."""
        tool_func = self.get_tool_func("functions", "execute_python_snippet")
        if not tool_func:
            self.skipTest("execute_python_snippet tool not found")

        # Set up test data
        code = "result = 2 + 2"

        # Use patch to protect against potentially dangerous code execution
        with patch('builtins.exec') as mock_exec:
            # Call function (await since it's async)
            result = self.run_async_test(tool_func, code)

            # Assertions
            self.assertEqual(result["status"], "success")
            mock_exec.assert_called_once_with(code, {}, {}) # Check expected args

def run_all_tests():
    """Run all MCP tool tests."""
    # Create and run the test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test classes
    test_classes = [
        DatasetToolsTest,
        IPFSToolsTest,
        VectorToolsTest,
        GraphToolsTest,
        AuditToolsTest,
        SecurityToolsTest,
        ProvenanceToolsTest,
        WebArchiveToolsTest,
        CLIToolsTest,
        FunctionToolsTest
    ]

    for test_class in test_classes:
        suite.addTest(loader.loadTestsFromTestCase(test_class))

    # Run the tests
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)

def main():
    """Main function."""
    # Verify tool structure and implementation
    verifier = MCPToolsVerifier()
    verifier.verify_all()

    # Run tests for all tools
    print("\n\nRUNNING UNIT TESTS FOR MCP TOOLS")
    print("=" * 40)
    run_all_tests()

if __name__ == "__main__":
    main()
