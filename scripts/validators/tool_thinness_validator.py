#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tool Thinness Validator

Validates that MCP tools follow the thin wrapper pattern by checking:
- Line count (should be <400 lines)
- Complexity metrics
- Import patterns

Usage:
    python scripts/validators/tool_thinness_validator.py
    python scripts/validators/tool_thinness_validator.py --max-lines 350
    python scripts/validators/tool_thinness_validator.py --report json
"""

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple


class ToolThinnessValidator:
    """Validates MCP tools are thin wrappers."""
    
    def __init__(self, max_lines: int = 400, max_complexity: int = 10):
        """
        Initialize validator.
        
        Args:
            max_lines: Maximum lines per tool file
            max_complexity: Maximum cyclomatic complexity per function
        """
        self.max_lines = max_lines
        self.max_complexity = max_complexity
        self.results = []
    
    def validate_file(self, file_path: Path) -> Dict:
        """
        Validate a single MCP tool file.
        
        Args:
            file_path: Path to tool file
            
        Returns:
            Validation result dictionary
        """
        try:
            rel_path = file_path.relative_to(Path.cwd())
        except ValueError:
            rel_path = file_path
        
        result = {
            "file": str(rel_path),
            "line_count": 0,
            "is_thin": True,
            "issues": [],
            "warnings": []
        }
        
        try:
            # Count lines
            with open(file_path, 'r') as f:
                lines = f.readlines()
                # Count non-blank, non-comment lines
                code_lines = [l for l in lines if l.strip() and not l.strip().startswith('#')]
                result["line_count"] = len(code_lines)
            
            # Check line count
            if result["line_count"] > self.max_lines:
                result["is_thin"] = False
                result["issues"].append(
                    f"Line count ({result['line_count']}) exceeds maximum ({self.max_lines})"
                )
            elif result["line_count"] > self.max_lines * 0.8:
                result["warnings"].append(
                    f"Line count ({result['line_count']}) is close to maximum ({self.max_lines})"
                )
            
            # Parse AST for complexity
            with open(file_path, 'r') as f:
                tree = ast.parse(f.read(), filename=str(file_path))
            
            # Check for business logic patterns (large functions, complex conditionals)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Count statements in function
                    stmt_count = len([n for n in ast.walk(node) if isinstance(n, ast.stmt)])
                    if stmt_count > 50:
                        result["warnings"].append(
                            f"Function '{node.name}' has {stmt_count} statements (may contain business logic)"
                        )
                    
                    # Count nested complexity
                    complexity = self._calculate_complexity(node)
                    if complexity > self.max_complexity:
                        result["is_thin"] = False
                        result["issues"].append(
                            f"Function '{node.name}' has complexity {complexity} (max: {self.max_complexity})"
                        )
            
            # Check imports - should import from core modules
            core_imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and ('ipfs_datasets_py.processors' in node.module or
                                       'ipfs_datasets_py.caching' in node.module or
                                       'ipfs_datasets_py.logic' in node.module):
                        core_imports.append(node.module)
            
            if core_imports:
                result["core_imports"] = core_imports
                result["uses_core_modules"] = True
            else:
                result["uses_core_modules"] = False
                result["warnings"].append(
                    "No imports from core modules detected (may not follow thin wrapper pattern)"
                )
            
        except Exception as e:
            result["is_thin"] = False
            result["issues"].append(f"Validation error: {str(e)}")
        
        return result
    
    def _calculate_complexity(self, node: ast.FunctionDef) -> int:
        """Calculate cyclomatic complexity of a function."""
        complexity = 1  # Base complexity
        
        for child in ast.walk(node):
            # Count decision points
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        
        return complexity
    
    def validate_directory(self, tools_dir: Path) -> List[Dict]:
        """
        Validate all MCP tools in a directory.
        
        Args:
            tools_dir: Path to MCP tools directory
            
        Returns:
            List of validation results
        """
        results = []
        
        # Find all Python files in tools directory
        for tool_file in tools_dir.rglob("*.py"):
            # Skip __init__.py and test files
            if tool_file.name == "__init__.py" or "test" in tool_file.name:
                continue
            
            # Skip tool_wrapper.py if it exists
            if tool_file.name == "tool_wrapper.py":
                continue
            
            result = self.validate_file(tool_file)
            results.append(result)
        
        self.results = results
        return results
    
    def generate_report(self, format: str = "text") -> str:
        """
        Generate validation report.
        
        Args:
            format: Report format ('text' or 'json')
            
        Returns:
            Formatted report string
        """
        if format == "json":
            return json.dumps({
                "total_files": len(self.results),
                "thin_tools": len([r for r in self.results if r["is_thin"]]),
                "thick_tools": len([r for r in self.results if not r["is_thin"]]),
                "results": self.results
            }, indent=2)
        
        # Text format
        lines = ["=" * 80, "Tool Thinness Validation Report", "=" * 80, ""]
        
        total = len(self.results)
        thin = len([r for r in self.results if r["is_thin"]])
        thick = total - thin
        
        lines.append(f"Total files analyzed: {total}")
        lines.append(f"Thin tools (✓): {thin}")
        lines.append(f"Thick tools (✗): {thick}")
        lines.append(f"Compliance rate: {(thin/total*100) if total > 0 else 0:.1f}%")
        lines.append("")
        
        # Details for each tool
        for result in sorted(self.results, key=lambda r: r["line_count"], reverse=True):
            status = "✓" if result["is_thin"] else "✗"
            lines.append(f"{status} {result['file']}")
            lines.append(f"   Lines: {result['line_count']}")
            
            if result.get("uses_core_modules"):
                lines.append(f"   Core imports: {', '.join(result['core_imports'][:3])}")
            
            for issue in result["issues"]:
                lines.append(f"   ERROR: {issue}")
            
            for warning in result["warnings"]:
                lines.append(f"   WARNING: {warning}")
            
            lines.append("")
        
        # Summary of thick tools
        if thick > 0:
            lines.append("=" * 80)
            lines.append("THICK TOOLS REQUIRING REFACTORING:")
            lines.append("=" * 80)
            for result in [r for r in self.results if not r["is_thin"]]:
                lines.append(f"- {result['file']} ({result['line_count']} lines)")
                for issue in result["issues"]:
                    lines.append(f"  • {issue}")
            lines.append("")
        
        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Validate MCP tool thinness")
    parser.add_argument(
        "--tools-dir",
        type=str,
        default="ipfs_datasets_py/mcp_server/tools",
        help="Path to MCP tools directory"
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=400,
        help="Maximum lines per tool file"
    )
    parser.add_argument(
        "--max-complexity",
        type=int,
        default=10,
        help="Maximum cyclomatic complexity per function"
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
    
    # Validate tools
    validator = ToolThinnessValidator(
        max_lines=args.max_lines,
        max_complexity=args.max_complexity
    )
    
    tools_dir = Path(args.tools_dir)
    if not tools_dir.exists():
        print(f"Error: Tools directory not found: {tools_dir}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Validating tools in {tools_dir}...", file=sys.stderr)
    validator.validate_directory(tools_dir)
    
    # Generate report
    report = validator.generate_report(format=args.report)
    
    # Output report
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(report)
    
    # Exit with error code if thick tools found
    thick_count = len([r for r in validator.results if not r["is_thin"]])
    sys.exit(1 if thick_count > 0 else 0)


if __name__ == "__main__":
    main()
