#!/usr/bin/env python3
"""
Comprehensive MCP Tools Test Suite

This script provides proper tests for all MCP tools with appropriate parameters
and generates individual test files for tools that don't have dedicated tests.
"""

import os
import sys
import json
import asyncio
import traceback
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Tuple

# Add project root to path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

# Test data and configurations
TEST_DATA = {
    "small_dataset": {
        "data": [{"id": 1, "name": "test1"}, {"id": 2, "name": "test2"}],
        "format": "json"
    },
    "test_vectors": [
        [0.1, 0.2, 0.3, 0.4, 0.5],
        [0.2, 0.3, 0.4, 0.5, 0.6],
        [0.3, 0.4, 0.5, 0.6, 0.7]
    ],
    "test_graph_data": {
        "nodes": [{"id": "1", "name": "node1"}, {"id": "2", "name": "node2"}],
        "edges": [{"source": "1", "target": "2", "relation": "connects_to"}]
    }
}

class MCPToolsTester:
    def __init__(self):
        self.results = {}
        self.test_dir = tempfile.mkdtemp(prefix="mcp_test_")
        self.report = {
            "timestamp": datetime.now().isoformat(),
            "total_tools": 0,
            "passed": 0,
            "failed": 0,
            "tools": {}
        }

    def __del__(self):
        # Cleanup test directory
        if hasattr(self, 'test_dir') and os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_cli_tools(self):
        """Test CLI tools."""
        print("Testing CLI tools...")

        try:
            from ipfs_datasets_py.mcp_server.tools.cli.execute_command import execute_command

            # Test basic command execution
            result = await execute_command("echo 'Hello World'")
            assert result['status'] == 'success'
            assert 'Hello World' in result['output']

            # Test command with error
            result = await execute_command("nonexistent_command_12345")
            assert result['status'] == 'error'

            self.report["tools"]["cli.execute_command"] = {
                "status": "passed",
                "tests": ["basic_execution", "error_handling"]
            }

        except Exception as e:
            self.report["tools"]["cli.execute_command"] = {
                "status": "failed",
                "error": str(e)
            }

    async def test_security_tools(self):
        """Test security tools."""
        print("Testing security tools...")

        try:
            from ipfs_datasets_py.mcp_server.tools.security_tools.check_access_permission import check_access_permission

            # Test access permission check
            result = await check_access_permission("test_resource", "test_user")
            assert isinstance(result, dict)
            assert 'permitted' in result

            self.report["tools"]["security_tools.check_access_permission"] = {
                "status": "passed",
                "tests": ["permission_check"]
            }

        except Exception as e:
            self.report["tools"]["security_tools.check_access_permission"] = {
                "status": "failed",
                "error": str(e)
            }

    async def test_function_tools(self):
        """Test function execution tools."""
        print("Testing function tools...")

        try:
            from ipfs_datasets_py.mcp_server.tools.functions.execute_python_snippet import execute_python_snippet

            # Test simple Python execution
            result = await execute_python_snippet("print('test')")
            assert result['status'] == 'success'

            # Test Python with syntax error
            result = await execute_python_snippet("print('unclosed string")
            assert result['status'] == 'error'

            self.report["tools"]["functions.execute_python_snippet"] = {
                "status": "passed",
                "tests": ["basic_execution", "syntax_error_handling"]
            }

        except Exception as e:
            self.report["tools"]["functions.execute_python_snippet"] = {
                "status": "failed",
                "error": str(e)
            }

    async def test_ipfs_tools(self):
        """Test IPFS tools."""
        print("Testing IPFS tools...")

        # Test get_from_ipfs
        try:
            from ipfs_datasets_py.mcp_server.tools.ipfs_tools.get_from_ipfs import get_from_ipfs

            # Test with a known test CID (this will likely fail due to network, but should handle gracefully)
            result = await get_from_ipfs("QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG")
            assert isinstance(result, dict)
            assert 'status' in result

            self.report["tools"]["ipfs_tools.get_from_ipfs"] = {
                "status": "passed",
                "tests": ["basic_retrieval"]
            }

        except Exception as e:
            self.report["tools"]["ipfs_tools.get_from_ipfs"] = {
                "status": "failed",
                "error": str(e)
            }

        # Test pin_to_ipfs
        try:
            from ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs import pin_to_ipfs

            # Create a test file
            test_file = os.path.join(self.test_dir, "test_pin.txt")
            with open(test_file, 'w') as f:
                f.write("Test content for pinning")

            result = await pin_to_ipfs(test_file)
            assert isinstance(result, dict)
            assert 'status' in result

            self.report["tools"]["ipfs_tools.pin_to_ipfs"] = {
                "status": "passed",
                "tests": ["basic_pinning"]
            }

        except Exception as e:
            self.report["tools"]["ipfs_tools.pin_to_ipfs"] = {
                "status": "failed",
                "error": str(e)
            }

    async def test_graph_tools(self):
        """Test graph tools."""
        print("Testing graph tools...")

        try:
            from ipfs_datasets_py.mcp_server.tools.graph_tools.query_knowledge_graph import query_knowledge_graph

            # Test graph query
            result = await query_knowledge_graph("test_graph", "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5")
            assert isinstance(result, dict)
            assert 'status' in result

            self.report["tools"]["graph_tools.query_knowledge_graph"] = {
                "status": "passed",
                "tests": ["sparql_query"]
            }

        except Exception as e:
            self.report["tools"]["graph_tools.query_knowledge_graph"] = {
                "status": "failed",
                "error": str(e)
            }

    async def test_audit_tools(self):
        """Test audit tools."""
        print("Testing audit tools...")

        # Test record_audit_event
        try:
            from ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event import record_audit_event

            result = await record_audit_event("test_action", "test_user", {"resource": "test"})
            assert isinstance(result, dict)
            assert 'status' in result

            self.report["tools"]["audit_tools.record_audit_event"] = {
                "status": "passed",
                "tests": ["event_recording"]
            }

        except Exception as e:
            self.report["tools"]["audit_tools.record_audit_event"] = {
                "status": "failed",
                "error": str(e)
            }

        # Test generate_audit_report
        try:
            from ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report import generate_audit_report

            result = await generate_audit_report()
            assert isinstance(result, dict)
            assert 'status' in result

            self.report["tools"]["audit_tools.generate_audit_report"] = {
                "status": "passed",
                "tests": ["report_generation"]
            }

        except Exception as e:
            self.report["tools"]["audit_tools.generate_audit_report"] = {
                "status": "failed",
                "error": str(e)
            }

    async def test_vector_tools(self):
        """Test vector tools."""
        print("Testing vector tools...")

        # Test create_vector_index
        try:
            from ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index import create_vector_index

            result = await create_vector_index(TEST_DATA["test_vectors"], "test_index")
            assert isinstance(result, dict)
            assert 'status' in result

            self.report["tools"]["vector_tools.create_vector_index"] = {
                "status": "passed",
                "tests": ["index_creation"]
            }

        except Exception as e:
            self.report["tools"]["vector_tools.create_vector_index"] = {
                "status": "failed",
                "error": str(e)
            }

        # Test search_vector_index
        try:
            from ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index import search_vector_index

            result = await search_vector_index("test_index", [0.1, 0.2, 0.3, 0.4, 0.5])
            assert isinstance(result, dict)
            assert 'status' in result

            self.report["tools"]["vector_tools.search_vector_index"] = {
                "status": "passed",
                "tests": ["vector_search"]
            }

        except Exception as e:
            self.report["tools"]["vector_tools.search_vector_index"] = {
                "status": "failed",
                "error": str(e)
            }

    async def test_provenance_tools(self):
        """Test provenance tools."""
        print("Testing provenance tools...")

        try:
            from ipfs_datasets_py.mcp_server.tools.provenance_tools.record_provenance import record_provenance

            result = await record_provenance("test_dataset", "transformation",
                                           {"input": "data.csv", "output": "processed.json"})
            assert isinstance(result, dict)
            assert 'status' in result

            self.report["tools"]["provenance_tools.record_provenance"] = {
                "status": "passed",
                "tests": ["provenance_recording"]
            }

        except Exception as e:
            self.report["tools"]["provenance_tools.record_provenance"] = {
                "status": "failed",
                "error": str(e)
            }

    async def test_web_archive_tools(self):
        """Test web archive tools."""
        print("Testing web archive tools...")

        # Create test files
        test_warc = os.path.join(self.test_dir, "test.warc")
        test_cdxj = os.path.join(self.test_dir, "test.cdxj")

        # Create minimal test WARC content
        with open(test_warc, 'w') as f:
            f.write("WARC/1.0\r\nWARC-Type: response\r\nWARC-Record-ID: <urn:uuid:12345>\r\n\r\nTest content")

        # Create minimal test CDXJ content
        with open(test_cdxj, 'w') as f:
            f.write('{"url": "http://example.com", "timestamp": "20230101000000", "status": "200"}\n')

        # Test each web archive tool
        tools_to_test = [
            ("extract_dataset_from_cdxj", [test_cdxj]),
            ("create_warc", ["http://example.com"]),
            ("extract_links_from_warc", [test_warc]),
            ("index_warc", [test_warc]),
            ("extract_metadata_from_warc", [test_warc]),
            ("extract_text_from_warc", [test_warc])
        ]

        for tool_name, args in tools_to_test:
            try:
                module = __import__(f"ipfs_datasets_py.mcp_server.tools.web_archive_tools.{tool_name}",
                                  fromlist=[tool_name])
                func = getattr(module, tool_name)

                result = await func(*args)
                assert isinstance(result, dict)
                assert 'status' in result

                self.report["tools"][f"web_archive_tools.{tool_name}"] = {
                    "status": "passed",
                    "tests": ["basic_functionality"]
                }

            except Exception as e:
                self.report["tools"][f"web_archive_tools.{tool_name}"] = {
                    "status": "failed",
                    "error": str(e)
                }

    async def test_dataset_tools(self):
        """Test dataset tools."""
        print("Testing dataset tools...")

        # Test load_dataset
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset

            # Test with a small built-in dataset (might fail, but should handle gracefully)
            result = await load_dataset("squad", format="json")
            assert isinstance(result, dict)
            assert 'status' in result

            self.report["tools"]["dataset_tools.load_dataset"] = {
                "status": "passed",
                "tests": ["dataset_loading"]
            }

        except Exception as e:
            self.report["tools"]["dataset_tools.load_dataset"] = {
                "status": "failed",
                "error": str(e)
            }

        # Test save_dataset
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset

            result = await save_dataset("test_dataset", TEST_DATA["small_dataset"]["data"],
                                      os.path.join(self.test_dir, "output.json"))
            assert isinstance(result, dict)
            assert 'status' in result

            self.report["tools"]["dataset_tools.save_dataset"] = {
                "status": "passed",
                "tests": ["dataset_saving"]
            }

        except Exception as e:
            self.report["tools"]["dataset_tools.save_dataset"] = {
                "status": "failed",
                "error": str(e)
            }

        # Test convert_dataset_format
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.convert_dataset_format import convert_dataset_format

            result = await convert_dataset_format("test_dataset", "csv",
                                                 input_data=TEST_DATA["small_dataset"]["data"])
            assert isinstance(result, dict)
            assert 'status' in result

            self.report["tools"]["dataset_tools.convert_dataset_format"] = {
                "status": "passed",
                "tests": ["format_conversion"]
            }

        except Exception as e:
            self.report["tools"]["dataset_tools.convert_dataset_format"] = {
                "status": "failed",
                "error": str(e)
            }

        # Test process_dataset
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import process_dataset

            result = await process_dataset(TEST_DATA["small_dataset"]["data"], ["normalize"])
            assert isinstance(result, dict)
            assert 'status' in result

            self.report["tools"]["dataset_tools.process_dataset"] = {
                "status": "passed",
                "tests": ["dataset_processing"]
            }

        except Exception as e:
            self.report["tools"]["dataset_tools.process_dataset"] = {
                "status": "failed",
                "error": str(e)
            }

    async def run_all_tests(self):
        """Run all test categories."""
        print("="*60)
        print("COMPREHENSIVE MCP TOOLS TEST SUITE")
        print("="*60)

        test_categories = [
            self.test_cli_tools,
            self.test_security_tools,
            self.test_function_tools,
            self.test_ipfs_tools,
            self.test_graph_tools,
            self.test_audit_tools,
            self.test_vector_tools,
            self.test_provenance_tools,
            self.test_web_archive_tools,
            self.test_dataset_tools
        ]

        for test_func in test_categories:
            try:
                await test_func()
            except Exception as e:
                print(f"Error in {test_func.__name__}: {e}")
                traceback.print_exc()

        # Calculate final statistics
        self.report["total_tools"] = len(self.report["tools"])
        self.report["passed"] = sum(1 for tool in self.report["tools"].values()
                                  if tool["status"] == "passed")
        self.report["failed"] = self.report["total_tools"] - self.report["passed"]

        return self.report

    def generate_test_files(self):
        """Generate individual test files for tools that don't have dedicated tests."""
        print("\nGenerating individual test files...")

        test_templates = {
            "cli": self._generate_cli_test_template,
            "security_tools": self._generate_security_test_template,
            "functions": self._generate_functions_test_template,
            "ipfs_tools": self._generate_ipfs_test_template,
            "graph_tools": self._generate_graph_test_template,
            "audit_tools": self._generate_audit_test_template,
            "vector_tools": self._generate_vector_test_template,
            "provenance_tools": self._generate_provenance_test_template,
            "web_archive_tools": self._generate_web_archive_test_template,
            "dataset_tools": self._generate_dataset_test_template
        }

        tests_dir = project_root / "tests"
        tests_dir.mkdir(exist_ok=True)

        for category, template_func in test_templates.items():
            test_file = tests_dir / f"test_{category}.py"
            if not test_file.exists():
                test_content = template_func()
                test_file.write_text(test_content)
                print(f"Generated: {test_file}")

    def _generate_cli_test_template(self):
        return '''#!/usr/bin/env python3
"""
Test suite for CLI tools
"""

import pytest
import asyncio
from ipfs_datasets_py.mcp_server.tools.cli.execute_command import execute_command


class TestCLITools:

    @pytest.mark.asyncio
    async def test_execute_command_success(self):
        """Test successful command execution."""
        result = await execute_command("echo 'test'")
        assert result['status'] == 'success'
        assert 'test' in result['output']

    @pytest.mark.asyncio
    async def test_execute_command_failure(self):
        """Test command execution failure."""
        result = await execute_command("nonexistent_command_12345")
        assert result['status'] == 'error'
        assert 'error' in result

    @pytest.mark.asyncio
    async def test_execute_command_with_args(self):
        """Test command execution with arguments."""
        result = await execute_command("ls -la /tmp")
        assert result['status'] == 'success'
'''

    def _generate_security_test_template(self):
        return '''#!/usr/bin/env python3
"""
Test suite for security tools
"""

import pytest
import asyncio
from ipfs_datasets_py.mcp_server.tools.security_tools.check_access_permission import check_access_permission


class TestSecurityTools:

    @pytest.mark.asyncio
    async def test_check_access_permission(self):
        """Test access permission checking."""
        result = await check_access_permission("test_resource", "test_user")
        assert isinstance(result, dict)
        assert 'permitted' in result

    @pytest.mark.asyncio
    async def test_check_access_permission_invalid_resource(self):
        """Test access permission with invalid resource."""
        result = await check_access_permission("", "test_user")
        assert isinstance(result, dict)
'''

    def _generate_functions_test_template(self):
        return '''#!/usr/bin/env python3
"""
Test suite for function execution tools
"""

import pytest
import asyncio
from ipfs_datasets_py.mcp_server.tools.functions.execute_python_snippet import execute_python_snippet


class TestFunctionTools:

    @pytest.mark.asyncio
    async def test_execute_python_snippet_success(self):
        """Test successful Python snippet execution."""
        result = await execute_python_snippet("print('hello world')")
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    async def test_execute_python_snippet_syntax_error(self):
        """Test Python snippet with syntax error."""
        result = await execute_python_snippet("print('unclosed string")
        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_execute_python_snippet_calculation(self):
        """Test Python snippet with calculation."""
        result = await execute_python_snippet("result = 2 + 2\\nprint(result)")
        assert result['status'] == 'success'
'''

    def _generate_ipfs_test_template(self):
        return '''#!/usr/bin/env python3
"""
Test suite for IPFS tools
"""

import pytest
import asyncio
import tempfile
import os
from ipfs_datasets_py.mcp_server.tools.ipfs_tools.get_from_ipfs import get_from_ipfs
from ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs import pin_to_ipfs


class TestIPFSTools:

    @pytest.mark.asyncio
    async def test_get_from_ipfs(self):
        """Test getting content from IPFS."""
        # Use a known test CID
        result = await get_from_ipfs("QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG")
        assert isinstance(result, dict)
        assert 'status' in result

    @pytest.mark.asyncio
    async def test_pin_to_ipfs(self):
        """Test pinning content to IPFS."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("Test content for pinning")
            temp_path = f.name

        try:
            result = await pin_to_ipfs(temp_path)
            assert isinstance(result, dict)
            assert 'status' in result
        finally:
            os.unlink(temp_path)
'''

    def _generate_graph_test_template(self):
        return '''#!/usr/bin/env python3
"""
Test suite for graph tools
"""

import pytest
import asyncio
from ipfs_datasets_py.mcp_server.tools.graph_tools.query_knowledge_graph import query_knowledge_graph


class TestGraphTools:

    @pytest.mark.asyncio
    async def test_query_knowledge_graph(self):
        """Test knowledge graph querying."""
        result = await query_knowledge_graph("test_graph", "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5")
        assert isinstance(result, dict)
        assert 'status' in result

    @pytest.mark.asyncio
    async def test_query_knowledge_graph_invalid_query(self):
        """Test knowledge graph with invalid query."""
        result = await query_knowledge_graph("test_graph", "INVALID SPARQL")
        assert isinstance(result, dict)
'''

    def _generate_audit_test_template(self):
        return '''#!/usr/bin/env python3
"""
Test suite for audit tools
"""

import pytest
import asyncio
from ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event import record_audit_event
from ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report import generate_audit_report


class TestAuditTools:

    @pytest.mark.asyncio
    async def test_record_audit_event(self):
        """Test audit event recording."""
        result = await record_audit_event("test_action", "test_user", {"resource": "test"})
        assert isinstance(result, dict)
        assert 'status' in result

    @pytest.mark.asyncio
    async def test_generate_audit_report(self):
        """Test audit report generation."""
        result = await generate_audit_report()
        assert isinstance(result, dict)
        assert 'status' in result
'''

    def _generate_vector_test_template(self):
        return '''#!/usr/bin/env python3
"""
Test suite for vector tools
"""

import pytest
import asyncio
from ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index import create_vector_index
from ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index import search_vector_index


class TestVectorTools:

    @pytest.mark.asyncio
    async def test_create_vector_index(self):
        """Test vector index creation."""
        vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        result = await create_vector_index(vectors, "test_index")
        assert isinstance(result, dict)
        assert 'status' in result

    @pytest.mark.asyncio
    async def test_search_vector_index(self):
        """Test vector index searching."""
        result = await search_vector_index("test_index", [0.1, 0.2, 0.3])
        assert isinstance(result, dict)
        assert 'status' in result
'''

    def _generate_provenance_test_template(self):
        return '''#!/usr/bin/env python3
"""
Test suite for provenance tools
"""

import pytest
import asyncio
from ipfs_datasets_py.mcp_server.tools.provenance_tools.record_provenance import record_provenance


class TestProvenanceTools:

    @pytest.mark.asyncio
    async def test_record_provenance(self):
        """Test provenance recording."""
        result = await record_provenance("test_dataset", "transformation",
                                       {"input": "data.csv", "output": "processed.json"})
        assert isinstance(result, dict)
        assert 'status' in result
'''

    def _generate_web_archive_test_template(self):
        return '''#!/usr/bin/env python3
"""
Test suite for web archive tools
"""

import pytest
import asyncio
import tempfile
import os
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_dataset_from_cdxj import extract_dataset_from_cdxj
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.create_warc import create_warc
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_links_from_warc import extract_links_from_warc
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.index_warc import index_warc
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_metadata_from_warc import extract_metadata_from_warc
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_text_from_warc import extract_text_from_warc


class TestWebArchiveTools:

    def setup_method(self):
        """Setup test files."""
        self.test_dir = tempfile.mkdtemp()

        # Create test WARC file
        self.test_warc = os.path.join(self.test_dir, "test.warc")
        with open(self.test_warc, 'w') as f:
            f.write("WARC/1.0\\r\\nWARC-Type: response\\r\\nWARC-Record-ID: <urn:uuid:12345>\\r\\n\\r\\nTest content")

        # Create test CDXJ file
        self.test_cdxj = os.path.join(self.test_dir, "test.cdxj")
        with open(self.test_cdxj, 'w') as f:
            f.write('{"url": "http://example.com", "timestamp": "20230101000000", "status": "200"}\\n')

    @pytest.mark.asyncio
    async def test_extract_dataset_from_cdxj(self):
        """Test CDXJ dataset extraction."""
        result = await extract_dataset_from_cdxj(self.test_cdxj)
        assert isinstance(result, dict)
        assert 'status' in result

    @pytest.mark.asyncio
    async def test_create_warc(self):
        """Test WARC creation."""
        result = await create_warc("http://example.com")
        assert isinstance(result, dict)
        assert 'status' in result

    @pytest.mark.asyncio
    async def test_extract_links_from_warc(self):
        """Test link extraction from WARC."""
        result = await extract_links_from_warc(self.test_warc)
        assert isinstance(result, dict)
        assert 'status' in result
'''

    def _generate_dataset_test_template(self):
        return '''#!/usr/bin/env python3
"""
Test suite for dataset tools
"""

import pytest
import asyncio
import tempfile
import os
from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset
from ipfs_datasets_py.mcp_server.tools.dataset_tools.convert_dataset_format import convert_dataset_format
from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import process_dataset


class TestDatasetTools:

    def setup_method(self):
        """Setup test data."""
        self.test_data = [{"id": 1, "name": "test1"}, {"id": 2, "name": "test2"}]
        self.test_dir = tempfile.mkdtemp()

    @pytest.mark.asyncio
    async def test_load_dataset(self):
        """Test dataset loading."""
        # This might fail due to network issues, but should handle gracefully
        result = await load_dataset("squad", format="json")
        assert isinstance(result, dict)
        assert 'status' in result

    @pytest.mark.asyncio
    async def test_save_dataset(self):
        """Test dataset saving."""
        output_path = os.path.join(self.test_dir, "output.json")
        result = await save_dataset("test_dataset", self.test_data, output_path)
        assert isinstance(result, dict)
        assert 'status' in result

    @pytest.mark.asyncio
    async def test_convert_dataset_format(self):
        """Test dataset format conversion."""
        result = await convert_dataset_format("test_dataset", "csv", input_data=self.test_data)
        assert isinstance(result, dict)
        assert 'status' in result

    @pytest.mark.asyncio
    async def test_process_dataset(self):
        """Test dataset processing."""
        result = await process_dataset(self.test_data, ["normalize"])
        assert isinstance(result, dict)
        assert 'status' in result
'''

    def save_report(self, filename="comprehensive_test_report.json"):
        """Save the test report to a file."""
        with open(filename, 'w') as f:
            json.dump(self.report, f, indent=2)
        print(f"Test report saved to: {filename}")

async def main():
    """Main execution function."""
    tester = MCPToolsTester()

    # Run comprehensive tests
    report = await tester.run_all_tests()

    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"Total tools tested: {report['total_tools']}")
    print(f"Passed: {report['passed']}")
    print(f"Failed: {report['failed']}")
    print(f"Success rate: {report['passed']/report['total_tools']*100:.1f}%" if report['total_tools'] > 0 else "0%")

    # Show failed tools
    failed_tools = [name for name, data in report['tools'].items() if data['status'] == 'failed']
    if failed_tools:
        print(f"\nFailed tools ({len(failed_tools)}):")
        for tool in failed_tools:
            error = report['tools'][tool].get('error', 'Unknown error')
            print(f"  - {tool}: {error}")

    # Save report
    tester.save_report()

    # Generate test files
    tester.generate_test_files()

    print(f"\nTest completed. Report saved and individual test files generated.")

if __name__ == "__main__":
    asyncio.run(main())
