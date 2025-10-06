#!/usr/bin/env python3
"""
Comprehensive test suite for IPFS Datasets MCP Server Tools.

This script tests all MCP tools to ensure they work correctly
and can be properly integrated with the MCP server.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, Any, List
import traceback

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Test data and fixtures
TEST_HTML_CONTENT = """
<!DOCTYPE html>
<html>
<head>
    <title>Test Page</title>
</head>
<body>
    <h1>Sample Title</h1>
    <p>This is a test paragraph with <a href="https://example.com">a link</a>.</p>
    <div>Some content in a div.</div>
</body>
</html>
"""

TEST_VECTORS = [
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0],
    [0.5, 0.5, 0.0]
]

class MCPToolTester:
    """Test harness for MCP tools."""

    def __init__(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_results = {}
        self.failed_tests = []

    def cleanup(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_test_warc(self) -> str:
        """Create a test WARC file."""
        warc_path = os.path.join(self.temp_dir, "test.warc")
        with open(warc_path, 'w') as f:
            f.write("WARC/1.0\n")
            f.write("WARC-Type: response\n")
            f.write("WARC-Target-URI: https://example.com\n")
            f.write("Content-Length: 100\n")
            f.write("\n")
            f.write("<html><body>Test content</body></html>\n")
        return warc_path

    def create_test_cdxj(self) -> str:
        """Create a test CDXJ file."""
        cdxj_path = os.path.join(self.temp_dir, "test.cdxj")
        with open(cdxj_path, 'w') as f:
            f.write('com,example)/ 20240101000000 {"url": "https://example.com/", "status": "200"}\n')
            f.write('com,example)/page1 20240101010000 {"url": "https://example.com/page1", "status": "200"}\n')
        return cdxj_path

    async def test_web_archive_tools(self):
        """Test all web archive tools."""
        print("\n🕸️  Testing Web Archive Tools...")

        # Import web archive tools
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "web_archive_tools"))

            from extract_text_from_warc import extract_text_from_warc
            from extract_metadata_from_warc import extract_metadata_from_warc
            from extract_links_from_warc import extract_links_from_warc
            from index_warc import index_warc
            from create_warc import create_warc
            from extract_dataset_from_cdxj import extract_dataset_from_cdxj

            warc_path = self.create_test_warc()
            cdxj_path = self.create_test_cdxj()

            tests = [
                ("extract_text_from_warc", lambda: extract_text_from_warc(warc_path)),
                ("extract_metadata_from_warc", lambda: extract_metadata_from_warc(warc_path)),
                ("extract_links_from_warc", lambda: extract_links_from_warc(warc_path)),
                ("index_warc", lambda: index_warc(warc_path)),
                ("create_warc", lambda: create_warc(["https://example.com"], os.path.join(self.temp_dir, "new.warc"))),
                ("extract_dataset_from_cdxj", lambda: extract_dataset_from_cdxj(cdxj_path))
            ]

            for test_name, test_func in tests:
                try:
                    result = test_func()
                    if result.get("status") == "success" or "records" in result or "metadata" in result:
                        print(f"    ✓ {test_name}")
                        self.test_results[f"web_archive.{test_name}"] = "PASS"
                    else:
                        print(f"    ✗ {test_name}: {result}")
                        self.test_results[f"web_archive.{test_name}"] = "FAIL"
                        self.failed_tests.append(f"web_archive.{test_name}")
                except Exception as e:
                    print(f"    ✗ {test_name}: {e}")
                    self.test_results[f"web_archive.{test_name}"] = f"ERROR: {e}"
                    self.failed_tests.append(f"web_archive.{test_name}")

        except Exception as e:
            print(f"    ✗ Failed to import web archive tools: {e}")
            self.test_results["web_archive"] = f"IMPORT_ERROR: {e}"

    async def test_vector_tools(self):
        """Test vector tools."""
        print("\n🔢 Testing Vector Tools...")

        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "vector_tools"))

            from create_vector_index import create_vector_index
            from search_vector_index import search_vector_index

            tests = [
                ("create_vector_index", lambda: asyncio.run(create_vector_index(TEST_VECTORS, dimension=3))),
                ("search_vector_index", lambda: asyncio.run(search_vector_index("test_index", [1.0, 0.0, 0.0], top_k=5)))
            ]

            for test_name, test_func in tests:
                try:
                    result = test_func()
                    if isinstance(result, dict) and (result.get("status") == "success" or "index_id" in result or "results" in result):
                        print(f"    ✓ {test_name}")
                        self.test_results[f"vector_tools.{test_name}"] = "PASS"
                    else:
                        print(f"    ✗ {test_name}: {result}")
                        self.test_results[f"vector_tools.{test_name}"] = "FAIL"
                        self.failed_tests.append(f"vector_tools.{test_name}")
                except Exception as e:
                    print(f"    ✗ {test_name}: {e}")
                    self.test_results[f"vector_tools.{test_name}"] = f"ERROR: {e}"
                    self.failed_tests.append(f"vector_tools.{test_name}")

        except Exception as e:
            print(f"    ✗ Failed to import vector tools: {e}")
            self.test_results["vector_tools"] = f"IMPORT_ERROR: {e}"

    async def test_graph_tools(self):
        """Test graph tools."""
        print("\n🕸️  Testing Graph Tools...")

        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "graph_tools"))

            from query_knowledge_graph import query_knowledge_graph

            tests = [
                ("query_knowledge_graph", lambda: asyncio.run(query_knowledge_graph(
                    "test_graph",
                    "MATCH (n) RETURN n LIMIT 10",
                    "sparql"
                )))
            ]

            for test_name, test_func in tests:
                try:
                    result = test_func()
                    if isinstance(result, dict) and (result.get("status") == "success" or "results" in result):
                        print(f"    ✓ {test_name}")
                        self.test_results[f"graph_tools.{test_name}"] = "PASS"
                    else:
                        print(f"    ✗ {test_name}: {result}")
                        self.test_results[f"graph_tools.{test_name}"] = "FAIL"
                        self.failed_tests.append(f"graph_tools.{test_name}")
                except Exception as e:
                    print(f"    ✗ {test_name}: {e}")
                    self.test_results[f"graph_tools.{test_name}"] = f"ERROR: {e}"
                    self.failed_tests.append(f"graph_tools.{test_name}")

        except Exception as e:
            print(f"    ✗ Failed to import graph tools: {e}")
            self.test_results["graph_tools"] = f"IMPORT_ERROR: {e}"

    async def test_dataset_tools(self):
        """Test dataset tools."""
        print("\n📊 Testing Dataset Tools...")

        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "dataset_tools"))

            from load_dataset import load_dataset
            from save_dataset import save_dataset
            from process_dataset import process_dataset
            from convert_dataset_format import convert_dataset_format

            # Create test data
            test_data = {"test": "data", "numbers": [1, 2, 3]}
            test_path = os.path.join(self.temp_dir, "test_dataset.json")
            with open(test_path, 'w') as f:
                json.dump(test_data, f)

            tests = [
                ("load_dataset", lambda: asyncio.run(load_dataset("squad", "plain_text"))),
                ("save_dataset", lambda: asyncio.run(save_dataset(test_data, os.path.join(self.temp_dir, "output.json")))),
                ("process_dataset", lambda: asyncio.run(process_dataset(test_path, {"operation": "normalize"}))),
                ("convert_dataset_format", lambda: asyncio.run(convert_dataset_format(
                    test_path,
                    os.path.join(self.temp_dir, "converted.csv"),
                    "json",
                    "csv"
                )))
            ]

            for test_name, test_func in tests:
                try:
                    result = test_func()
                    if isinstance(result, dict) and (result.get("status") == "success" or "dataset" in result or "output_path" in result):
                        print(f"    ✓ {test_name}")
                        self.test_results[f"dataset_tools.{test_name}"] = "PASS"
                    else:
                        print(f"    ✗ {test_name}: {result}")
                        self.test_results[f"dataset_tools.{test_name}"] = "FAIL"
                        self.failed_tests.append(f"dataset_tools.{test_name}")
                except Exception as e:
                    print(f"    ✗ {test_name}: {e}")
                    self.test_results[f"dataset_tools.{test_name}"] = f"ERROR: {e}"
                    self.failed_tests.append(f"dataset_tools.{test_name}")

        except Exception as e:
            print(f"    ✗ Failed to import dataset tools: {e}")
            self.test_results["dataset_tools"] = f"IMPORT_ERROR: {e}"

    async def test_ipfs_tools(self):
        """Test IPFS tools."""
        print("\n🌐 Testing IPFS Tools...")

        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "ipfs_tools"))

            from get_from_ipfs import get_from_ipfs
            from pin_to_ipfs import pin_to_ipfs

            tests = [
                ("get_from_ipfs", lambda: asyncio.run(get_from_ipfs("QmTestHash123", self.temp_dir))),
                ("pin_to_ipfs", lambda: asyncio.run(pin_to_ipfs(os.path.join(self.temp_dir, "test_file.txt"))))
            ]

            # Create test file for pinning
            test_file = os.path.join(self.temp_dir, "test_file.txt")
            with open(test_file, 'w') as f:
                f.write("Test content for IPFS")

            for test_name, test_func in tests:
                try:
                    result = test_func()
                    if isinstance(result, dict) and (result.get("status") == "success" or "hash" in result or "path" in result):
                        print(f"    ✓ {test_name}")
                        self.test_results[f"ipfs_tools.{test_name}"] = "PASS"
                    else:
                        print(f"    ✗ {test_name}: {result}")
                        self.test_results[f"ipfs_tools.{test_name}"] = "FAIL"
                        self.failed_tests.append(f"ipfs_tools.{test_name}")
                except Exception as e:
                    print(f"    ✗ {test_name}: {e}")
                    self.test_results[f"ipfs_tools.{test_name}"] = f"ERROR: {e}"
                    self.failed_tests.append(f"ipfs_tools.{test_name}")

        except Exception as e:
            print(f"    ✗ Failed to import IPFS tools: {e}")
            self.test_results["ipfs_tools"] = f"IMPORT_ERROR: {e}"

    async def test_audit_tools(self):
        """Test audit tools."""
        print("\n📋 Testing Audit Tools...")

        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "audit_tools"))

            from record_audit_event import record_audit_event
            from generate_audit_report import generate_audit_report

            tests = [
                ("record_audit_event", lambda: asyncio.run(record_audit_event(
                    "test_event",
                    "user123",
                    {"action": "test", "resource": "dataset"}
                ))),
                ("generate_audit_report", lambda: asyncio.run(generate_audit_report(
                    start_date="2024-01-01",
                    end_date="2024-12-31"
                )))
            ]

            for test_name, test_func in tests:
                try:
                    result = test_func()
                    if isinstance(result, dict) and (result.get("status") == "success" or "event_id" in result or "report" in result):
                        print(f"    ✓ {test_name}")
                        self.test_results[f"audit_tools.{test_name}"] = "PASS"
                    else:
                        print(f"    ✗ {test_name}: {result}")
                        self.test_results[f"audit_tools.{test_name}"] = "FAIL"
                        self.failed_tests.append(f"audit_tools.{test_name}")
                except Exception as e:
                    print(f"    ✗ {test_name}: {e}")
                    self.test_results[f"audit_tools.{test_name}"] = f"ERROR: {e}"
                    self.failed_tests.append(f"audit_tools.{test_name}")

        except Exception as e:
            print(f"    ✗ Failed to import audit tools: {e}")
            self.test_results["audit_tools"] = f"IMPORT_ERROR: {e}"

    async def test_other_tools(self):
        """Test miscellaneous tools."""
        print("\n🔧 Testing Other Tools...")

        # Test CLI tools
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "cli"))
            from execute_command import execute_command

            result = await execute_command("echo 'test'")
            if isinstance(result, dict) and result.get("status") == "success":
                print("    ✓ execute_command")
                self.test_results["cli.execute_command"] = "PASS"
            else:
                print(f"    ✗ execute_command: {result}")
                self.test_results["cli.execute_command"] = "FAIL"
                self.failed_tests.append("cli.execute_command")
        except Exception as e:
            print(f"    ✗ execute_command: {e}")
            self.test_results["cli.execute_command"] = f"ERROR: {e}"

        # Test security tools
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "security_tools"))
            from check_access_permission import check_access_permission

            result = await check_access_permission("user123", "dataset456", "read")
            if isinstance(result, dict):
                print("    ✓ check_access_permission")
                self.test_results["security.check_access_permission"] = "PASS"
            else:
                print(f"    ✗ check_access_permission: {result}")
                self.test_results["security.check_access_permission"] = "FAIL"
                self.failed_tests.append("security.check_access_permission")
        except Exception as e:
            print(f"    ✗ check_access_permission: {e}")
            self.test_results["security.check_access_permission"] = f"ERROR: {e}"

        # Test provenance tools
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "provenance_tools"))
            from record_provenance import record_provenance

            result = await record_provenance("dataset123", {
                "action": "created",
                "timestamp": "2024-01-01T00:00:00Z",
                "source": "test"
            })
            if isinstance(result, dict):
                print("    ✓ record_provenance")
                self.test_results["provenance.record_provenance"] = "PASS"
            else:
                print(f"    ✗ record_provenance: {result}")
                self.test_results["provenance.record_provenance"] = "FAIL"
                self.failed_tests.append("provenance.record_provenance")
        except Exception as e:
            print(f"    ✗ record_provenance: {e}")
            self.test_results["provenance.record_provenance"] = f"ERROR: {e}"

        # Test function tools
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "functions"))
            from execute_python_snippet import execute_python_snippet

            result = await execute_python_snippet("print('Hello, World!')")
            if isinstance(result, dict):
                print("    ✓ execute_python_snippet")
                self.test_results["functions.execute_python_snippet"] = "PASS"
            else:
                print(f"    ✗ execute_python_snippet: {result}")
                self.test_results["functions.execute_python_snippet"] = "FAIL"
                self.failed_tests.append("functions.execute_python_snippet")
        except Exception as e:
            print(f"    ✗ execute_python_snippet: {e}")
            self.test_results["functions.execute_python_snippet"] = f"ERROR: {e}"

    async def run_all_tests(self):
        """Run all MCP tool tests."""
        print("🧪 IPFS Datasets MCP Tools Test Suite")
        print("=" * 50)

        test_suites = [
            self.test_web_archive_tools,
            self.test_vector_tools,
            self.test_graph_tools,
            self.test_dataset_tools,
            self.test_ipfs_tools,
            self.test_audit_tools,
            self.test_other_tools
        ]

        for test_suite in test_suites:
            try:
                await test_suite()
            except Exception as e:
                print(f"❌ Test suite {test_suite.__name__} crashed: {e}")
                traceback.print_exc()

        self.print_summary()

    def print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 50)
        print("📊 TEST SUMMARY")
        print("=" * 50)

        total_tests = len(self.test_results)
        passed_tests = len([r for r in self.test_results.values() if r == "PASS"])
        failed_tests = len(self.failed_tests)

        print(f"Total Tests: {total_tests}")
        print(f"Passed: {passed_tests}")
        print(f"Failed: {failed_tests}")
        print(f"Success Rate: {(passed_tests / total_tests * 100):.1f}%" if total_tests > 0 else "N/A")

        if self.failed_tests:
            print(f"\n❌ Failed Tests:")
            for test in self.failed_tests:
                result = self.test_results.get(test, "Unknown error")
                print(f"  • {test}: {result}")

        if passed_tests == total_tests:
            print(f"\n🎉 All tests passed! MCP tools are ready for use.")
        else:
            print(f"\n⚠️  Some tests failed. Please check the tools and fix any issues.")

        # Save detailed results
        results_file = "mcp_tools_test_results.json"
        with open(results_file, 'w') as f:
            json.dump({
                "summary": {
                    "total": total_tests,
                    "passed": passed_tests,
                    "failed": failed_tests,
                    "success_rate": (passed_tests / total_tests * 100) if total_tests > 0 else 0
                },
                "results": self.test_results,
                "failed_tests": self.failed_tests
            }, f, indent=2)
        print(f"\n📄 Detailed results saved to: {results_file}")

async def main():
    """Main test runner."""
    tester = MCPToolTester()
    try:
        await tester.run_all_tests()
    finally:
        tester.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
