#!/usr/bin/env python3
"""
Improved MCP Tools Test Suite

This script provides comprehensive testing for all MCP tools with proper
async handling and correct mocking based on actual implementations.
"""
import os
import sys
import json
import time
import inspect
import unittest
import importlib
import logging
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("improved_mcp_test")

# Add project root to path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

class AsyncTestCase(unittest.TestCase):
    """Base test case that supports async test methods."""
    
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
    
    def tearDown(self):
        self.loop.close()
    
    def async_test(self, coro):
        """Helper to run async test methods."""
        return self.loop.run_until_complete(coro)

class BaseToolTester(AsyncTestCase):
    """Base class for MCP tool tests with async support."""
    
    def get_tool_func(self, category, tool_name):
        """Get the tool function."""
        import_path = f"ipfs_datasets_py.mcp_server.tools.{category}.{tool_name}"
        try:
            module = importlib.import_module(import_path)
            if hasattr(module, tool_name):
                return getattr(module, tool_name)
            return None
        except ImportError as e:
            logger.warning(f"Could not import {import_path}: {e}")
            return None

class DatasetToolsTest(BaseToolTester):
    """Tests for dataset tools."""
    
    @patch('datasets.load_dataset')
    def test_load_dataset(self, mock_hf_load_dataset):
        """Test load_dataset tool."""
        tool_func = self.get_tool_func("dataset_tools", "load_dataset")
        if not tool_func:
            self.skipTest("load_dataset tool not found")
        
        # Set up mock return value
        mock_dataset = MagicMock()
        mock_info = MagicMock()
        mock_info.to_dict.return_value = {"dataset_name": "test_dataset", "description": "Test dataset"}
        mock_dataset.info = mock_info
        mock_dataset.features = {"text": "string"}
        mock_dataset.__len__ = MagicMock(return_value=100)
        mock_hf_load_dataset.return_value = mock_dataset
        
        # Call async function
        async def run_test():
            result = await tool_func("test_source", format="json")
            self.assertEqual(result["status"], "success")
            self.assertIn("dataset_id", result)
            self.assertIn("metadata", result)
            
        self.async_test(run_test())
    
    def test_save_dataset(self):
        """Test save_dataset tool."""
        tool_func = self.get_tool_func("dataset_tools", "save_dataset")
        if not tool_func:
            self.skipTest("save_dataset tool not found")
        
        async def run_test():
            # Mock the entire DatasetManager import chain
            mock_dataset = MagicMock()
            mock_dataset.format = "json"
            mock_dataset.save_async = AsyncMock(return_value={"size": 1024, "location": "/tmp/test.json"})
            
            mock_manager = MagicMock()
            mock_manager.get_dataset = MagicMock(return_value=mock_dataset)
            
            # Create a mock module for the import
            mock_ipfs_datasets_py = MagicMock()
            mock_ipfs_datasets_py.DatasetManager = MagicMock(return_value=mock_manager)
            
            # Patch sys.modules to handle the dynamic import
            with patch.dict('sys.modules', {'ipfs_datasets_py': mock_ipfs_datasets_py}):
                result = await tool_func("test_dataset_id", "/tmp/test.json", format="json")
                self.assertEqual(result["status"], "success")
                
        self.async_test(run_test())
    
    def test_process_dataset(self):
        """Test process_dataset tool."""
        tool_func = self.get_tool_func("dataset_tools", "process_dataset")
        if not tool_func:
            self.skipTest("process_dataset tool not found")
        
        async def run_test():
            operations = [{"type": "filter", "field": "text", "value": "test"}]
            result = await tool_func("test_dataset_id", operations)
            self.assertEqual(result["status"], "success")
            
        self.async_test(run_test())
    
    def test_convert_dataset_format(self):
        """Test convert_dataset_format tool."""
        tool_func = self.get_tool_func("dataset_tools", "convert_dataset_format")
        if not tool_func:
            self.skipTest("convert_dataset_format tool not found")
        
        async def run_test():
            # The libp2p_kit is now a stub, so we can import it directly
            mock_dataset = MagicMock()
            mock_dataset.format = "json"
            mock_dataset.save_async = AsyncMock(return_value={"size": 1024})
            
            # Mock the DistributedDatasetManager from the stub
            with patch('ipfs_datasets_py.libp2p_kit.DistributedDatasetManager') as mock_manager_class:
                mock_manager = MagicMock()
                mock_manager_class.return_value = mock_manager
                
                mock_shard_manager = MagicMock()
                mock_manager.shard_manager = mock_shard_manager
                mock_shard_manager.get_dataset.return_value = mock_dataset
                
                result = await tool_func("test_dataset_id", "csv", output_path="/tmp/output.csv")
                self.assertEqual(result["status"], "success")
            
        self.async_test(run_test())

