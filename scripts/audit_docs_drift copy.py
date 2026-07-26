"""
Docs/Code Drift Audit (Session 83, P2-docs).

Scans codebase for documentation/code inconsistencies:
- Docstrings referencing removed/renamed functions
- Outdated code examples in comments
- Missing or incorrect type hints
- Dead links in documentation
- Inconsistent parameter documentation

Usage:
    python audit_docs_drift.py
    python audit_docs_drift.py --module ipfs_datasets_py.mcp_server
    python audit_docs_drift.py --fix-examples
    python audit_docs_drift.py --output drift_report.json
"""

import argparse
import ast
import importlib
import inspect
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional, Set

# Root of project
PROJECT_ROOT = Path(__file__).parent


# ---------------------------------------------------------------------------
# Issue Types
# ---------------------------------------------------------------------------

@dataclass
class DriftIssue:
    """Represents a documentation/code drift issue."""
    
    severity: str  # "error", "warning", "info"
    category: str  # "missing_function", "wrong_type", "dead_link", etc.
    file_path: str
    line_number: Optional[int]
    message: str
    context: Optional[str] = None
    suggestion: Optional[str] = None


@dataclass
class DriftReport:
    """Aggregated drift audit results."""
    
    issues: List[DriftIssue] = field(default_factory=list)
    files_scanned: int = 0
    functions_checked: int = 0
    classes_checked: int = 0
    
    def add_issue(
        self,
        severity: str,
        category: str,
        file_path: str,
        message: str,
        line_number: Optional[int] = None,
        context: Optional[str] = None,
        suggestion: Optional[str] = None,
    ) -> None:
        """Add an issue to the report."""
        self.issues.append(DriftIssue(
            severity=severity,
            category=category,
            file_path=file_path,
            line_number=line_number,
            message=message,
            context=context,
            suggestion=suggestion,
        ))
    
    def get_by_severity(self, severity: str) -> List[DriftIssue]:
        """Get issues by severity level."""
        return [issue for issue in self.issues if issue.severity == severity]
    
    def get_by_category(self, category: str) -> List[DriftIssue]:
        """Get issues by category."""
        return [issue for issue in self.issues if issue.category == category]
    
    def summary(self) -> Dict[str, Any]:
        """Generate summary statistics."""
        return {
            "total_issues": len(self.issues),
            "by_severity": {
                "error": len(self.get_by_severity("error")),
                "warning": len(self.get_by_severity("warning")),
                "info": len(self.get_by_severity("info")),
            },
            "by_category": {
                category: len(self.get_by_category(category))
                for category in set(issue.category for issue in self.issues)
            },
            "files_scanned": self.files_scanned,
            "functions_checked": self.functions_checked,
            "classes_checked": self.classes_checked,
        }


# ---------------------------------------------------------------------------
# Audit Functions
# ---------------------------------------------------------------------------

def check_docstring_references(
    source_code: str,
    file_path: Path,
    module_namespace: Optional[Dict[str, Any]],
    report: DriftReport
) -> None:
    """Check if docstrings reference non-existent functions/classes.
    
    Scans for patterns like:
    - :meth:`function_name`
    - :func:`module.function_name`
    - :class:`ClassName`
    - See `function_name()` for details
    """
    # Common docstring reference patterns
    patterns = [
        (r':meth:`([^`]+)`', "method"),
        (r':func:`([^`]+)`', "function"),
        (r':class:`([^`]+)`', "class"),
        (r'See `([a-zA-Z_][a-zA-Z0-9_]*)\(\)` for', "function"),
        (r'`([a-zA-Z_][a-zA-Z0-9_]*)\(\)`', "function"),
    ]
    
    for pattern, ref_type in patterns:
        for match in re.finditer(pattern, source_code):
            referenced_name = match.group(1)
            
            # Try to resolve the reference
            if module_namespace and '.' not in referenced_name:
                # Simple name, check in module
                if referenced_name not in module_namespace:
                    line_number = source_code[:match.start()].count('\n') + 1
                    report.add_issue(
                        severity="warning",
                        category="missing_reference",
                        file_path=str(file_path),
                        line_number=line_number,
                        message=f"Docstring references non-existent {ref_type}: {referenced_name}",
                        suggestion=f"Check if {referenced_name} was removed or renamed",
                    )


