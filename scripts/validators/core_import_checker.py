#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Core Import Checker

Validates that MCP tools properly import and delegate to core modules.

Usage:
    python scripts/validators/core_import_checker.py
    python scripts/validators/core_import_checker.py --report json
"""

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Set


class CoreImportChecker:
    """Validates MCP tools use core modules correctly."""
    
    CORE_MODULE_PREFIXES = [
        'ipfs_datasets_py.processors',
        'ipfs_datasets_py.caching',
        'ipfs_datasets_py.logic',
        'ipfs_datasets_py.embeddings',
        'ipfs_datasets_py.ml',
        'ipfs_datasets_py.search',
        'ipfs_datasets_py.core_operations',
    ]
    
    def __init__(self):
        """Initialize checker."""
        self.results = []
    
    def check_file(self, file_path: Path) -> Dict:
        """
        Check a single MCP tool file for core module usage.
        
        Args:
            file_path: Path to tool file
            
        Returns:
            Check result dictionary
        """
        try:
            rel_path = file_path.relative_to(Path.cwd())
        except ValueError:
            rel_path = file_path
        
        result = {
            "file": str(rel_path),
            "uses_core_modules": False,
            "core_imports": [],
            "business_logic_detected": False,
            "issues": [],
            "warnings": [],
            "delegation_pattern": "unknown"
        }
        
        try:
            with open(file_path, 'r') as f:
                content = f.read()
                tree = ast.parse(content, filename=str(file_path))
            
            # Check imports
            core_imports = []
            all_imports = []
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        all_imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        all_imports.append(node.module)
                        # Check if importing from core modules
                        for prefix in self.CORE_MODULE_PREFIXES:
                            if node.module.startswith(prefix):
                                core_imports.append(node.module)
                                break
            
            result["core_imports"] = list(set(core_imports))
            result["uses_core_modules"] = len(core_imports) > 0
            
            # Check for business logic indicators
            business_logic_indicators = []
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Check function length (business logic tends to be long)
                    func_lines = node.end_lineno - node.lineno if hasattr(node, 'end_lineno') else 0
                    if func_lines > 100:
                        business_logic_indicators.append(
                            f"Function '{node.name}' is {func_lines} lines (may contain business logic)"
                        )
                    
                    # Check for complex algorithms (nested loops, many conditionals)
                    loop_depth = self._count_max_loop_depth(node)
                    if loop_depth > 2:
                        business_logic_indicators.append(
                            f"Function '{node.name}' has loop depth {loop_depth} (algorithm implementation)"
                        )
                    
                    # Check for data processing patterns
                    has_comprehensions = any(isinstance(n, (ast.ListComp, ast.DictComp, ast.SetComp)) 
                                            for n in ast.walk(node))
                    has_filters = any(isinstance(n, ast.Call) and 
                                    getattr(n.func, 'id', None) in ['filter', 'map', 'reduce']
                                    for n in ast.walk(node))
                    
                    if has_comprehensions and has_filters:
                        business_logic_indicators.append(
                            f"Function '{node.name}' has data processing patterns (may contain business logic)"
                        )
            
            if business_logic_indicators:
                result["business_logic_detected"] = True
                result["warnings"].extend(business_logic_indicators[:3])  # Limit to first 3
            
            # Determine delegation pattern
            if result["uses_core_modules"]:
                # Check if functions delegate to core modules
                delegation_count = 0
                function_count = 0
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        function_count += 1
                        # Look for calls to imported core module classes/functions
                        for child in ast.walk(node):
                            if isinstance(child, ast.Call):
                                if isinstance(child.func, ast.Name):
                                    # Direct function call
                                    if any(child.func.id in imp for imp in core_imports):
                                        delegation_count += 1
                                        break
                                elif isinstance(child.func, ast.Attribute):
                                    # Method call
                                    if isinstance(child.func.value, ast.Name):
                                        # Check if the object is from a core module
                                        delegation_count += 1
                                        break
                
                if function_count > 0:
                    delegation_ratio = delegation_count / function_count
                    if delegation_ratio > 0.7:
                        result["delegation_pattern"] = "good"
                    elif delegation_ratio > 0.3:
                        result["delegation_pattern"] = "partial"
                    else:
                        result["delegation_pattern"] = "poor"
                        result["warnings"].append(
                            f"Only {delegation_count}/{function_count} functions delegate to core modules"
                        )
                else:
                    result["delegation_pattern"] = "n/a"
            else:
                result["delegation_pattern"] = "none"
                if not result["business_logic_detected"]:
                    result["warnings"].append(
                        "No core module imports, but also no obvious business logic (may be utility file)"
                    )
                else:
                    result["issues"].append(
                        "Business logic detected but no core module imports (should be refactored)"
                    )
            
        except Exception as e:
            result["issues"].append(f"Check error: {str(e)}")
        
        return result
    
    def _count_max_loop_depth(self, node: ast.AST) -> int:
        """Count maximum loop nesting depth."""
        def count_depth(n, current_depth=0):
            max_depth = current_depth
            for child in ast.iter_child_nodes(n):
                if isinstance(child, (ast.For, ast.While)):
                    child_depth = count_depth(child, current_depth + 1)
                    max_depth = max(max_depth, child_depth)
                else:
                    child_depth = count_depth(child, current_depth)
                    max_depth = max(max_depth, child_depth)
            return max_depth
        
        return count_depth(node)
    
    def check_directory(self, tools_dir: Path) -> List[Dict]:
        """
        Check all MCP tools in a directory.
        
        Args:
            tools_dir: Path to MCP tools directory
            
        Returns:
            List of check results
        """
        results = []
        
        for tool_file in tools_dir.rglob("*.py"):
            if tool_file.name == "__init__.py" or "test" in tool_file.name:
                continue
            if tool_file.name == "tool_wrapper.py":
                continue
            
            result = self.check_file(tool_file)
            results.append(result)
        
        self.results = results
        return results
    
    def generate_report(self, format: str = "text") -> str:
        """Generate check report."""
        if format == "json":
            return json.dumps({
                "total_files": len(self.results),
                "using_core_modules": len([r for r in self.results if r["uses_core_modules"]]),
                "with_business_logic": len([r for r in self.results if r["business_logic_detected"]]),
                "results": self.results
            }, indent=2)
        
        lines = ["=" * 80, "Core Import Checker Report", "=" * 80, ""]
        
        total = len(self.results)
        using_core = len([r for r in self.results if r["uses_core_modules"]])
        with_business_logic = len([r for r in self.results if r["business_logic_detected"]])
        
        lines.append(f"Total files analyzed: {total}")
        lines.append(f"Using core modules: {using_core} ({using_core/total*100:.1f}%)")
        lines.append(f"With business logic: {with_business_logic}")
        lines.append("")
        
        # Delegation pattern breakdown
        patterns = {}
        for r in self.results:
            pattern = r["delegation_pattern"]
            patterns[pattern] = patterns.get(pattern, 0) + 1
        
        lines.append("Delegation Patterns:")
        for pattern, count in sorted(patterns.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  {pattern}: {count}")
        lines.append("")
        
        # Files needing attention
        needs_attention = [r for r in self.results 
                          if r["business_logic_detected"] and not r["uses_core_modules"]]
        
        if needs_attention:
            lines.append("=" * 80)
            lines.append("FILES NEEDING REFACTORING (Business Logic Without Core Modules):")
            lines.append("=" * 80)
            for result in needs_attention:
                lines.append(f"- {result['file']}")
                for issue in result["issues"]:
                    lines.append(f"  • {issue}")
                for warning in result["warnings"][:2]:
                    lines.append(f"  ⚠ {warning}")
                lines.append("")
        
        # Good examples
        good_examples = [r for r in self.results 
                        if r["uses_core_modules"] and r["delegation_pattern"] == "good"]
        
        if good_examples:
            lines.append("=" * 80)
            lines.append("GOOD EXAMPLES (Proper Core Module Usage):")
            lines.append("=" * 80)
            for result in good_examples[:10]:  # Limit to 10
                lines.append(f"✓ {result['file']}")
                lines.append(f"  Imports: {', '.join(result['core_imports'][:2])}")
                lines.append("")
        
        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Check core module imports in MCP tools")
    parser.add_argument(
        "--tools-dir",
        type=str,
        default="ipfs_datasets_py/mcp_server/tools",
        help="Path to MCP tools directory"
    )
    parser.add_argument(
        "--report",
        choices=["text", "json"],
        default="text",
        help="Report format"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file (default: stdout)"
    )
    
    args = parser.parse_args()
    
    checker = CoreImportChecker()
    
    tools_dir = Path(args.tools_dir)
    if not tools_dir.exists():
        print(f"Error: Tools directory not found: {tools_dir}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Checking imports in {tools_dir}...", file=sys.stderr)
    checker.check_directory(tools_dir)
    
    report = checker.generate_report(format=args.report)
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(report)
    
    sys.exit(0)


if __name__ == "__main__":
    main()