class IPFSToolsTest(BaseToolTester):
    """Tests for IPFS tools."""
    
    def test_pin_to_ipfs(self):
        """Test pin_to_ipfs tool."""
        tool_func = self.get_tool_func("ipfs_tools", "pin_to_ipfs")
        if not tool_func:
            self.skipTest("pin_to_ipfs tool not found")
        
        async def run_test():
            with patch('ipfs_datasets_py.ipfs_kit_py.high_level_api.IPFSSimpleAPI') as mock_api:
                mock_client = MagicMock()
                mock_api.return_value = mock_client
                mock_client.pin_add = MagicMock(return_value={"Pins": ["QmTest123"]})
                
                result = await tool_func("/tmp/test.json")
                self.assertEqual(result["status"], "success")
                self.assertIn("cid", result)
                
        self.async_test(run_test())

class AuditToolsTest(BaseToolTester):
    """Tests for audit tools."""
    
    def test_record_audit_event(self):
        """Test record_audit_event tool."""
        tool_func = self.get_tool_func("audit_tools", "record_audit_event")
        if not tool_func:
            self.skipTest("record_audit_event tool not found")
        
        # This is a sync function, no async needed
        result = tool_func(
            action="test_action",
            resource_id="test_resource",
            resource_type="dataset",
            user_id="test_user"
        )
        self.assertEqual(result["status"], "success")
    
    def test_generate_audit_report(self):
        """Test generate_audit_report tool."""
        tool_func = self.get_tool_func("audit_tools", "generate_audit_report")
        if not tool_func:
            self.skipTest("generate_audit_report tool not found")
        
        async def run_test():
            result = await tool_func(
                report_type="comprehensive",
                start_time="2025-01-01T00:00:00Z",
                end_time="2025-01-31T23:59:59Z"
            )
            self.assertEqual(result["status"], "success")
            
        self.async_test(run_test())

