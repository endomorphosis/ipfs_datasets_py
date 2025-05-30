#!/usr/bin/env python3
"""
Comprehensive test suite for IPFS Datasets MCP server tools.

This script tests all MCP tools across different categories to ensure
they function correctly and as expected. Each tool is tested with appropriate
sample data, and results are validated against expected outcomes.

Usage:
    python test_mcp_tools.py [--category CATEGORY]
"""
import os
import sys
import json
import asyncio
import argparse
import logging
import importlib
import tempfile
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable, Tuple, Set
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mcp_tool_test")

# Import IPFS Datasets library
try:
    import ipfs_datasets_py
    from ipfs_datasets_py import mcp_server
    # We'll import the individual tools dynamically later
except ImportError as e:
    logger.error(f"Error importing IPFS Datasets: {e}")
    print(f"Error: Could not import IPFS Datasets library: {e}")
    sys.exit(1)

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent
MCP_SERVER_PATH = PROJECT_ROOT / "ipfs_datasets_py" / "mcp_server"
TOOLS_PATH = MCP_SERVER_PATH / "tools"
TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="mcp_tool_test_"))

# Test data
SAMPLE_DATASET = {
    "metadata": {
        "name": "Test Dataset",
        "description": "A sample dataset for testing",
        "version": "1.0.0",
        "created_at": "2025-05-21T00:00:00Z"
    },
    "data": [
        {"id": 1, "text": "Sample text 1", "value": 10.5},
        {"id": 2, "text": "Sample text 2", "value": 20.3},
        {"id": 3, "text": "Sample text 3", "value": 15.8}
    ]
}

SAMPLE_VECTOR_DATA = {
    "vectors": [
        [0.1, 0.2, 0.3, 0.4, 0.5],
        [0.6, 0.7, 0.8, 0.9, 1.0],
        [0.2, 0.4, 0.6, 0.8, 1.0]
    ],
    "metadata": [
        {"id": 1, "text": "Vector 1"},
        {"id": 2, "text": "Vector 2"},
        {"id": 3, "text": "Vector 3"}
    ]
}

SAMPLE_AUDIT_EVENT = {
    "event_type": "dataset_access",
    "user_id": "test_user",
    "timestamp": "2025-05-21T12:34:56Z",
    "resource": "test_dataset",
    "action": "read",
    "status": "success"
}

SAMPLE_GRAPH_DATA = {
    "nodes": [
        {"id": "n1", "label": "Node 1", "type": "entity"},
        {"id": "n2", "label": "Node 2", "type": "concept"},
        {"id": "n3", "label": "Node 3", "type": "entity"}
    ],
    "edges": [
        {"source": "n1", "target": "n2", "label": "relates_to"},
        {"source": "n2", "target": "n3", "label": "contains"},
        {"source": "n1", "target": "n3", "label": "references"}
    ]
}

SAMPLE_PROVENANCE_DATA = {
    "entity_id": "dataset_123",
    "entity_type": "dataset",
    "timestamp": "2025-05-21T12:34:56Z",
    "actions": [
        {"type": "creation", "agent": "user_1", "timestamp": "2025-05-20T10:00:00Z"},
        {"type": "modification", "agent": "user_2", "timestamp": "2025-05-21T09:30:00Z"}
    ],
    "sources": ["source_1", "source_2"]
}

SAMPLE_CID = "QmV9tSDx9UiPeWExXEeH6aoDvmihvx6jD5eLb4jbTaKGps"

# Initialize test environment
def setup_test_environment():
    """Set up the test environment with necessary files and directories."""
    logger.info(f"Setting up test environment in {TEST_DATA_DIR}")

    # Create test directory if it doesn't exist
    os.makedirs(TEST_DATA_DIR, exist_ok=True)

    # Create test dataset file
    dataset_file = TEST_DATA_DIR / "test_dataset.json"
    with open(dataset_file, "w") as f:
        json.dump(SAMPLE_DATASET, f)

    # Create test vector file
    vector_file = TEST_DATA_DIR / "test_vectors.json"
    with open(vector_file, "w") as f:
        json.dump(SAMPLE_VECTOR_DATA, f)

    # Create test graph file
    graph_file = TEST_DATA_DIR / "test_graph.json"
    with open(graph_file, "w") as f:
        json.dump(SAMPLE_GRAPH_DATA, f)

    return {
        "dataset_file": str(dataset_file),
        "vector_file": str(vector_file),
        "graph_file": str(graph_file),
        "test_dir": str(TEST_DATA_DIR)
    }

