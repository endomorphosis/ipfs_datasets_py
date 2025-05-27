#!/usr/bin/env python3
"""
MCP Tools Test Coverage Analyzer

This script analyzes test coverage for MCP tools by comparing tool modules
with existing test files and generates test files for any missing tests.
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple

class MCPToolsTestAnalyzer:
    """Analyzer for MCP tool test coverage."""

    def __init__(self):
        self.tools_dir = Path("ipfs_datasets_py/mcp_server/tools")
        self.test_dir = Path("test")
        self.tool_files = []
        self.test_files = []
        self.tool_modules = {}
        self.test_coverage = {}
        self.missing_tests = {}
    
    def find_tool_files(self):
        """Find all MCP tool implementation files."""
        print("=== Finding MCP Tool Files ===")
        
        if not self.tools_dir.exists():
            print(f"Error: Tools directory not found at {self.tools_dir}")
            return
        
        for category_dir in self.tools_dir.iterdir():
            if not category_dir.is_dir() or category_dir.name.startswith('__'):
                continue
                
            category = category_dir.name
            self.tool_modules[category] = []
            
            for tool_file in category_dir.glob('*.py'):
                if tool_file.name.startswith('__'):
                    continue
                
                tool_name = tool_file.stem
                self.tool_modules[category].append(tool_name)
                self.tool_files.append((category, tool_name, tool_file))
                
        print(f"Found {len(self.tool_files)} tool files across {len(self.tool_modules)} categories")
        
        # Print all found tools
        for category, tools in self.tool_modules.items():
            print(f"- {category}: {len(tools)} tools")
            for tool in sorted(tools):
                print(f"  - {tool}")

    def find_test_files(self):
        """Find all MCP tool test files."""
        print("\n=== Finding MCP Tool Test Files ===")
        
        if not self.test_dir.exists():
            print(f"Error: Test directory not found at {self.test_dir}")
            return
        
        # Look for test files that match the MCP tool naming pattern
        for test_file in self.test_dir.glob('test_mcp_*.py'):
            tool_name = test_file.stem.replace('test_mcp_', '')
            self.test_files.append((tool_name, test_file))
        
        print(f"Found {len(self.test_files)} MCP tool test files")
        
        # Print all found test files
        for tool_name, test_file in sorted(self.test_files):
            print(f"- {test_file.name} (testing: {tool_name})")
    
    def analyze_test_coverage(self):
        """Analyze test coverage for MCP tools."""
        print("\n=== Analyzing Test Coverage ===")
        
        # Create a set of tool names with tests
        tested_tools = {tool_name for tool_name, _ in self.test_files}
        
        # Check each tool against the tested tools set
        for category, tools in self.tool_modules.items():
            self.test_coverage[category] = {
                'total': len(tools),
                'tested': 0,
                'missing': 0,
                'tools': {}
            }
            
            for tool in tools:
                has_test = tool in tested_tools
                self.test_coverage[category]['tools'][tool] = has_test
                
                if has_test:
                    self.test_coverage[category]['tested'] += 1
                else:
                    self.test_coverage[category]['missing'] += 1
                    if category not in self.missing_tests:
                        self.missing_tests[category] = []
                    self.missing_tests[category].append(tool)
        
        # Calculate overall statistics
        total_tools = sum(data['total'] for data in self.test_coverage.values())
        total_tested = sum(data['tested'] for data in self.test_coverage.values())
        total_missing = sum(data['missing'] for data in self.test_coverage.values())
        
        if total_tools > 0:
            coverage_pct = (total_tested / total_tools) * 100
            print(f"Overall test coverage: {total_tested}/{total_tools} tools ({coverage_pct:.1f}%)")
            
            for category, data in self.test_coverage.items():
                if data['total'] > 0:
                    cat_coverage_pct = (data['tested'] / data['total']) * 100
                    print(f"- {category}: {data['tested']}/{data['total']} tools ({cat_coverage_pct:.1f}%)")
        else:
            print("No tools found for analysis")
    
    def generate_missing_test_template(self, category: str, tool_name: str) -> str:
        """Generate a template for a missing test file."""
        template = f"""#!/usr/bin/env python3
\"\"\"
Test for the {tool_name} MCP tool in the {category} category.
\"\"\"

import unittest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import sys
sys.path.insert(0, '.')

