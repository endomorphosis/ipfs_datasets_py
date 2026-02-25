#!/usr/bin/env python3
"""Documentation drift audit tool for optimiz module.

Checks that code examples in documentation are still valid and that
documented APIs match actual implementation.
"""

import re
import ast
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple


class DocsAuditor:
    """Audits documentation for drift from actual code."""
    
    def __init__(self, optimizers_root: Path):
        """Initialize auditor.
        
        Args:
            optimizers_root: Path to optimizers module root
        """
        self.root = optimizers_root
        self.issues: List[Dict[str, str]] = []
    
    def check_imports_in_examples(self, doc_file: Path) -> List[Dict[str, str]]:
        """Extract and verify import statements from code examples.
        
        Args:
            doc_file: Documentation file to check
            
        Returns:
            List of issues found
        """
        issues = []
        content = doc_file.read_text()
        
        # Extract code blocks marked as python
        code_blocks = re.findall(r'```python\n(.*?)```', content, re.DOTALL)
        
        for idx, code in enumerate(code_blocks, 1):
            # Extract import statements
            imports = re.findall(r'^(?:from|import)\s+[\w.]+.*$', code, re.MULTILINE)
            
            for imp in imports:
                # Try to parse and validate import
                try:
                    ast.parse(imp)
                except SyntaxError:
                    issues.append({
                        'file': str(doc_file.name),
                        'block': str(idx),
                        'type': 'syntax_error',
                        'detail': f'Invalid import statement: {imp}',
                    })
                    continue
                
                # Check if module actually exists (simple heuristic)
                module_name = self._extract_module_name(imp)
                if module_name and not self._module_exists(module_name):
                    issues.append({
                        'file': str(doc_file.name),
                        'block': str(idx),
                        'type': 'missing_module',
                        'detail': f'Module not found: {module_name} (import: {imp})',
                    })
        
        return issues
    
    def _extract_module_name(self, import_statement: str) -> str:
        """Extract module name from import statement."""
        # from X import Y -> X
        # import X -> X
        match = re.match(r'(?:from\s+([\w.]+)|import\s+([\w.]+))', import_statement)
        if match:
            return match.group(1) or match.group(2)
        return ""
    
    def _module_exists(self, module_name: str) -> bool:
        """Check if module exists in the codebase."""
        # Check if it's in optimizers module
        parts = module_name.split('.')
        if parts[0] in ('ipfs_datasets_py', 'optimizers'):
            # Start from optimizers root for relative imports
            if parts[0] == 'ipfs_datasets_py' and len(parts) > 1 and parts[1] == 'optimizers':
                parts = parts[2:]  # Strip ipfs_datasets_py.optimizers prefix
            elif parts[0] == 'optimizers':
                parts = parts[1:]
            
            check_path = self.root
            for part in parts:
                check_path = check_path / part
                if not check_path.exists():
                    # Try as py file
                    if (check_path.parent / f"{part}.py").exists():
                        return True
                    return False
            return True
        
        # External module - assume it exists
        return True
    
    def check_class_references(self, doc_file: Path) -> List[Dict[str, str]]:
        """Check that referenced classes exist.
        
        Args:
            doc_file: Documentation file to check
            
        Returns:
            List of issues found
        """
        issues = []
        content = doc_file.read_text()
        
        # Find class references like :class:`ClassName` or `ClassName`
        class_refs = re.findall(r':class:`([^`]+)`|`([A-Z][a-zA-Z]+)`', content)
        
        for ref in class_refs:
            class_name = ref[0] or ref[1]
            # Skip generic examples
            if class_name in ('MyClass', 'Example', 'YourClass'):
                continue
            
            # Search for class definition in codebase
            if not self._class_exists(class_name):
                issues.append({
                    'file': str(doc_file.name),
                    'type': 'missing_class',
                    'detail': f'Referenced class not found: {class_name}',
                })
        
        return issues
    
    def _class_exists(self, class_name: str) -> bool:
        """Check if class exists in the codebase."""
        # grep for class definition
        try:
            result = subprocess.run(
                ['grep', '-r', f'^class {class_name}\\b', str(self.root), '--include=*.py'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return True  # Assume exists if can't check
    
    def audit_file(self, doc_file: Path) -> List[Dict[str, str]]:
        """Audit a single documentation file.
        
        Args:
            doc_file: Path to documentation file
            
        Returns:
            List of issues found
        """
        issues = []
        
        if not doc_file.exists():
            return [{'file': str(doc_file), 'type': 'missing_file', 'detail': 'File not found'}]
        
        # Check imports in code examples
        issues.extend(self.check_imports_in_examples(doc_file))
        
        # Check class references
        issues.extend(self.check_class_references(doc_file))
        
        return issues
    
    def audit_all(self) -> Dict[str, List[Dict[str, str]]]:
        """Audit all documentation files.
        
        Returns:
            Dict mapping file names to lists of issues
        """
        results = {}
        
        # Find all .md files
        md_files = list(self.root.glob('*.md')) + list(self.root.glob('docs/**/*.md'))
        
        for doc_file in md_files:
            issues = self.audit_file(doc_file)
            if issues:
                results[str(doc_file.name)] = issues
        
        return results
    
    def generate_report(self, results: Dict[str, List[Dict[str, str]]]) -> str:
        """Generate human-readable report.
        
        Args:
            results: Audit results from audit_all()
            
        Returns:
            Formatted report string
        """
        if not results:
            return "✅ No documentation drift detected!"
        
        report_lines = []
        report_lines.append("# Documentation Drift Audit Report\n")
        report_lines.append(f"Found {sum(len(v) for v in results.values())} issues across {len(results)} files\n")
        
        for file_name, issues in sorted(results.items()):
            report_lines.append(f"\n## {file_name}")
            report_lines.append(f"**{len(issues)} issue(s)**\n")
            
            for issue in issues:
                issue_type = issue.get('type', 'unknown')
                detail = issue.get('detail', 'No details')
                block = issue.get('block', '')
                block_str = f" (code block #{block})" if block else ""
                
                report_lines.append(f"- **{issue_type}**{block_str}: {detail}")
        
        return "\n".join(report_lines)


def main():
    """Run the documentation audit."""
    import sys
    
    # Determine optimizers root
    script_dir = Path(__file__).parent
    if (script_dir / 'optimizers').exists():
        optimizers_root = script_dir / 'ipfs_datasets_py' / 'optimizers'
    else:
        # Assume we're in the optimizers directory
        optimizers_root = script_dir
    
    auditor = DocsAuditor(optimizers_root)
    results = auditor.audit_all()
    report = auditor.generate_report(results)
    
    print(report)
    
    # Exit with error code if issues found
    sys.exit(1 if results else 0)


if __name__ == '__main__':
    main()