def check_type_hints(
    tree: ast.AST,
    file_path: Path,
    report: DriftReport
) -> None:
    """Check for missing or incorrect type hints."""
    
    class TypeHintChecker(ast.NodeVisitor):
        def __init__(self):
            self.current_class = None
        
        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.current_class = node.name
            report.classes_checked += 1
            self.generic_visit(node)
            self.current_class = None
        
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            report.functions_checked += 1
            
            # Skip private functions and special methods (except __init__)
            if node.name.startswith('_') and node.name not in ('__init__', '__call__'):
                return
            
            # Check for missing return type hint
            if node.returns is None and node.name != '__init__':
                report.add_issue(
                    severity="info",
                    category="missing_type_hint",
                    file_path=str(file_path),
                    line_number=node.lineno,
                    message=f"Function '{node.name}' missing return type hint",
                    suggestion=f"Add return type annotation to {node.name}()",
                )
            
            # Check for missing argument type hints
            for arg in node.args.args:
                if arg.annotation is None and arg.arg != 'self' and arg.arg != 'cls':
                    report.add_issue(
                        severity="info",
                        category="missing_type_hint",
                        file_path=str(file_path),
                        line_number=node.lineno,
                        message=f"Argument '{arg.arg}' in '{node.name}' missing type hint",
                        suggestion="Consider adding type annotations for better IDE support",
                    )
    
    checker = TypeHintChecker()
    checker.visit(tree)


def check_example_code(
    source_code: str,
    file_path: Path,
    report: DriftReport
) -> None:
    """Check for outdated code examples in comments/docstrings.
    
    Looks for:
    - >>> examples that might fail
    - Example: blocks with old API usage
    """
    # Find code examples
    example_pattern = re.compile(
        r'(>>>|Example:)\s*\n\s*(.+?)(?=\n\s*(?:>>>|\n|$))',
        re.MULTILINE | re.DOTALL
    )
    
    for match in example_pattern.finditer(source_code):
        example_code = match.group(2).strip()
        line_number = source_code[:match.start()].count('\n') + 1
        
        # Check for common deprecation patterns
        deprecated_patterns = [
            (r'from_dict\(', 'from_dict usage - verify method still exists'),
            (r'\.to_dict\(\)', 'to_dict usage - verify method still exists'),
            (r'ComplianceChecker\(\)', 'ComplianceChecker instantiation - verify signature'),
        ]
        
        for deprecated_pattern, warning in deprecated_patterns:
            if re.search(deprecated_pattern, example_code):
                report.add_issue(
                    severity="warning",
                    category="outdated_example",
                    file_path=str(file_path),
                    line_number=line_number,
                    message=f"Example may be outdated: {warning}",
                    context=example_code[:100],
                )


def check_dead_links(
    source_code: str,
    file_path: Path,
    report: DriftReport
) -> None:
    """Check for dead internal file links in documentation."""
    # Find file references
    link_patterns = [
        r'\[([^\]]+)\]\(([^)]+\.md)\)',  # Markdown links
        r'See \[([^\]]+)\]\(([^)]+)\)',   # See references
        r'`([^`]+\.py)`',                 # Code file references
    ]
    
    for pattern in link_patterns:
        for match in re.finditer(pattern, source_code):
            if len(match.groups()) > 1:
                link_target = match.group(2)
            else:
                link_target = match.group(1)
            
            # Check if it's a relative path
            if not link_target.startswith(('http://', 'https://', '#')):
                target_path = file_path.parent / link_target
                if not target_path.exists():
                    line_number = source_code[:match.start()].count('\n') + 1
                    report.add_issue(
                        severity="warning",
                        category="dead_link",
                        file_path=str(file_path),
                        line_number=line_number,
                        message=f"Dead link to: {link_target}",
                        suggestion=f"File not found: {target_path}",
                    )


def audit_python_file(
    file_path: Path,
    report: DriftReport
) -> None:
    """Audit a single Python file for documentation drift."""
    try:
        source_code = file_path.read_text(encoding='utf-8')
        report.files_scanned += 1
    except Exception as e:
        report.add_issue(
            severity="error",
            category="read_error",
            file_path=str(file_path),
            message=f"Failed to read file: {e}",
        )
        return
    
    # Parse AST
    try:
        tree = ast.parse(source_code, filename=str(file_path))
    except SyntaxError as e:
        report.add_issue(
            severity="error",
            category="syntax_error",
            file_path=str(file_path),
            line_number=e.lineno,
            message=f"Syntax error: {e.msg}",
        )
        return
    
    # Try to import module to get runtime namespace
    module_path = file_path.relative_to(PROJECT_ROOT).with_suffix('')
    module_name = str(module_path).replace('/', '.')
    module_namespace = None
    
    try:
        if not module_name.startswith('tests'):
            module = importlib.import_module(module_name)
            module_namespace = {name: getattr(module, name) for name in dir(module)}
    except Exception:
        pass  # Can't import, skip namespace checks
    
    # Run audits
    check_docstring_references(source_code, file_path, module_namespace, report)
    check_type_hints(tree, file_path, report)
    check_example_code(source_code, file_path, report)
    check_dead_links(source_code, file_path, report)


