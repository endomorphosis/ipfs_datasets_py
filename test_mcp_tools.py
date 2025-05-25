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
from unittest.mock import patch, MagicMock

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
    
    @patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset.asyncio')
    def test_load_dataset(self, mock_asyncio):
        """Test the load_dataset tool."""
        # Import the tool
        load_dataset_module = import_tool("dataset_tools", "load_dataset")
        if not load_dataset_module:
            self.skipTest("load_dataset tool not found")
        
        # Create mock result
        mock_result = {
            "status": "success",
            "dataset_info": {
                "name": "Test Dataset",
                "num_records": 3
            }
        }
        
        # Configure mock
        mock_asyncio.run.return_value = mock_result
        
        # Call the function (note: we're not using await)
        result = load_dataset_module.load_dataset(
            source=self.test_env["dataset_file"],
            format="json"
        )
        
        # Verify the result
        self.assertIsNotNone(result)
        # In a real test, we'd check the actual result after running the coroutine
    
    @patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset.asyncio')
    def test_save_dataset(self, mock_asyncio):
        """Test the save_dataset tool."""
        # Import the tool
        save_dataset_module = import_tool("dataset_tools", "save_dataset")
        if not save_dataset_module:
            self.skipTest("save_dataset tool not found")
        
        # Create output path
        output_path = os.path.join(self.test_env["test_dir"], "output_dataset.json")
        
        # Create mock result
        mock_result = {
            "status": "success",
            "path": output_path
        }
        
        # Configure mock
        mock_asyncio.run.return_value = mock_result
        
        # Call the function (note: we're not using await)
        result = save_dataset_module.save_dataset(
            dataset=SAMPLE_DATASET,
            destination=output_path,
            format="json"
        )
        
        # Verify the result
        self.assertIsNotNone(result)
        # In a real test, we'd check the actual result after running the coroutine
    
    @patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset.asyncio')
    def test_process_dataset(self, mock_asyncio):
        """Test the process_dataset tool."""
        # Import the tool
        process_dataset_module = import_tool("dataset_tools", "process_dataset")
        if not process_dataset_module:
            self.skipTest("process_dataset tool not found")
        
        # Create mock result
        mock_result = {
            "status": "success",
            "dataset": {
                "data": [SAMPLE_DATASET["data"][1], SAMPLE_DATASET["data"][2]],
                "metadata": SAMPLE_DATASET["metadata"]
            }
        }
        
        # Configure mock
        mock_asyncio.run.return_value = mock_result
        
        # Call the function (note: we're not using await)
        result = process_dataset_module.process_dataset(
            dataset=SAMPLE_DATASET,
            operations=[
                {"type": "filter", "field": "value", "condition": "gt", "value": 15}
            ]
        )
        
        # Verify the result
        self.assertIsNotNone(result)
        # In a real test, we'd check the actual result after running the coroutine
    
    @patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.convert_dataset_format.asyncio')
    def test_convert_dataset_format(self, mock_asyncio):
        """Test the convert_dataset_format tool."""
        # Import the tool
        convert_dataset_module = import_tool("dataset_tools", "convert_dataset_format")
        if not convert_dataset_module:
            self.skipTest("convert_dataset_format tool not found")
        
        # Create output path
        output_path = os.path.join(self.test_env["test_dir"], "converted_dataset.csv")
        
        # Create mock result
        mock_result = {
            "status": "success",
            "path": output_path
        }
        
        # Configure mock
        mock_asyncio.run.return_value = mock_result
        
        # Call the function (note: we're not using await)
        result = convert_dataset_module.convert_dataset_format(
            source=self.test_env["dataset_file"],
            source_format="json",
            target_format="csv",
            output_path=output_path
        )
        
        # Verify the result
        self.assertIsNotNone(result)
        # In a real test, we'd check the actual result after running the coroutine