def cleanup_test_environment():
    """Clean up the test environment."""
    logger.info(f"Cleaning up test environment in {TEST_DATA_DIR}")
    import shutil
    shutil.rmtree(TEST_DATA_DIR)

# Helper functions for module import
def import_tool(category: str, tool_name: str):
    """Import a tool module dynamically."""
    try:
        # First try importing from the specific category
        return importlib.import_module(f"ipfs_datasets_py.mcp_server.tools.{category}.{tool_name}")
    except ImportError as e:
        logger.warning(f"Could not import tool {tool_name} from {category}: {e}")
        return None

def get_tools_in_category(category: str) -> List[str]:
    """Get all tool names in a category."""
    category_path = TOOLS_PATH / category
    if not category_path.exists():
        return []

    return [
        f.stem
        for f in category_path.iterdir()
        if f.is_file() and f.name.endswith('.py') and not f.name.startswith('__')
    ]

# Tool test functions
class DatasetToolTests(unittest.TestCase):
    """Test cases for dataset tools."""

    def setUp(self):
        self.test_env = setup_test_environment()

    def tearDown(self):
        cleanup_test_environment()

    @patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset.hf_load_dataset')
    async def test_load_dataset(self, mock_hf_load_dataset):
        """Test the load_dataset tool."""
        load_dataset_module = import_tool("dataset_tools", "load_dataset")
        if not load_dataset_module:
            self.skipTest("load_dataset tool not found")

        mock_hf_load_dataset.return_value = MagicMock(
            num_rows=3,
            features={"id": "int", "text": "string", "value": "float"},
            info=MagicMock(to_dict=lambda: {"description": "Mock Dataset"})
        )

        result = await load_dataset_module.load_dataset(
            source=self.test_env["dataset_file"],
            format="json"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"]["num_records"], 3)
        self.assertIn("id", result["summary"]["schema"])

    @patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset.save_dataset_to_file')
    async def test_save_dataset(self, mock_save_dataset_to_file):
        """Test the save_dataset tool."""
        save_dataset_module = import_tool("dataset_tools", "save_dataset")
        if not save_dataset_module:
            self.skipTest("save_dataset tool not found")

        output_path = os.path.join(self.test_env["test_dir"], "output_dataset.json")
        mock_save_dataset_to_file.return_value = {"status": "success", "path": output_path}

        result = await save_dataset_module.save_dataset(
            dataset=SAMPLE_DATASET,
            destination=output_path,
            format="json"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["path"], output_path)

    @patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset.process_dataset_data')
    async def test_process_dataset(self, mock_process_dataset_data):
        """Test the process_dataset tool."""
        process_dataset_module = import_tool("dataset_tools", "process_dataset")
        if not process_dataset_module:
            self.skipTest("process_dataset tool not found")

        mock_process_dataset_data.return_value = {
            "status": "success",
            "dataset": {
                "data": [SAMPLE_DATASET["data"][1], SAMPLE_DATASET["data"][2]],
                "metadata": SAMPLE_DATASET["metadata"]
            }
        }

        result = await process_dataset_module.process_dataset(
            dataset=SAMPLE_DATASET,
            operations=[
                {"type": "filter", "field": "value", "condition": "gt", "value": 15}
            ]
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["dataset"]["data"]), 2)

    @patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.convert_dataset_format.convert_dataset')
    async def test_convert_dataset_format(self, mock_convert_dataset):
        """Test the convert_dataset_format tool."""
        convert_dataset_module = import_tool("dataset_tools", "convert_dataset_format")
        if not convert_dataset_module:
            self.skipTest("convert_dataset_format tool not found")

        output_path = os.path.join(self.test_env["test_dir"], "converted_dataset.csv")
        mock_convert_dataset.return_value = {"status": "success", "path": output_path}

        result = await convert_dataset_module.convert_dataset_format(
            source=self.test_env["dataset_file"],
            source_format="json",
            target_format="csv",
            output_path=output_path
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["path"], output_path)