class WebArchiveToolsTest(BaseToolTester):
    """Tests for web archive tools."""
    
    def test_create_warc(self):
        """Test create_warc tool."""
        tool_func = self.get_tool_func("web_archive_tools", "create_warc")
        if not tool_func:
            self.skipTest("create_warc tool not found")
        
        with patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor') as mock_processor:
            mock_instance = MagicMock()
            mock_processor.return_value = mock_instance
            mock_instance.create_warc = MagicMock(return_value="/tmp/test.warc")
            
            result = tool_func("https://example.com", "/tmp/test.warc")
            self.assertEqual(result["status"], "success")
    
    def test_index_warc(self):
        """Test index_warc tool."""
        tool_func = self.get_tool_func("web_archive_tools", "index_warc")
        if not tool_func:
            self.skipTest("index_warc tool not found")
        
        with patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor') as mock_processor:
            mock_instance = MagicMock()
            mock_processor.return_value = mock_instance
            mock_instance.index_warc = MagicMock(return_value="/tmp/test.cdxj")
            
            result = tool_func("/tmp/test.warc", "/tmp/test.cdxj")
            self.assertEqual(result["status"], "success")
    
    def test_extract_dataset_from_cdxj(self):
        """Test extract_dataset_from_cdxj tool."""
        tool_func = self.get_tool_func("web_archive_tools", "extract_dataset_from_cdxj")
        if not tool_func:
            self.skipTest("extract_dataset_from_cdxj tool not found")
        
        with patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor') as mock_processor:
            mock_instance = MagicMock()
            mock_processor.return_value = mock_instance
            mock_instance.extract_dataset_from_cdxj = MagicMock(return_value={"status": "success"})
            
            result = tool_func("/tmp/test.cdxj", "/tmp/dataset.json")
            self.assertEqual(result["status"], "success")
    
    def test_extract_text_from_warc(self):
        """Test extract_text_from_warc tool."""
        tool_func = self.get_tool_func("web_archive_tools", "extract_text_from_warc")
        if not tool_func:
            self.skipTest("extract_text_from_warc tool not found")
        
        with patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor') as mock_processor:
            mock_instance = MagicMock()
            mock_processor.return_value = mock_instance
            mock_instance.extract_text_from_warc = MagicMock(return_value=[{"uri": "test", "text": "content"}])
            
            result = tool_func("/tmp/test.warc")
            self.assertEqual(result["status"], "success")
    
    def test_extract_links_from_warc(self):
        """Test extract_links_from_warc tool."""
        tool_func = self.get_tool_func("web_archive_tools", "extract_links_from_warc")
        if not tool_func:
            self.skipTest("extract_links_from_warc tool not found")
        
        with patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor') as mock_processor:
            mock_instance = MagicMock()
            mock_processor.return_value = mock_instance
            mock_instance.extract_links_from_warc = MagicMock(return_value=[{"uri": "test", "links": ["http://example.com"]}])
            
            result = tool_func("/tmp/test.warc")
            self.assertEqual(result["status"], "success")
    
    def test_extract_metadata_from_warc(self):
        """Test extract_metadata_from_warc tool."""
        tool_func = self.get_tool_func("web_archive_tools", "extract_metadata_from_warc")
        if not tool_func:
            self.skipTest("extract_metadata_from_warc tool not found")
        
        with patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor') as mock_processor:
            mock_instance = MagicMock()
            mock_processor.return_value = mock_instance
            mock_instance.extract_metadata_from_warc = MagicMock(return_value=[{"uri": "test", "metadata": {"title": "Test"}}])
            
            result = tool_func("/tmp/test.warc")
            self.assertEqual(result["status"], "success")

class CLIToolsTest(BaseToolTester):
    """Tests for CLI tools."""
    
    def test_execute_command(self):
        """Test execute_command tool."""
        tool_func = self.get_tool_func("cli", "execute_command")
        if not tool_func:
            self.skipTest("execute_command tool not found")
        
        async def run_test():
            result = await tool_func("echo test")
            self.assertEqual(result["status"], "success")
            # The command doesn't actually execute for security reasons
            self.assertIn("message", result)
                
        self.async_test(run_test())

class FunctionToolsTest(BaseToolTester):
    """Tests for function tools."""
    
    def test_execute_python_snippet(self):
        """Test execute_python_snippet tool."""
        tool_func = self.get_tool_func("functions", "execute_python_snippet")
        if not tool_func:
            self.skipTest("execute_python_snippet tool not found")
        
        # This is likely a sync function that returns a dict directly
        result = tool_func("x = 2 + 2\nprint(x)")
        self.assertEqual(result["status"], "success")

class SecurityToolsTest(BaseToolTester):
    """Tests for security tools."""
    
    def test_check_access_permission(self):
        """Test check_access_permission tool."""
        tool_func = self.get_tool_func("security_tools", "check_access_permission")
        if not tool_func:
            self.skipTest("check_access_permission tool not found")
        
        async def run_test():
            result = await tool_func(
                resource_id="test_resource_123",
                user_id="test_user_456",
                permission_type="read",
                resource_type="dataset"
            )
            self.assertEqual(result["status"], "success")
            self.assertIn("allowed", result)
            
        self.async_test(run_test())