from ipfs_datasets_py.mcp_server.tools.{category} import {tool_name}

class Test{tool_name.title().replace('_', '')}(unittest.TestCase):
    \"\"\"Test case for the {tool_name} MCP tool.\"\"\"
    
    def setUp(self):
        \"\"\"Set up test fixtures.\"\"\"
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
    
    def tearDown(self):
        \"\"\"Clean up after tests.\"\"\"
        self.loop.close()
    
    def async_test(self, coro):
        \"\"\"Helper to run async tests.\"\"\"
        return self.loop.run_until_complete(coro)
    
    @patch('ipfs_datasets_py.mcp_server.tools.{category}.{tool_name}.{tool_name}')
    def test_{tool_name}_basic(self, mock_{tool_name}):
        \"\"\"Test basic functionality of {tool_name}.\"\"\"
        mock_{tool_name}.return_value = {{'status': 'success'}}
        
        # Replace with appropriate test parameters
        async def run_test():
            result = await {tool_name}()
            self.assertEqual(result['status'], 'success')
        
        self.async_test(run_test())

if __name__ == '__main__':
    unittest.main()
"""
        return template
    
    def generate_missing_tests(self):
        """Generate test files for MCP tools that are missing tests."""
        print("\n=== Generating Missing Tests ===")
        
        if not self.missing_tests:
            print("No missing tests to generate.")
            return
        
        generated_count = 0
        for category, tools in self.missing_tests.items():
            for tool in tools:
                test_file_path = self.test_dir / f"test_mcp_{tool}.py"
                
                # Only generate if the file doesn't exist
                if not test_file_path.exists():
                    template = self.generate_missing_test_template(category, tool)
                    
                    # Write to stdout instead of file to avoid side effects
                    print(f"\n--- Generated Test for {category}.{tool} ---")
                    print(f"Would create file: {test_file_path}")
                    print("First few lines of the template:")
                    print("\n".join(template.split("\n")[:5]) + "\n...\n")
                    
                    generated_count += 1
        
        print(f"\nGenerated templates for {generated_count} missing tests")
        
        # Create a summary report file
        self.generate_summary_report()
    
    def generate_summary_report(self):
        """Generate a summary report of test coverage."""
        report = "# MCP Tools Test Coverage Report\n\n"
        
        # Overall statistics
        total_tools = sum(data['total'] for data in self.test_coverage.values())
        total_tested = sum(data['tested'] for data in self.test_coverage.values())
        total_missing = sum(data['missing'] for data in self.test_coverage.values())
        
        coverage_pct = (total_tested / total_tools) * 100 if total_tools > 0 else 0
        
        report += "## Overall Statistics\n"
        report += f"- Total MCP tools: {total_tools}\n"
        report += f"- Tools with tests: {total_tested} ({coverage_pct:.1f}%)\n"
        report += f"- Tools without tests: {total_missing} ({100-coverage_pct:.1f}%)\n\n"
        
        # Category breakdown
        report += "## Coverage by Category\n\n"
        
        for category, data in self.test_coverage.items():
            cat_coverage_pct = (data['tested'] / data['total']) * 100 if data['total'] > 0 else 0
            report += f"### {category}\n"
            report += f"- Coverage: {data['tested']}/{data['total']} tools ({cat_coverage_pct:.1f}%)\n"
            
            # List tools without tests
            if data['missing'] > 0:
                report += "- Missing tests for:\n"
                for tool, has_test in data['tools'].items():
                    if not has_test:
                        report += f"  - {tool}\n"
            report += "\n"
        
        # Save the report
        with open('mcp_tools_test_coverage_report.md', 'w') as f:
            f.write(report)
        
        print(f"Test coverage report saved to mcp_tools_test_coverage_report.md")
        
        # Save coverage data to JSON
        with open('mcp_tools_test_coverage.json', 'w') as f:
            json.dump(self.test_coverage, f, indent=2)
        
        print(f"Test coverage data saved to mcp_tools_test_coverage.json")
    
    def run(self):
        """Run the complete analysis process."""
        self.find_tool_files()
        self.find_test_files()
        self.analyze_test_coverage()
        self.generate_missing_tests()
        
        print("\nAnalysis complete!")

if __name__ == "__main__":
    analyzer = MCPToolsTestAnalyzer()
    analyzer.run()