class IPFSToolTests(unittest.TestCase):
    """Test cases for IPFS tools."""

    def setUp(self):
        self.test_env = setup_test_environment()

    def tearDown(self):
        cleanup_test_environment()

    @patch('ipfs_datasets_py.mcp_server.tools.ipfs_tools.get_from_ipfs.ipfs_kit_py')
    async def test_get_from_ipfs(self, mock_ipfs_kit_py):
        """Test the get_from_ipfs tool."""
        get_from_ipfs_module = import_tool("ipfs_tools", "get_from_ipfs")
        if not get_from_ipfs_module:
            self.skipTest("get_from_ipfs tool not found")

        output_path = os.path.join(self.test_env["test_dir"], "ipfs_content.json")

        # Mock the async methods
        mock_ipfs_kit_py.get_async = AsyncMock(return_value=None)
        mock_ipfs_kit_py.cat_async = AsyncMock(return_value=b'{"key": "value"}')

        # Test with output_path
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=100):
            result = await get_from_ipfs_module.get_from_ipfs(
                cid=SAMPLE_CID,
                output_path=output_path
            )
            self.assertIsNotNone(result)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["output_path"], output_path)
            mock_ipfs_kit_py.get_async.assert_called_once_with(SAMPLE_CID, output_path, timeout=60)

        # Reset mocks for next test
        mock_ipfs_kit_py.get_async.reset_mock()
        mock_ipfs_kit_py.cat_async.reset_mock()

        # Test without output_path (cat)
        result = await get_from_ipfs_module.get_from_ipfs(
            cid=SAMPLE_CID
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["content"], '{"key": "value"}')
        mock_ipfs_kit_py.cat_async.assert_called_once_with(SAMPLE_CID, timeout=60)

    @patch('ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs.ipfs_kit_py')
    async def test_pin_to_ipfs(self, mock_ipfs_kit_py):
        """Test the pin_to_ipfs tool."""
        pin_to_ipfs_module = import_tool("ipfs_tools", "pin_to_ipfs")
        if not pin_to_ipfs_module:
            self.skipTest("pin_to_ipfs tool not found")

        # Mock the async method
        mock_ipfs_kit_py.add_async = AsyncMock(return_value={"Hash": SAMPLE_CID, "Size": 123, "Name": "test_dataset.json"})

        with patch('os.path.exists', return_value=True):
            result = await pin_to_ipfs_module.pin_to_ipfs(
                content_path=self.test_env["dataset_file"]
            )
            self.assertIsNotNone(result)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["cid"], SAMPLE_CID)
            mock_ipfs_kit_py.add_async.assert_called_once_with(
                self.test_env["dataset_file"],
                recursive=True,
                wrap_with_directory=False,
                hash="sha2-256"
            )

class VectorToolTests(unittest.TestCase):
    """Test cases for vector tools."""

    def setUp(self):
        self.test_env = setup_test_environment()

    def tearDown(self):
        cleanup_test_environment()

    @patch('ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index.IPFSKnnIndex')
    async def test_create_vector_index(self, mock_ipfs_knn_index):
        """Test the create_vector_index tool."""
        create_vector_index_module = import_tool("vector_tools", "create_vector_index")
        if not create_vector_index_module:
            self.skipTest("create_vector_index tool not found")

        mock_instance = mock_ipfs_knn_index.return_value
        mock_instance.add_vectors.return_value = ["vec1", "vec2", "vec3"]
        mock_instance.index_id = "test_index_id"
        mock_instance.index_name = "test_index_name"

        result = await create_vector_index_module.create_vector_index(
            vectors=SAMPLE_VECTOR_DATA["vectors"],
            metadata=SAMPLE_VECTOR_DATA["metadata"],
            metric="cosine"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["index_id"], "test_index_id")
        self.assertEqual(result["num_vectors"], 3)

    @patch('ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index.IPFSKnnIndexManager')
    async def test_search_vector_index(self, mock_ipfs_knn_index_manager):
        """Test the search_vector_index tool."""
        search_vector_index_module = import_tool("vector_tools", "search_vector_index")
        if not search_vector_index_module:
            self.skipTest("search_vector_index tool not found")

        mock_manager_instance = mock_ipfs_knn_index_manager.return_value
        mock_index_instance = MagicMock()
        mock_manager_instance.get_index.return_value = mock_index_instance

        mock_index_instance.search.return_value = [
            MagicMock(id=1, score=0.95, metadata={"id": 1, "text": "Vector 1"}),
            MagicMock(id=3, score=0.75, metadata={"id": 3, "text": "Vector 3"})
        ]

        result = await search_vector_index_module.search_vector_index(
            index_id="test_index_id",
            query_vector=[0.1, 0.2, 0.3, 0.4, 0.5],
            top_k=2
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["num_results"], 2)
        self.assertEqual(result["results"][0]["id"], 1)