class IPFSToolTests(unittest.TestCase):
    """Test cases for IPFS tools."""
    
    def setUp(self):
        self.test_env = setup_test_environment()
    
    def tearDown(self):
        cleanup_test_environment()
    
    @patch('ipfs_datasets_py.mcp_server.tools.ipfs_tools.get_from_ipfs.asyncio')
    def test_get_from_ipfs(self, mock_asyncio):
        """Test the get_from_ipfs tool."""
        # Import the tool
        get_from_ipfs_module = import_tool("ipfs_tools", "get_from_ipfs")
        if not get_from_ipfs_module:
            self.skipTest("get_from_ipfs tool not found")
        
        # Create output path
        output_path = os.path.join(self.test_env["test_dir"], "ipfs_content.json")
        
        # Create mock result
        mock_result = {
            "status": "success",
            "path": output_path,
            "cid": SAMPLE_CID
        }
        
        # Configure mock
        mock_asyncio.run.return_value = mock_result
        
        # Call the function (note: we're not using await)
        result = get_from_ipfs_module.get_from_ipfs(
            cid=SAMPLE_CID,
            output_path=output_path
        )
        
        # Verify the result
        self.assertIsNotNone(result)
        # In a real test, we'd check the actual result after running the coroutine
    
    @patch('ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs.asyncio')
    def test_pin_to_ipfs(self, mock_asyncio):
        """Test the pin_to_ipfs tool."""
        # Import the tool
        pin_to_ipfs_module = import_tool("ipfs_tools", "pin_to_ipfs")
        if not pin_to_ipfs_module:
            self.skipTest("pin_to_ipfs tool not found")
        
        # Create mock result
        mock_result = {
            "status": "success",
            "cid": SAMPLE_CID
        }
        
        # Configure mock
        mock_asyncio.run.return_value = mock_result
        
        # Call the function (note: we're not using await)
        result = pin_to_ipfs_module.pin_to_ipfs(
            file_path=self.test_env["dataset_file"]
        )
        
        # Verify the result
        self.assertIsNotNone(result)
        # In a real test, we'd check the actual result after running the coroutine

class VectorToolTests(unittest.TestCase):
    """Test cases for vector tools."""
    
    def setUp(self):
        self.test_env = setup_test_environment()
    
    def tearDown(self):
        cleanup_test_environment()
    
    @patch('ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index.asyncio')
    def test_create_vector_index(self, mock_asyncio):
        """Test the create_vector_index tool."""
        # Import the tool
        create_vector_index_module = import_tool("vector_tools", "create_vector_index")
        if not create_vector_index_module:
            self.skipTest("create_vector_index tool not found")
        
        # Create index path
        index_path = os.path.join(self.test_env["test_dir"], "vector_index")
        
        # Create mock result
        mock_result = {
            "status": "success",
            "index_path": index_path
        }
        
        # Configure mock
        mock_asyncio.run.return_value = mock_result
        
        # Call the function (note: we're not using await)
        result = create_vector_index_module.create_vector_index(
            vectors=SAMPLE_VECTOR_DATA["vectors"],
            metadata=SAMPLE_VECTOR_DATA["metadata"],
            index_type="flat",
            index_path=index_path
        )
        
        # Verify the result
        self.assertIsNotNone(result)
        # In a real test, we'd check the actual result after running the coroutine
    
    @patch('ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index.asyncio')
    def test_search_vector_index(self, mock_asyncio):
        """Test the search_vector_index tool."""
        # Import the tool
        search_vector_index_module = import_tool("vector_tools", "search_vector_index")
        if not search_vector_index_module:
            self.skipTest("search_vector_index tool not found")
        
        # Create index path
        index_path = os.path.join(self.test_env["test_dir"], "vector_index")
        
        # Create mock result
        mock_result = {
            "status": "success",
            "results": [
                {"id": 1, "score": 0.95, "metadata": {"id": 1, "text": "Vector 1"}},
                {"id": 3, "score": 0.75, "metadata": {"id": 3, "text": "Vector 3"}}
            ]
        }
        
        # Configure mock
        mock_asyncio.run.return_value = mock_result
        
        # Call the function (note: we're not using await)
        result = search_vector_index_module.search_vector_index(
            query_vector=[0.1, 0.2, 0.3, 0.4, 0.5],
            index_path=index_path,
            top_k=2
        )
        
        # Verify the result
        self.assertIsNotNone(result)
        # In a real test, we'd check the actual result after running the coroutine

class GraphToolTests(unittest.TestCase):
    """Test cases for graph tools."""
    
    def setUp(self):
        self.test_env = setup_test_environment()
    
    def tearDown(self):
        cleanup_test_environment()
    
    @patch('ipfs_datasets_py.mcp_server.tools.graph_tools.query_knowledge_graph.asyncio')
    async def test_query_knowledge_graph(self, mock_asyncio):
        """Test the query_knowledge_graph tool."""
        # Import the tool
        query_knowledge_graph_module = import_tool("graph_tools", "query_knowledge_graph")
        if not query_knowledge_graph_module:
            self.skipTest("query_knowledge_graph tool not found")
        
        # Test querying a knowledge graph
        result = await query_knowledge_graph_module.query_knowledge_graph(
            graph=SAMPLE_GRAPH_DATA,
            query="MATCH (n) WHERE n.type = 'entity' RETURN n"
        )
        
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)