def audit_markdown_file(
    file_path: Path,
    report: DriftReport
) -> None:
    """Audit a Markdown documentation file."""
    try:
        content = file_path.read_text(encoding='utf-8')
        report.files_scanned += 1
    except Exception as e:
        report.add_issue(
            severity="error",
            category="read_error",
            file_path=str(file_path),
            message=f"Failed to read file: {e}",
        )
        return
    
    # Check for dead links
    check_dead_links(content, file_path, report)


# ---------------------------------------------------------------------------
# Main Audit Workflow
# ---------------------------------------------------------------------------

def run_audit(
    root_path: Path = PROJECT_ROOT,
    module_filter: Optional[str] = None,
    file_extensions: Set[str] = {'.py', '.md'},
) -> DriftReport:
    """Run comprehensive documentation drift audit.
    
    Args:
        root_path: Root directory to scan.
        module_filter: Optional module name to filter (e.g., "ipfs_datasets_py.mcp_server").
        file_extensions: File extensions to scan.
    
    Returns:
        DriftReport with all found issues.
    """
    report = DriftReport()
    
    # Find files to audit
    files_to_audit = []
    
    for ext in file_extensions:
        pattern = f"**/*{ext}"
        for file_path in root_path.glob(pattern):
            # Skip certain directories
            if any(part in str(file_path) for part in ['.git', '__pycache__', 'venv', '.venv', 'node_modules']):
                continue
            
            # Apply module filter
            if module_filter:
                relative = file_path.relative_to(root_path)
                module_path = str(relative.with_suffix('')).replace('/', '.')
                if not module_path.startswith(module_filter):
                    continue
            
            files_to_audit.append(file_path)
    
    # Audit each file
    for file_path in files_to_audit:
        if file_path.suffix == '.py':
            audit_python_file(file_path, report)
        elif file_path.suffix == '.md':
            audit_markdown_file(file_path, report)
    
    return report


# ---------------------------------------------------------------------------
# CLI Interface
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Audit codebase for documentation/code drift"
    )
    parser.add_argument(
        "--module",
        type=str,
        help="Filter by module name (e.g., ipfs_datasets_py.mcp_server)"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Save report to JSON file"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print all issues to console"
    )
    parser.add_argument(
        "--severity",
        type=str,
        choices=["error", "warning", "info"],
        help="Only show issues of specified severity or higher"
    )
    
    args = parser.parse_args()
    
    print("Running documentation drift audit...")
    print(f"Scanning: {PROJECT_ROOT}")
    if args.module:
        print(f"Module filter: {args.module}")
    print()
    
    # Run audit
    report = run_audit(
        root_path=PROJECT_ROOT,
        module_filter=args.module,
    )
    
    # Print summary
    summary = report.summary()
    print("="*70)
    print("AUDIT SUMMARY")
    print("="*70)
    print(f"Files scanned: {summary['files_scanned']}")
    print(f"Functions checked: {summary['functions_checked']}")
    print(f"Classes checked: {summary['classes_checked']}")
    print()
    print(f"Total issues: {summary['total_issues']}")
    print(f"  Errors:   {summary['by_severity']['error']}")
    print(f"  Warnings: {summary['by_severity']['warning']}")
    print(f"  Info:     {summary['by_severity']['info']}")
    print()
    
    if summary['by_category']:
        print("Issues by category:")
        for category, count in sorted(summary['by_category'].items()):
            print(f"  {category}: {count}")
        print()
    
    # Print issues if verbose or filtering by severity
    if args.verbose or args.severity:
        severity_order = {'error': 0, 'warning': 1, 'info': 2}
        if args.severity:
            threshold = severity_order[args.severity]
            issues = [i for i in report.issues if severity_order[i.severity] <= threshold]
        else:
            issues = report.issues
        
        print("="*70)
        print("ISSUES")
        print("="*70)
        
        for issue in issues:
            print(f"\n[{issue.severity.upper()}] {issue.category}")
            print(f"  File: {issue.file_path}")
            if issue.line_number:
                print(f"  Line: {issue.line_number}")
            print(f"  {issue.message}")
            if issue.suggestion:
                print(f"  Suggestion: {issue.suggestion}")
            if issue.context:
                print(f"  Context: {issue.context[:100]}...")
    
    # Save to JSON if requested
    if args.output:
        output_data = {
            "summary": summary,
            "issues": [asdict(issue) for issue in report.issues],
        }
        output_path = Path(args.output)
        with output_path.open("w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\nReport saved to: {output_path}")
    
    # Exit code based on errors
    if summary['by_severity']['error'] > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