class GraphToolTests(unittest.TestCase):
    """Test cases for graph tools."""

    def setUp(self):
        self.test_env = setup_test_environment()

    def tearDown(self):
        cleanup_test_environment()

    @patch('ipfs_datasets_py.mcp_server.tools.graph_tools.query_knowledge_graph.GraphRAGProcessor')
    async def test_query_knowledge_graph(self, mock_graph_rag_processor):
        """Test the query_knowledge_graph tool."""
        query_knowledge_graph_module = import_tool("graph_tools", "query_knowledge_graph")
        if not query_knowledge_graph_module:
            self.skipTest("query_knowledge_graph tool not found")

        mock_processor_instance = mock_graph_rag_processor.return_value
        mock_processor_instance.load_graph.return_value = MagicMock()
        mock_processor_instance.execute_sparql.return_value = [
            {"id": "n1", "label": "Node 1"},
            {"id": "n3", "label": "Node 3"}
        ]

        result = await query_knowledge_graph_module.query_knowledge_graph(
            graph_id="test_graph_id",
            query="MATCH (n) WHERE n.type = 'entity' RETURN n",
            query_type="sparql"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["num_results"], 2)
        self.assertEqual(result["results"][0]["id"], "n1")

class AuditToolTests(unittest.TestCase):
    """Test cases for audit tools."""

    def setUp(self):
        self.test_env = setup_test_environment()

    def tearDown(self):
        cleanup_test_environment()

    @patch('ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event.AuditLogger')
    def test_record_audit_event(self, mock_audit_logger):
        """Test the record_audit_event tool."""
        record_audit_event_module = import_tool("audit_tools", "record_audit_event")
        if not record_audit_event_module:
            self.skipTest("record_audit_event tool not found")

        mock_instance = mock_audit_logger.get_instance.return_value
        mock_instance.log.return_value = "mock_event_id"

        result = record_audit_event_module.record_audit_event(
            action=SAMPLE_AUDIT_EVENT["action"],
            resource_id=SAMPLE_AUDIT_EVENT["resource"],
            resource_type="test_resource_type", # Added resource_type
            user_id=SAMPLE_AUDIT_EVENT["user_id"],
            severity="info"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["event_id"], "mock_event_id")

    @patch('ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report.AuditReportGenerator')
    async def test_generate_audit_report(self, mock_audit_report_generator):
        """Test the generate_audit_report tool."""
        generate_audit_report_module = import_tool("audit_tools", "generate_audit_report")
        if not generate_audit_report_module:
            self.skipTest("generate_audit_report tool not found")

        mock_instance = mock_audit_report_generator.return_value
        mock_instance.generate_comprehensive_report.return_value = {"report_id": "mock_report_id", "timestamp": "mock_timestamp"}
        mock_instance.export_report.return_value = os.path.join(self.test_env["test_dir"], "audit_report.json")

        result = await generate_audit_report_module.generate_audit_report(
            report_type="comprehensive",
            output_format="json",
            output_path=os.path.join(self.test_env["test_dir"], "audit_report.json")
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["report_type"], "comprehensive")
        self.assertEqual(result["output_path"], os.path.join(self.test_env["test_dir"], "audit_report.json"))

class SecurityToolTests(unittest.TestCase):
    """Test cases for security tools."""

    def setUp(self):
        self.test_env = setup_test_environment()

    def tearDown(self):
        cleanup_test_environment()

    @patch('ipfs_datasets_py.mcp_server.tools.security_tools.check_access_permission.SecurityManager')
    async def test_check_access_permission(self, mock_security_manager):
        """Test the check_access_permission tool."""
        check_access_permission_module = import_tool("security_tools", "check_access_permission")
        if not check_access_permission_module:
            self.skipTest("check_access_permission tool not found")

        mock_instance = mock_security_manager.return_value
        mock_instance.check_access.return_value = True

        result = await check_access_permission_module.check_access_permission(
            user_id="test_user",
            resource_id="test_dataset",
            permission_type="read"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["allowed"])