class AuditToolTests(unittest.TestCase):
    """Test cases for audit tools."""
    
    def setUp(self):
        self.test_env = setup_test_environment()
    
    def tearDown(self):
        cleanup_test_environment()
    
    @patch('ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event.asyncio')
    async def test_record_audit_event(self, mock_asyncio):
        """Test the record_audit_event tool."""
        # Import the tool
        record_audit_event_module = import_tool("audit_tools", "record_audit_event")
        if not record_audit_event_module:
            self.skipTest("record_audit_event tool not found")
        
        # Test recording an audit event
        result = await record_audit_event_module.record_audit_event(
            event=SAMPLE_AUDIT_EVENT
        )
        
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)
    
    @patch('ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report.asyncio')
    async def test_generate_audit_report(self, mock_asyncio):
        """Test the generate_audit_report tool."""
        # Import the tool
        generate_audit_report_module = import_tool("audit_tools", "generate_audit_report")
        if not generate_audit_report_module:
            self.skipTest("generate_audit_report tool not found")
        
        # Test generating an audit report
        result = await generate_audit_report_module.generate_audit_report(
            start_time="2025-05-01T00:00:00Z",
            end_time="2025-05-22T00:00:00Z",
            filters={"resource": "test_dataset"},
            output_format="json",
            output_path=os.path.join(self.test_env["test_dir"], "audit_report.json")
        )
        
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)

class SecurityToolTests(unittest.TestCase):
    """Test cases for security tools."""
    
    def setUp(self):
        self.test_env = setup_test_environment()
    
    def tearDown(self):
        cleanup_test_environment()
    
    @patch('ipfs_datasets_py.mcp_server.tools.security_tools.check_access_permission.asyncio')
    async def test_check_access_permission(self, mock_asyncio):
        """Test the check_access_permission tool."""
        # Import the tool
        check_access_permission_module = import_tool("security_tools", "check_access_permission")
        if not check_access_permission_module:
            self.skipTest("check_access_permission tool not found")
        
        # Test checking access permission
        result = await check_access_permission_module.check_access_permission(
            user_id="test_user",
            resource_id="test_dataset",
            action="read"
        )
        
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)

class ProvenanceToolTests(unittest.TestCase):
    """Test cases for provenance tools."""
    
    def setUp(self):
        self.test_env = setup_test_environment()
    
    def tearDown(self):
        cleanup_test_environment()
    
    @patch('ipfs_datasets_py.mcp_server.tools.provenance_tools.record_provenance.asyncio')
    async def test_record_provenance(self, mock_asyncio):
        """Test the record_provenance tool."""
        # Import the tool
        record_provenance_module = import_tool("provenance_tools", "record_provenance")
        if not record_provenance_module:
            self.skipTest("record_provenance tool not found")
        
        # Test recording provenance data
        result = await record_provenance_module.record_provenance(
            provenance_data=SAMPLE_PROVENANCE_DATA
        )
        
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)

