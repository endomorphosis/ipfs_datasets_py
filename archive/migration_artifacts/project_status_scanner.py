#!/usr/bin/env python3
"""
Project Status Scanner for IPFS Datasets MCP Server

This script provides a comprehensive assessment of what needs to be done
to complete the MCP server project.
"""

import os
import sys
import json
import asyncio
import importlib
import traceback
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

class ProjectStatusScanner:
    def __init__(self):
        self.project_root = Path(__file__).resolve().parent
        self.mcp_server_path = self.project_root / "ipfs_datasets_py" / "mcp_server"
        self.tools_path = self.mcp_server_path / "tools"

        self.status = {
            "tools_analysis": {},
            "server_status": {},
            "missing_components": [],
            "test_coverage": {},
            "integration_status": {},
            "recommendations": []
        }

    def scan_tools_structure(self):
        """Scan all tool categories and their implementations."""
        print("🔍 Scanning MCP Tools Structure...")

        if not self.tools_path.exists():
            self.status["missing_components"].append("Tools directory not found")
            return

        tool_categories = []
        for item in self.tools_path.iterdir():
            if item.is_dir() and not item.name.startswith('__'):
                tool_categories.append(item.name)

        print(f"Found {len(tool_categories)} tool categories: {', '.join(tool_categories)}")

        for category in tool_categories:
            category_path = self.tools_path / category
            tools = []

            for item in category_path.iterdir():
                if item.is_file() and item.suffix == '.py' and not item.name.startswith('__'):
                    tool_name = item.stem
                    tools.append(tool_name)

            self.status["tools_analysis"][category] = {
                "tools": tools,
                "count": len(tools),
                "path": str(category_path)
            }

            print(f"  {category}: {len(tools)} tools - {', '.join(tools)}")

    def test_tool_imports(self):
        """Test if all tools can be imported successfully."""
        print("\n🧪 Testing Tool Imports...")

        import_results = {}
        total_tools = 0
        successful_imports = 0

        for category, info in self.status["tools_analysis"].items():
            category_results = []

            for tool_name in info["tools"]:
                total_tools += 1
                try:
                    module_path = f"ipfs_datasets_py.mcp_server.tools.{category}.{tool_name}"
                    module = importlib.import_module(module_path)

                    # Check if the tool has the expected function
                    if hasattr(module, tool_name):
                        category_results.append({
                            "name": tool_name,
                            "status": "✅ Import OK",
                            "has_function": True
                        })
                        successful_imports += 1
                    else:
                        category_results.append({
                            "name": tool_name,
                            "status": "⚠️ Import OK but no main function",
                            "has_function": False
                        })

                except Exception as e:
                    category_results.append({
                        "name": tool_name,
                        "status": f"❌ Import failed: {str(e)[:50]}...",
                        "error": str(e)
                    })

            import_results[category] = category_results

        self.status["test_coverage"]["import_results"] = import_results
        self.status["test_coverage"]["import_success_rate"] = f"{successful_imports}/{total_tools} ({successful_imports/total_tools*100:.1f}%)" if total_tools > 0 else "0/0"

        print(f"Import Success Rate: {self.status['test_coverage']['import_success_rate']}")

        for category, results in import_results.items():
            print(f"\n  {category}:")
            for result in results:
                print(f"    {result['status']} {result['name']}")

    def check_server_components(self):
        """Check the main server components."""
        print("\n🖥️ Checking Server Components...")

        components_to_check = [
            "server.py",
            "simple_server.py",
            "configs.py",
            "logger.py",
            "__init__.py"
        ]

        server_status = {}

        for component in components_to_check:
            component_path = self.mcp_server_path / component
            if component_path.exists():
                server_status[component] = "✅ Exists"

                # Try to import key components
                if component == "server.py":
                    try:
                        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
                        server_status[component] += " (IPFSDatasetsMCPServer importable)"
                    except Exception as e:
                        server_status[component] += f" (Import error: {str(e)[:30]}...)"

                elif component == "configs.py":
                    try:
                        from ipfs_datasets_py.mcp_server.configs import Configs
                        server_status[component] += " (Configs importable)"
                    except Exception as e:
                        server_status[component] += f" (Import error: {str(e)[:30]}...)"
            else:
                server_status[component] = "❌ Missing"
                self.status["missing_components"].append(component)

        self.status["server_status"] = server_status

        for component, status in server_status.items():
            print(f"  {status} {component}")

    def check_test_coverage(self):
        """Check what test files exist."""
        print("\n🧪 Checking Test Coverage...")

        test_files = []
        for test_file in self.project_root.glob("*test*.py"):
            if "mcp" in test_file.name.lower():
                test_files.append(test_file.name)

        self.status["test_coverage"]["test_files"] = test_files
        print(f"Found {len(test_files)} MCP-related test files:")
        for test_file in test_files[:10]:  # Show first 10
            print(f"  - {test_file}")
        if len(test_files) > 10:
            print(f"  ... and {len(test_files) - 10} more")

    def analyze_integration_status(self):
        """Analyze integration with the broader library."""
        print("\n🔗 Analyzing Integration Status...")

        # Check if main library modules exist
        lib_modules = [
            "ipfs_datasets.py",
            "web_archive_utils.py",
            "ipfs_knn_index.py",
            "data_provenance.py",
            "security.py",
            "knowledge_graph_extraction.py"
        ]

        integration_status = {}
        lib_path = self.project_root / "ipfs_datasets_py"

        for module in lib_modules:
            module_path = lib_path / module
            if module_path.exists():
                integration_status[module] = "✅ Available"
            else:
                integration_status[module] = "❌ Missing"

        self.status["integration_status"] = integration_status

        for module, status in integration_status.items():
            print(f"  {status} {module}")

    def generate_recommendations(self):
        """Generate recommendations for what needs to be done."""
        print("\n💡 Generating Recommendations...")

        recommendations = []

        # Check import success rate
        if "import_success_rate" in self.status["test_coverage"]:
            success_rate = self.status["test_coverage"]["import_success_rate"]
            if "100%" not in success_rate:
                recommendations.append("🔧 Fix tool import issues - not all tools are importing correctly")

        # Check for missing server components
        if self.status["missing_components"]:
            recommendations.append(f"📁 Create missing components: {', '.join(self.status['missing_components'])}")

        # Check tool coverage vs library features
        total_tools = sum(info["count"] for info in self.status["tools_analysis"].values())
        if total_tools < 20:
            recommendations.append("🛠️ Consider adding more tools to improve library feature coverage")

        # Check for integration issues
        missing_modules = [k for k, v in self.status["integration_status"].items() if "Missing" in v]
        if missing_modules:
            recommendations.append(f"🔗 Check integration - some library modules are missing: {', '.join(missing_modules)}")

        # General recommendations
        recommendations.extend([
            "🧪 Run comprehensive functional tests on all tools",
            "📝 Validate that all library features are properly exposed via MCP tools",
            "🚀 Test the complete MCP server startup and tool registration process",
            "📋 Create integration tests with actual MCP clients",
            "🔍 Verify async/sync compatibility across all tools"
        ])

        self.status["recommendations"] = recommendations

        for i, rec in enumerate(recommendations, 1):
            print(f"  {i}. {rec}")

    def save_status_report(self):
        """Save the complete status report."""
        report_path = self.project_root / "project_status_report.json"
        with open(report_path, 'w') as f:
            json.dump(self.status, f, indent=2, default=str)
        print(f"\n📄 Full report saved to: {report_path}")

    def run_comprehensive_scan(self):
        """Run the complete project status scan."""
        print("🚀 IPFS Datasets MCP Server - Project Status Scan")
        print("=" * 60)

        self.scan_tools_structure()
        self.test_tool_imports()
        self.check_server_components()
        self.check_test_coverage()
        self.analyze_integration_status()
        self.generate_recommendations()
        self.save_status_report()

        print("\n" + "=" * 60)
        print("🎯 SCAN COMPLETE - Check recommendations above")
        print("=" * 60)

def main():
    scanner = ProjectStatusScanner()
    scanner.run_comprehensive_scan()

if __name__ == "__main__":
    main()