class IPFSToolsExtendedTest(BaseToolTester):
    """Tests for additional IPFS tools."""
    
    def test_get_from_ipfs(self):
        """Test get_from_ipfs tool."""
        tool_func = self.get_tool_func("ipfs_tools", "get_from_ipfs")
        if not tool_func:
            self.skipTest("get_from_ipfs tool not found")
        
        async def run_test():
            # Mock the ipfs_kit_py import and the configs
            with patch('ipfs_datasets_py.ipfs_kit_py') as mock_ipfs_kit, \
                 patch('ipfs_datasets_py.configs') as mock_configs, \
                 patch('os.path.exists', return_value=True), \
                 patch('os.path.getsize', return_value=1024), \
                 patch('os.path.isfile', return_value=True):
                
                mock_configs.ipfs_kit_integration = "direct"
                mock_ipfs_kit.get_async = AsyncMock()
                
                result = await tool_func("QmTest123", "/tmp/output")
                self.assertEqual(result["status"], "success")
                self.assertIn("output_path", result)
                
        self.async_test(run_test())

class VectorToolsTest(BaseToolTester):
    """Tests for vector tools."""
    
    def test_create_vector_index(self):
        """Test create_vector_index tool."""
        tool_func = self.get_tool_func("vector_tools", "create_vector_index")
        if not tool_func:
            self.skipTest("create_vector_index tool not found")
        
        async def run_test():
            vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
            result = await tool_func(
                vectors=vectors,
                dimension=3,
                metric="cosine",
                index_name="test_index"
            )
            self.assertEqual(result["status"], "success")
            self.assertIn("index_id", result)
            
        self.async_test(run_test())
    
    def test_search_vector_index(self):
        """Test search_vector_index tool."""
        tool_func = self.get_tool_func("vector_tools", "search_vector_index")
        if not tool_func:
            self.skipTest("search_vector_index tool not found")
        
        async def run_test():
            query_vector = [0.1, 0.2, 0.3]
            result = await tool_func(
                index_id="test_index_123",
                query_vector=query_vector,
                k=5
            )
            self.assertEqual(result["status"], "success")
            self.assertIn("results", result)
            
        self.async_test(run_test())

class GraphToolsTest(BaseToolTester):
    """Tests for graph tools."""
    
    def test_query_knowledge_graph(self):
        """Test query_knowledge_graph tool."""
        tool_func = self.get_tool_func("graph_tools", "query_knowledge_graph")
        if not tool_func:
            self.skipTest("query_knowledge_graph tool not found")
        
        async def run_test():
            result = await tool_func(
                graph_id="test_graph_123",
                query="MATCH (n) RETURN n LIMIT 10",
                query_type="cypher"
            )
            self.assertEqual(result["status"], "success")
            self.assertIn("results", result)
            
        self.async_test(run_test())

class ProvenanceToolsTest(BaseToolTester):
    """Tests for provenance tools."""
    
    def test_record_provenance(self):
        """Test record_provenance tool."""
        tool_func = self.get_tool_func("provenance_tools", "record_provenance")
        if not tool_func:
            self.skipTest("record_provenance tool not found")
        
        async def run_test():
            provenance_data = {
                "entity_id": "dataset_123",
                "entity_type": "dataset",
                "source_id": "source_456",
                "transformation": "filter_operation",
                "timestamp": "2025-05-24T16:00:00Z"
            }
            result = await tool_func(
                entity_id="dataset_123",
                entity_type="dataset",
                provenance_data=provenance_data
            )
            self.assertEqual(result["status"], "success")
            
        self.async_test(run_test())