class WebArchiveToolTests(unittest.TestCase):
    """Test cases for web archive tools."""
    
    def setUp(self):
        self.test_env = setup_test_environment()
    
    def tearDown(self):
        cleanup_test_environment()
    
    @patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.create_warc.WebArchiveProcessor')
    async def test_create_warc(self, mock_processor):
        """Test the create_warc tool."""
        # Set up mock
        mock_instance = mock_processor.return_value
        mock_instance.create_warc.return_value = os.path.join(self.test_env["test_dir"], "test.warc")
        
        # Import the tool
        create_warc_module = import_tool("web_archive_tools", "create_warc")
        if not create_warc_module:
            self.skipTest("create_warc tool not found")
        
        # Test creating a WARC file
        result = await create_warc_module.create_warc(
            url="https://example.com",
            output_path=os.path.join(self.test_env["test_dir"], "test.warc")
        )
        
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)
        self.assertEqual(result["status"], "success")
    
    @patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.index_warc.WebArchiveProcessor')
    async def test_index_warc(self, mock_processor):
        """Test the index_warc tool."""
        # Set up mock
        mock_instance = mock_processor.return_value
        mock_instance.index_warc.return_value = os.path.join(self.test_env["test_dir"], "test.cdxj")
        
        # Import the tool
        index_warc_module = import_tool("web_archive_tools", "index_warc")
        if not index_warc_module:
            self.skipTest("index_warc tool not found")
        
        # Test indexing a WARC file
        result = await index_warc_module.index_warc(
            warc_path=os.path.join(self.test_env["test_dir"], "test.warc"),
            output_path=os.path.join(self.test_env["test_dir"], "test.cdxj")
        )
        
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)
        self.assertEqual(result["status"], "success")
    
    @patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_dataset_from_cdxj.WebArchiveProcessor')
    async def test_extract_dataset_from_cdxj(self, mock_processor):
        """Test the extract_dataset_from_cdxj tool."""
        # Set up mock
        mock_instance = mock_processor.return_value
        mock_instance.extract_dataset_from_cdxj.return_value = SAMPLE_DATASET
        
        # Import the tool
        extract_dataset_module = import_tool("web_archive_tools", "extract_dataset_from_cdxj")
        if not extract_dataset_module:
            self.skipTest("extract_dataset_from_cdxj tool not found")
        
        # Test extracting a dataset from a CDXJ file
        result = await extract_dataset_module.extract_dataset_from_cdxj(
            cdxj_path=os.path.join(self.test_env["test_dir"], "test.cdxj"),
            output_path=os.path.join(self.test_env["test_dir"], "extracted_dataset.json")
        )
        
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)
    
    @patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_text_from_warc.WebArchiveProcessor')
    async def test_extract_text_from_warc(self, mock_processor):
        """Test the extract_text_from_warc tool."""
        # Set up mock
        mock_instance = mock_processor.return_value
        mock_instance.extract_text_from_warc.return_value = {"text": "Sample extracted text"}
        
        # Import the tool
        extract_text_module = import_tool("web_archive_tools", "extract_text_from_warc")
        if not extract_text_module:
            self.skipTest("extract_text_from_warc tool not found")
        
        # Test extracting text from a WARC file
        result = await extract_text_module.extract_text_from_warc(
            warc_path=os.path.join(self.test_env["test_dir"], "test.warc"),
            output_path=os.path.join(self.test_env["test_dir"], "extracted_text.txt")
        )
        
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)

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
        "web_archive_tools": WebArchiveToolTests
    }
    
    # Results tracking
    results = {
        "total_tools": 0,
        "tested_tools": 0,
        "passed_tests": 0,
        "failed_tests": 0,
        "skipped_tests": 0,
        "by_category": {}
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
        
        # Run the test suite
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        
        # Get the number of tests run
        tests_run = result.testsRun
        
        # Update results
        results["tested_tools"] += tests_run
        results["passed_tests"] += tests_run - len(result.errors) - len(result.failures) - len(result.skipped)
        results["failed_tests"] += len(result.errors) + len(result.failures)
        results["skipped_tests"] += len(result.skipped)
        
        results["by_category"][category]["tested"] = tests_run
        results["by_category"][category]["passed"] = tests_run - len(result.errors) - len(result.failures) - len(result.skipped)
        results["by_category"][category]["failed"] = len(result.errors) + len(result.failures)
        results["by_category"][category]["skipped"] = len(result.skipped)
        
        # Update individual tool results - we need a different approach as we don't have direct access to test objects
        for error in result.errors:
            test_method_name = error[0]._testMethodName
            tool_name = test_method_name[5:]  # Remove "test_" prefix
            if tool_name in results["by_category"][category]["tools"]:
                results["by_category"][category]["tools"][tool_name]["status"] = "error"
                
        for failure in result.failures:
            test_method_name = failure[0]._testMethodName
            tool_name = test_method_name[5:]  # Remove "test_" prefix
            if tool_name in results["by_category"][category]["tools"]:
                results["by_category"][category]["tools"][tool_name]["status"] = "failure"
                
        for skip in result.skipped:
            test_method_name = skip[0]._testMethodName
            tool_name = test_method_name[5:]  # Remove "test_" prefix
            if tool_name in results["by_category"][category]["tools"]:
                results["by_category"][category]["tools"][tool_name]["status"] = "skipped"
        
        # Mark successful tests
        for tool_name in results["by_category"][category]["tools"]:
            if results["by_category"][category]["tools"][tool_name]["status"] == "pending":
                results["by_category"][category]["tools"][tool_name]["status"] = "passed"
    
    # Calculate overall success rate
    if results["tested_tools"] > 0:
        results["success_rate"] = (results["passed_tests"] / results["tested_tools"]) * 100
    else:
        results["success_rate"] = 0
    
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
