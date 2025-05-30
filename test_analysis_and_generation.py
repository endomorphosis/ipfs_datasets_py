#!/usr/bin/env python3
"""
Comprehensive MCP Tools Testing Summary and Missing Tests Generation

This script analyzes the test results and generates tests for missing tools.
"""
import json
from pathlib import Path

def analyze_test_results():
    """Analyze the test results and provide a comprehensive summary."""

    with open('mcp_tools_test_report.json', 'r') as f:
        results = json.load(f)

    print("=== COMPREHENSIVE MCP TOOLS TEST ANALYSIS ===")
    print(f"Timestamp: {results['timestamp']}")
    print(f"Total Tests Run: {results['tests_run']}")
    print(f"Success Rate: {results['success_rate']:.1f}%")
    print()

    print("=== TEST BREAKDOWN ===")
    print(f"✅ Passed: {results['tests_run'] - results['failures'] - results['errors']}")
    print(f"❌ Failed: {results['failures']}")
    print(f"💥 Errors: {results['errors']}")
    print(f"⏭️  Skipped: {results['skipped']}")
    print()

    # Analyze working tools
    working_tools = []
    problematic_tools = []

    # From the test output, we know:
    working_tools = [
        "dataset_tools/process_dataset",
        # Add other working tools based on test output
    ]

    print("=== WORKING TOOLS ===")
    print("✅ dataset_tools/process_dataset - Full functionality working")
    print()

    print("=== TOOLS NEEDING FIXES ===")

    # Tools with import errors (need missing dependencies)
    import_error_tools = [
        "ipfs_tools/pin_to_ipfs",
        "vector_tools/create_vector_index",
        "vector_tools/search_vector_index",
        "graph_tools/query_knowledge_graph",
        "security_tools/check_access_permission",
        "provenance_tools/record_provenance"
    ]

    print("🔗 Tools with Import Errors (Missing Dependencies):")
    for tool in import_error_tools:
        print(f"   - {tool}")
    print()

    # Tools with logic/implementation issues
    logic_error_tools = [
        "dataset_tools/load_dataset",
        "dataset_tools/save_dataset",
        "dataset_tools/convert_dataset_format",
        "audit_tools/record_audit_event",
        "audit_tools/generate_audit_report",
        "cli/execute_command",
        "functions/execute_python_snippet"
    ]

    print("⚙️  Tools with Logic/Implementation Issues:")
    for tool in logic_error_tools:
        print(f"   - {tool}")
    print()

    # Web archive tools (sync vs async issues)
    web_archive_tools = [
        "web_archive_tools/create_warc",
        "web_archive_tools/index_warc",
        "web_archive_tools/extract_dataset_from_cdxj",
        "web_archive_tools/extract_text_from_warc",
        "web_archive_tools/extract_links_from_warc",
        "web_archive_tools/extract_metadata_from_warc"
    ]

    print("🌐 Web Archive Tools (Async/Sync Issues):")
    for tool in web_archive_tools:
        print(f"   - {tool}")
    print()

    return results

def generate_test_for_get_from_ipfs():
    """Generate a proper test for the missing get_from_ipfs tool."""

    test_code = '''
# Test for ipfs_tools/get_from_ipfs
def test_get_from_ipfs(self):
    """Test get_from_ipfs tool."""
    tool_func = self.get_tool_func("ipfs_tools", "get_from_ipfs")
    if not tool_func:
        self.skipTest("get_from_ipfs tool not found")

    async def run_test():
        # Mock the IPFS client used in the actual implementation
        with patch('subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = b"File downloaded successfully"
            mock_result.stderr = b""
            mock_run.return_value = mock_result

            result = await tool_func("QmTest123", "/tmp/output_file")
            self.assertEqual(result["status"], "success")
            self.assertIn("output_path", result)

    self.async_test(run_test())
'''

    return test_code