class ProvenanceToolTests(unittest.TestCase):
    """Test cases for provenance tools."""

    def setUp(self):
        self.test_env = setup_test_environment()

    def tearDown(self):
        cleanup_test_environment()

    @patch('ipfs_datasets_py.mcp_server.tools.provenance_tools.record_provenance.EnhancedProvenanceManager')
    async def test_record_provenance(self, mock_provenance_manager):
        """Test the record_provenance tool."""
        record_provenance_module = import_tool("provenance_tools", "record_provenance")
        if not record_provenance_module:
            self.skipTest("record_provenance tool not found")

        mock_instance = mock_provenance_manager.return_value
        mock_instance.record_operation.return_value = "mock_provenance_id"
        mock_instance.get_record.return_value = {
            "provenance_id": "mock_provenance_id",
            "timestamp": "2025-05-21T12:34:56Z"
        }

        result = await record_provenance_module.record_provenance(
            dataset_id="test_dataset_id",
            operation="test_operation",
            inputs=["input1"],
            parameters={"param1": "value1"},
            description="Test provenance record",
            agent_id="test_agent",
            timestamp="2025-05-21T12:34:56Z",
            tags=["tag1", "tag2"]
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["provenance_id"], "mock_provenance_id")

class WebArchiveToolTests(unittest.TestCase):
    """Test cases for web archive tools."""

    def setUp(self):
        self.test_env = setup_test_environment()

    def tearDown(self):
        cleanup_test_environment()

    @patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.create_warc.WebArchiveProcessor')
    def test_create_warc(self, mock_processor):
        """Test the create_warc tool."""
        create_warc_module = import_tool("web_archive_tools", "create_warc")
        if not create_warc_module:
            self.skipTest("create_warc tool not found")

        mock_instance = mock_processor.return_value
        mock_instance.create_warc.return_value = os.path.join(self.test_env["test_dir"], "test.warc")

        result = create_warc_module.create_warc(
            url="https://example.com",
            output_path=os.path.join(self.test_env["test_dir"], "test.warc")
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["warc_path"], os.path.join(self.test_env["test_dir"], "test.warc"))

    @patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.index_warc.WebArchiveProcessor')
    def test_index_warc(self, mock_processor):
        """Test the index_warc tool."""
        index_warc_module = import_tool("web_archive_tools", "index_warc")
        if not index_warc_module:
            self.skipTest("index_warc tool not found")

        mock_instance = mock_processor.return_value
        mock_instance.index_warc.return_value = os.path.join(self.test_env["test_dir"], "test.cdxj")

        result = index_warc_module.index_warc(
            warc_path=os.path.join(self.test_env["test_dir"], "test.warc"),
            output_path=os.path.join(self.test_env["test_dir"], "test.cdxj")
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["cdxj_path"], os.path.join(self.test_env["test_dir"], "test.cdxj"))

    @patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_dataset_from_cdxj.WebArchiveProcessor')
    def test_extract_dataset_from_cdxj(self, mock_processor):
        """Test the extract_dataset_from_cdxj tool."""
        extract_dataset_module = import_tool("web_archive_tools", "extract_dataset_from_cdxj")
        if not extract_dataset_module:
            self.skipTest("extract_dataset_from_cdxj tool not found")

        mock_instance = mock_processor.return_value
        mock_instance.extract_dataset_from_cdxj.return_value = SAMPLE_DATASET

        result = extract_dataset_module.extract_dataset_from_cdxj(
            cdxj_path=os.path.join(self.test_env["test_dir"], "test.cdxj"),
            output_format="dict"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["dataset"], SAMPLE_DATASET)

    @patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_text_from_warc.WebArchiveProcessor')
    def test_extract_text_from_warc(self, mock_processor):
        """Test the extract_text_from_warc tool."""
        extract_text_module = import_tool("web_archive_tools", "extract_text_from_warc")
        if not extract_text_module:
            self.skipTest("extract_text_from_warc tool not found")

        mock_instance = mock_processor.return_value
        mock_instance.extract_text_from_warc.return_value = [{"uri": "http://example.com", "text": "Sample extracted text"}]

        result = extract_text_module.extract_text_from_warc(
            warc_path=os.path.join(self.test_env["test_dir"], "test.warc")
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertIn("records", result)
        self.assertEqual(len(result["records"]), 1)

    @patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_links_from_warc.WebArchiveProcessor')
    def test_extract_links_from_warc(self, mock_processor):
        """Test the extract_links_from_warc tool."""
        extract_links_module = import_tool("web_archive_tools", "extract_links_from_warc")
        if not extract_links_module:
            self.skipTest("extract_links_from_warc tool not found")

        mock_instance = mock_processor.return_value
        mock_instance.extract_links_from_warc.return_value = [
            {"uri": "http://example.com", "links": ["http://example.com/page1", "http://example.com/page2"]}
        ]

        result = extract_links_module.extract_links_from_warc(
            warc_path=os.path.join(self.test_env["test_dir"], "test.warc")
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertIn("records", result)
        self.assertEqual(len(result["records"]), 1)

    @patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_metadata_from_warc.WebArchiveProcessor')
    def test_extract_metadata_from_warc(self, mock_processor):
        """Test the extract_metadata_from_warc tool."""
        extract_metadata_module = import_tool("web_archive_tools", "extract_metadata_from_warc")
        if not extract_metadata_module:
            self.skipTest("extract_metadata_from_warc tool not found")

        mock_instance = mock_processor.return_value
        mock_instance.extract_metadata_from_warc.return_value = [
            {"uri": "http://example.com", "metadata": {"title": "Example", "status": "200"}}
        ]

        result = extract_metadata_module.extract_metadata_from_warc(
            warc_path=os.path.join(self.test_env["test_dir"], "test.warc")
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertIn("records", result)
        self.assertEqual(len(result["records"]), 1)

class CLIToolTests(unittest.TestCase):
    """Test cases for CLI tools."""

    def setUp(self):
        self.test_env = setup_test_environment()

    def tearDown(self):
        cleanup_test_environment()

    @patch('subprocess.run')
    async def test_execute_command(self, mock_subprocess_run):
        """Test the execute_command tool."""
        execute_command_module = import_tool("cli", "execute_command")
        if not execute_command_module:
            self.skipTest("execute_command tool not found")

        mock_subprocess_run.return_value = MagicMock(
            returncode=0,
            stdout="Command executed successfully",
            stderr=""
        )

        result = await execute_command_module.execute_command(
            command="echo 'test'",
            timeout=30
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["return_code"], 0)
        self.assertEqual(result["stdout"], "Command executed successfully")

class FunctionToolTests(unittest.TestCase):
    """Test cases for function tools."""

    def setUp(self):
        self.test_env = setup_test_environment()

    def tearDown(self):
        cleanup_test_environment()

    @patch('exec')
    async def test_execute_python_snippet(self, mock_exec):
        """Test the execute_python_snippet tool."""
        execute_python_snippet_module = import_tool("functions", "execute_python_snippet")
        if not execute_python_snippet_module:
            self.skipTest("execute_python_snippet tool not found")

        # Mock successful execution
        mock_exec.return_value = None

        result = await execute_python_snippet_module.execute_python_snippet(
            code="result = 2 + 2",
            globals_dict={},
            timeout=30
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")

# Run tests for all tools
def run_tool_tests(categories: Optional[List[str]] = None):
    """Run tests for all tools or specified categories."""
    # Determine which categories to test
    all_categories = [
        d.name for d in TOOLS_PATH.iterdir()
        if d.is_dir() and not d.name.startswith("__")
    ]

    categories_to_test = categories if categories else all_categories

    logger.info(f"Running tests for categories: {', '.join(categories_to_test)}")

    # Map of category to test class
    category_test_map = {
        "dataset_tools": DatasetToolTests,
        "ipfs_tools": IPFSToolTests,
        "vector_tools": VectorToolTests,
        "graph_tools": GraphToolTests,
        "audit_tools": AuditToolTests,
        "security_tools": SecurityToolTests,
        "provenance_tools": ProvenanceToolTests,
        "web_archive_tools": WebArchiveToolTests,
        "cli": CLIToolTests,
        "functions": FunctionToolTests
    }

    # Results tracking
    results = {
        "total_tools": 0,
        "tested_tools": 0,
        "passed_tests": 0,
        "failed_tests": 0,
        "skipped_tests": 0,
        "by_category": {},
        "success_rate": 0.0
    }

    # Run tests for each category
    for category in categories_to_test:
        if category not in category_test_map:
            logger.warning(f"No test class defined for category: {category}")
            continue

        # Get tools in this category
        tools = get_tools_in_category(category)
        if not tools:
            logger.warning(f"No tools found in category: {category}")
            continue

        logger.info(f"Testing {len(tools)} tools in category: {category}")
        results["total_tools"] += len(tools)

        # Initialize category results
        results["by_category"][category] = {
            "total": len(tools),
            "tested": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "tools": {}
        }

        # Create test suite for this category
        suite = unittest.TestSuite()
        test_class = category_test_map[category]

        # Add each test method to the suite
        for method_name in dir(test_class):
            if method_name.startswith("test_"):
                tool_name = method_name[5:]  # Remove "test_" prefix
                if tool_name in tools:
                    suite.addTest(test_class(method_name))
                    results["by_category"][category]["tools"][tool_name] = {
                        "status": "pending"
                    }

        # Run the tests for this category
        runner = unittest.TextTestRunner(verbosity=2, stream=open(os.devnull, 'w'))
        test_result = runner.run(suite)

        # Update results
        category_tested = test_result.testsRun
        category_failed = len(test_result.failures) + len(test_result.errors)
        category_skipped = len(test_result.skipped)
        category_passed = category_tested - category_failed - category_skipped

        results["tested_tools"] += category_tested
        results["passed_tests"] += category_passed
        results["failed_tests"] += category_failed
        results["skipped_tests"] += category_skipped

        results["by_category"][category]["tested"] = category_tested
        results["by_category"][category]["passed"] = category_passed
        results["by_category"][category]["failed"] = category_failed
        results["by_category"][category]["skipped"] = category_skipped

        # Update individual tool results
        for test, error in test_result.failures + test_result.errors:
            tool_name = test._testMethodName[5:]  # Remove "test_" prefix
            if tool_name in results["by_category"][category]["tools"]:
                results["by_category"][category]["tools"][tool_name]["status"] = "failed"
                results["by_category"][category]["tools"][tool_name]["error"] = str(error)

        for test, reason in test_result.skipped:
            tool_name = test._testMethodName[5:]  # Remove "test_" prefix
            if tool_name in results["by_category"][category]["tools"]:
                results["by_category"][category]["tools"][tool_name]["status"] = "skipped"
                results["by_category"][category]["tools"][tool_name]["reason"] = reason

        # Mark remaining as passed
        for tool_name in results["by_category"][category]["tools"]:
            if results["by_category"][category]["tools"][tool_name]["status"] == "pending":
                results["by_category"][category]["tools"][tool_name]["status"] = "passed"

    # Calculate overall success rate
    if results["tested_tools"] > 0:
        results["success_rate"] = (results["passed_tests"] / results["tested_tools"]) * 100

    return results

def main():
    """Main entry point."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Test IPFS Datasets MCP tools")
    parser.add_argument("--category", help="Specific tool category to test")
    args = parser.parse_args()

    # Determine categories to test
    categories = [args.category] if args.category else None

    # Run the tests
    results = run_tool_tests(categories)

    # Print summary report
    print("\n" + "=" * 60)
    print("MCP Tool Test Results Summary")
    print("=" * 60)
    print(f"Total tools: {results['total_tools']}")
    print(f"Tests run: {results['tested_tools']}")
    print(f"Passed: {results['passed_tests']}")
    print(f"Failed: {results['failed_tests']}")
    print(f"Skipped: {results['skipped_tests']}")
    print(f"Success rate: {results['success_rate']:.1f}%")

    print("\nResults by category:")
    for category, cat_results in results["by_category"].items():
        print(f"  {category}: {cat_results['passed']}/{cat_results['tested']} passed")

    # Save detailed results
    with open("mcp_tool_test_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nDetailed results saved to: mcp_tool_test_results.json")

    # Return overall success status
    return results["failed_tests"] == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
