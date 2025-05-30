#!/usr/bin/env python3
"""
MCP Tools Test Generator

This script discovers all available MCP tools in the ipfs_datasets_py package,
identifies which ones have tests, and generates tests for those that don't.
"""

import os
import sys
import importlib
import inspect
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Set, Tuple

sys.path.insert(0, '.')

class MCPToolsTestGenerator:
    def __init__(self):
        self.tools_base_path = Path("ipfs_datasets_py/mcp_server/tools")
        self.test_path = Path("test")
        self.discovered_tools = {}
        self.tested_tools = set()
        self.untested_tools = set()
        self.tested_count = 0
        self.untested_count = 0
        self.total_count = 0

        self.tool_categories = [
            "audit_tools", "dataset_tools", "web_archive_tools",
            "cli", "functions", "security_tools", "vector_tools",
            "graph_tools", "provenance_tools", "ipfs_tools"
        ]

    def discover_all_tools(self) -> Dict[str, List[str]]:
        """Discover all MCP tools in the codebase."""
        print("=== Discovering MCP Tools ===")

        for category in self.tool_categories:
            category_path = self.tools_base_path / category
            if not category_path.exists():
                print(f"Category {category} not found")
                continue

            # Look for Python files in the category directory
            tools = []
            for file_path in category_path.glob("*.py"):
                if file_path.name != "__init__.py":
                    tool_name = file_path.stem
                    tools.append(tool_name)

            self.discovered_tools[category] = tools
            print(f"✓ {category}: {len(tools)} tools found")

        total_tools = sum(len(tools) for tools in self.discovered_tools.values())
        print(f"\nTotal discovered tools: {total_tools}")
        return self.discovered_tools

    def find_existing_tests(self) -> Set[str]:
        """Find existing MCP tool tests."""
        print("\n=== Finding Existing Tests ===")

        test_files = list(self.test_path.glob("test_mcp_*.py"))
        for test_file in test_files:
            # Extract tool name from test file name (test_mcp_<tool_name>.py)
            tool_name = test_file.stem.replace("test_mcp_", "")
            self.tested_tools.add(tool_name)

        print(f"Found {len(self.tested_tools)} existing tool tests")
        return self.tested_tools

    def identify_untested_tools(self) -> Set[Tuple[str, str]]:
        """Identify tools that don't have tests."""
        print("\n=== Identifying Untested Tools ===")

        for category, tools in self.discovered_tools.items():
            for tool in tools:
                if tool not in self.tested_tools:
                    self.untested_tools.add((category, tool))

        print(f"Found {len(self.untested_tools)} untested tools")
        for category, tool in sorted(self.untested_tools):
            print(f"- {category}.{tool}")

        return self.untested_tools

    def get_tool_signature(self, category: str, tool: str) -> Dict:
        """Get the signature of a tool function."""
        try:
            # Import the specific tool module
            module_name = f"ipfs_datasets_py.mcp_server.tools.{category}.{tool}"

            try:
                # Try direct import first
                module = importlib.import_module(module_name)

                # Assume the function has the same name as the module
                func = getattr(module, tool)
            except (ImportError, AttributeError):
                # If that fails, try importing from the category
                module_name = f"ipfs_datasets_py.mcp_server.tools.{category}"
                module = importlib.import_module(module_name)
                func = getattr(module, tool)

            # Get parameter info
            sig = inspect.signature(func)
            params = {}
            for name, param in sig.parameters.items():
                params[name] = {
                    "annotation": str(param.annotation) if param.annotation != inspect.Parameter.empty else "Any",
                    "default": None if param.default == inspect.Parameter.empty else repr(param.default),
                    "required": param.default == inspect.Parameter.empty,
                }

            return {
                "is_async": asyncio.iscoroutinefunction(func),
                "parameters": params,
                "docstring": inspect.getdoc(func) or "",
            }
        except Exception as e:
            print(f"Error getting signature for {category}.{tool}: {e}")
            return {
                "is_async": True,  # Default to async
                "parameters": {},
                "docstring": "",
            }

    def generate_test_file(self, category: str, tool: str) -> str:
        """Generate a test file for a tool."""
        signature = self.get_tool_signature(category, tool)

        # Extract first parameter for function
        first_param = ""
        test_params = []
        for name, info in signature.get("parameters", {}).items():
            if info["required"]:
                if "path" in name.lower():
                    test_params.append(f'{name}="/tmp/test_{tool}_file"')
                elif "url" in name.lower():
                    test_params.append(f'{name}="https://example.com"')
                elif "cid" in name.lower():
                    test_params.append(f'{name}="QmTest123"')
                elif "command" in name.lower():
                    test_params.append(f'{name}="echo test"')
                elif "query" in name.lower():
                    test_params.append(f'{name}="SELECT * LIMIT 10"')
                elif "code" in name.lower():
                    test_params.append(f'{name}="print(\'Hello\')"')
                elif "vector" in name.lower():
                    test_params.append(f'{name}=[[1.0, 2.0], [3.0, 4.0]]')
                else:
                    test_params.append(f'{name}="test_{name}"')

        # Generate parameter string
        params_str = ", ".join(test_params)

        # Check if async
        is_async = signature.get("is_async", True)

        # Generate test file content
        template = f"""#!/usr/bin/env python3
\"\"\"
Test for the {category}.{tool} MCP tool.

This test verifies that the {tool} tool works correctly.
\"\"\"

import unittest
import sys
import os
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

class Test{tool.title().replace("_", "")}(unittest.TestCase):
    \"\"\"Test case for the {tool} MCP tool.\"\"\"

    def setUp(self):
        \"\"\"Set up test environment.\"\"\"
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        \"\"\"Clean up after tests.\"\"\"
        self.loop.close()

    def test_{tool}_returns_valid_result(self):
        \"\"\"Test that {tool} returns a valid result.\"\"\"
        {'async ' if is_async else ''}def run_test():
            # Import the tool
            from ipfs_datasets_py.mcp_server.tools.{category} import {tool}

            # Create mock for any dependencies
            # with patch('dependency.module.function') as mock_func:
            #     mock_func.return_value = {'expected': 'value'}

            # Call the function
            result = {'await ' if is_async else ''}{tool}({params_str})

            # Assert the result has expected structure
            self.assertIsInstance(result, dict)
            self.assertIn('status', result)

        {'self.loop.run_until_complete(run_test())' if is_async else 'run_test()'}

if __name__ == '__main__':
    unittest.main()
"""
        return template

    def generate_tests_for_untested_tools(self) -> int:
        """Generate test files for untested tools."""
        print("\n=== Generating Tests for Untested Tools ===")

        generated_count = 0
        for category, tool in self.untested_tools:
            try:
                test_content = self.generate_test_file(category, tool)

                # Create output path
                output_path = self.test_path / f"test_mcp_{tool}.py"

                # Don't overwrite existing test file
                if not output_path.exists():
                    output_path.write_text(test_content)
                    print(f"✓ Generated test for {category}.{tool}: {output_path}")
                    generated_count += 1
                else:
                    print(f"⚠ Test already exists for {category}.{tool}: {output_path}")
            except Exception as e:
                print(f"✗ Error generating test for {category}.{tool}: {e}")

        print(f"\nGenerated {generated_count} new test files")
        return generated_count

    def run_all_tests(self):
        """Run all MCP tool tests."""
        print("\n=== Running Generated Tests ===")

        # Change to project directory and run pytest
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

        # Run tests in the test directory
        test_command = "python -m pytest test/test_mcp_*.py -v"
        print(f"Running: {test_command}")
        os.system(test_command)

    def run(self):
        """Execute the full test generation process."""
        self.discover_all_tools()
        self.find_existing_tests()
        self.identify_untested_tools()
        self.generate_tests_for_untested_tools()
        print("\nTo run all tests, execute:")
        print("python -m pytest test/test_mcp_*.py -v")

if __name__ == "__main__":
    generator = MCPToolsTestGenerator()
    generator.run()