def discover_and_test_missing_tools():
    """
    Discover any tools that don't have tests and create basic tests for them.
    """
    from pathlib import Path
    
    tools_path = Path("ipfs_datasets_py/mcp_server/tools")
    missing_tests = []
    
    # Get all existing test classes
    test_classes = {
        "dataset_tools": DatasetToolsTest,
        "ipfs_tools": IPFSToolsTest,
        "vector_tools": VectorToolsTest,
        "graph_tools": GraphToolsTest,
        "security_tools": SecurityToolsTest,
        "provenance_tools": ProvenanceToolsTest,
        "audit_tools": AuditToolsTest,
        "web_archive_tools": WebArchiveToolsTest,
        "cli": CLIToolsTest,
        "functions": FunctionToolsTest,
    }
    
    # Scan for tools not covered by tests
    for category_dir in tools_path.iterdir():
        if category_dir.is_dir() and not category_dir.name.startswith("_"):
            category = category_dir.name
            
            for tool_file in category_dir.glob("*.py"):
                if tool_file.name != "__init__.py":
                    tool_name = tool_file.stem
                    
                    # Check if we have a test for this tool
                    test_class = test_classes.get(category)
                    if test_class:
                        test_method_name = f"test_{tool_name}"
                        if not hasattr(test_class, test_method_name):
                            missing_tests.append((category, tool_name))
                    else:
                        missing_tests.append((category, tool_name))
    
    if missing_tests:
        logger.info(f"Found {len(missing_tests)} tools without tests:")
        for category, tool_name in missing_tests:
            logger.info(f"  {category}/{tool_name}")
    
    return missing_tests

def generate_missing_tests(missing_tools):
    """Generate basic test templates for missing tools."""
    test_templates = []
    
    for category, tool_name in missing_tools:
        template = f'''
    def test_{tool_name}(self):
        """Test {tool_name} tool."""
        tool_func = self.get_tool_func("{category}", "{tool_name}")
        if not tool_func:
            self.skipTest("{tool_name} tool not found")
        
        async def run_test():
            # TODO: Add proper test implementation for {tool_name}
            # Check function signature to determine parameters
            sig = inspect.signature(tool_func)
            params = list(sig.parameters.keys())
            
            # Basic test - call with minimal parameters
            if inspect.iscoroutinefunction(tool_func):
                result = await tool_func()  # Add required parameters
            else:
                result = tool_func()  # Add required parameters
            
            self.assertEqual(result["status"], "success")
            
        if inspect.iscoroutinefunction(tool_func):
            self.async_test(run_test())
        else:
            # For sync functions, call directly
            result = tool_func()  # Add required parameters
            self.assertEqual(result["status"], "success")
'''
        test_templates.append((category, tool_name, template))
    
    return test_templates

def run_comprehensive_tests():
    """Run all tests and generate reports."""
    logger.info("Starting comprehensive MCP tools testing...")
    
    # Discover missing tests
    missing_tools = discover_and_test_missing_tools()
    
    if missing_tools:
        logger.info("Generating test templates for missing tools...")
        templates = generate_missing_tests(missing_tools)
        
        # Write missing test templates to file
        with open("missing_tool_tests.py", "w") as f:
            f.write("# Generated test templates for missing tools\n\n")
            for category, tool_name, template in templates:
                f.write(f"# Test for {category}/{tool_name}:\n")
                f.write(template)
                f.write("\n")
    
    # Run existing tests
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    test_classes = [
        DatasetToolsTest,
        IPFSToolsTest,
        IPFSToolsExtendedTest,
        VectorToolsTest,
        GraphToolsTest,
        SecurityToolsTest,
        ProvenanceToolsTest,
        AuditToolsTest,
        WebArchiveToolsTest,
        CLIToolsTest,
        FunctionToolsTest,
    ]
    
    for test_class in test_classes:
        suite.addTest(loader.loadTestsFromTestCase(test_class))
    
    # Run the tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Generate test report
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped) if hasattr(result, 'skipped') else 0,
        "success_rate": (result.testsRun - len(result.failures) - len(result.errors)) / max(result.testsRun, 1) * 100,
        "missing_tools": missing_tools,
        "failure_details": [{"test": str(test), "error": error} for test, error in result.failures],
        "error_details": [{"test": str(test), "error": error} for test, error in result.errors]
    }
    
    with open("mcp_tools_test_report.json", "w") as f:
        json.dump(report, f, indent=2)
    
    logger.info(f"Test report written to mcp_tools_test_report.json")
    logger.info(f"Success rate: {report['success_rate']:.1f}%")
    
    return result

if __name__ == "__main__":
    run_comprehensive_tests()