def generate_fixes_for_failing_tools():
    """Generate suggested fixes for the failing tools."""

    fixes = {
        "dataset_tools/load_dataset": """
Fix: The test is failing because the mock dataset source doesn't exist.
Use a better mock or test with valid parameters:
- Mock the HuggingFace datasets.load_dataset function properly
- Provide realistic test data that won't cause errors
""",

        "dataset_tools/save_dataset": """
Fix: The DatasetManager class doesn't exist in dataset_serialization module.
Need to either:
- Check what the actual class name is in dataset_serialization.py
- Mock the correct class name
- Or mock the entire module if the implementation is different
""",

        "dataset_tools/convert_dataset_format": """
Fix: Function signature mismatch. The convert_dataset_format function
doesn't accept 'input_format' parameter.
- Check the actual function signature in the implementation
- Update test to match the actual parameters
""",

        "audit_tools/record_audit_event": """
Fix: The AuditLogger class doesn't have a 'log_event' method.
- Check the actual method name in the AuditLogger class
- Update the test to call the correct method
""",

        "audit_tools/generate_audit_report": """
Fix: The generate_audit_report function doesn't support 'summary' report type.
- Check what report types are actually supported
- Use a valid report type in the test
""",

        "cli/execute_command": """
Fix: The execute_command is working but doesn't actually execute commands for security.
- Update test expectations to match the security behavior
- Test for the 'message' field instead of 'output'
""",

        "web_archive_tools/*": """
Fix: These tools are returning dict instead of awaitable.
- Check if these functions are actually async
- If they're sync functions, don't use 'await'
- Update the test framework to handle both sync and async properly
"""
    }

    return fixes

def generate_missing_dependencies_script():
    """Generate a script to install missing dependencies for tools with import errors."""

    script = '''#!/bin/bash
# Script to install missing dependencies for MCP tools

echo "Installing missing dependencies for IPFS datasets MCP tools..."

# For vector tools (requires FAISS or similar)
pip install faiss-cpu numpy

# For IPFS tools
pip install ipfshttpclient

# For graph tools
pip install networkx rdflib

# For security tools
pip install cryptography pyjwt

# For web archive tools
pip install warcio beautifulsoup4 requests

# For additional dependencies
pip install aiofiles aiohttp

echo "Dependencies installation complete!"
'''

    return script

def main():
    """Main function to run the comprehensive analysis."""

    # Analyze test results
    results = analyze_test_results()

    # Generate missing test
    print("=== GENERATING MISSING TEST ===")
    get_from_ipfs_test = generate_test_for_get_from_ipfs()

    with open('missing_get_from_ipfs_test.py', 'w') as f:
        f.write(get_from_ipfs_test)
    print("✅ Generated test for get_from_ipfs -> missing_get_from_ipfs_test.py")

    # Generate fixes suggestions
    print("=== GENERATING FIX SUGGESTIONS ===")
    fixes = generate_fixes_for_failing_tools()

    with open('tool_fixes_suggestions.md', 'w') as f:
        f.write("# MCP Tools Fix Suggestions\\n\\n")
        for tool, fix in fixes.items():
            f.write(f"## {tool}\\n\\n{fix}\\n\\n")
    print("✅ Generated fix suggestions -> tool_fixes_suggestions.md")

    # Generate dependency installation script
    print("=== GENERATING DEPENDENCY SCRIPT ===")
    dep_script = generate_missing_dependencies_script()

    with open('install_missing_dependencies.sh', 'w') as f:
        f.write(dep_script)
    print("✅ Generated dependency script -> install_missing_dependencies.sh")

    print()
    print("=== NEXT STEPS ===")
    print("1. Run: chmod +x install_missing_dependencies.sh && ./install_missing_dependencies.sh")
    print("2. Fix the identified issues in the tool implementations")
    print("3. Re-run the test suite to verify fixes")
    print("4. Add the missing test for get_from_ipfs to the main test suite")

if __name__ == "__main__":
    main()
