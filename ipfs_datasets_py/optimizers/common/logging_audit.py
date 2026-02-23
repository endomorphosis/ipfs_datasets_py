"""Structured logging audit tool for optimizer module.

Scans optimizer classes and methods to audit logging patterns and identify
inconsistencies or missing logging statements. Generates a checklist of
methods and their logging status.
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple
from dataclasses import dataclass, field


@dataclass
class LoggingAuditResult:
    """Result of logging audit for a single file."""
    file_path: str
    class_name: str = ""
    methods_with_logging: List[str] = field(default_factory=list)
    methods_without_logging: List[str] = field(default_factory=list)
    logging_patterns: Dict[str, int] = field(default_factory=dict)  # Pattern -> count
    has_logger_init: bool = False
    issues: List[str] = field(default_factory=list)  # Warnings/issues


class LoggingAuditor:
    """Audits logging usage across optimizer module."""
    
    CRITICAL_METHODS = {
        'generate', 'critique', 'optimize', 'validate',
        'run_session', '__init__', 'from_dict', 'from_env',
        'merge', 'merge_outputs', 'extract', 'rank',
    }
    
    LOGGING_PATTERNS = {
        'logger.debug': r'logger\.debug\(',
        'logger.info': r'logger\.info\(',
        'logger.warning': r'logger\.warning\(',
        'logger.warning (alt)': r'logger\.warn\(',
        'logger.error': r'logger\.error\(',
        'logger.critical': r'logger\.critical\(',
        '_logger.debug': r'_logger\.debug\(',
        '_logger.info': r'_logger\.info\(',
        '_logger.warning': r'_logger\.warning\(',
        '_logger.error': r'_logger\.error\(',
        'print (f-string)': r'print\(f["\']',
        'formatted string (no log)': r'\.format\(',
    }
    
    def __init__(self, root_dir: str = "ipfs_datasets_py/optimizers"):
        """Initialize auditor.
        
        Args:
            root_dir: Root directory to scan
        """
        self.root_dir = Path(root_dir)
        self.results: List[LoggingAuditResult] = []
    
    def audit_file(self, file_path: Path) -> LoggingAuditResult:
        """Audit a single Python file for logging usage.
        
        Args:
            file_path: Path to Python file
            
        Returns:
            LoggingAuditResult with findings
        """
        result = LoggingAuditResult(file_path=str(file_path))
        
        try:
            with open(file_path, 'r') as f:
                content = f.read()
        except Exception as e:
            result.issues.append(f"Could not read file: {e}")
            return result
        
        lines = content.split('\n')
        
        # Check for logger initialization
        result.has_logger_init = any(
            re.search(r'logger\s*=\s*logging\.getLogger', line) or
            re.search(r'_logger\s*=\s*logging\.getLogger', line)
            for line in lines[:50]  # Check first 50 lines
        )
        
        # Count logging patterns
        for pattern_name, pattern_regex in self.LOGGING_PATTERNS.items():
            count = len(re.findall(pattern_regex, content))
            if count > 0:
                result.logging_patterns[pattern_name] = count
        
        # Extract class and method names
        class_match = re.search(r'^class\s+(\w+)', content, re.MULTILINE)
        if class_match:
            result.class_name = class_match.group(1)
        
        # Find all method definitions
        method_pattern = r'^\s{0,8}def\s+(\w+)\s*\('
        all_methods = re.findall(method_pattern, content, re.MULTILINE)
        
        # Check which methods have logging
        for method in all_methods:
            # Find the method body
            method_regex = rf'def\s+{method}\s*\([^)]*\).*?:\n(.*?)(?=\n\s{{0,8}}def\s|\nclass\s|\Z)'
            method_match = re.search(method_regex, content, re.DOTALL)
            
            if method_match:
                method_body = method_match.group(1)
                has_logging = any(
                    re.search(pattern, method_body)
                    for pattern in self.LOGGING_PATTERNS.values()
                )
                
                if has_logging:
                    result.methods_with_logging.append(method)
                elif method in self.CRITICAL_METHODS:
                    result.methods_without_logging.append(method)
        
        # Check for unstructured logging (f-strings without logger)
        fstring_count = len(re.findall(r'print\(f["\'].*?["\']', content))
        if fstring_count > 0:
            result.issues.append(f"Found {fstring_count} print(f'...') statements (should use logger)")
        
        # Check for string formatting without logger
        format_count = len(re.findall(r'f["\'][^"\']*{.*?}[^"\']*["\']', content))
        if format_count > 5:
            result.issues.append(f"Many f-strings found ({format_count}); audit for unstructured logging")
        
        # Check for missing logger init when methods exist
        if all_methods and not result.has_logger_init:
            result.issues.append("No logger initialization found but file has methods")
        
        return result
    
    def audit_directory(self) -> List[LoggingAuditResult]:
        """Scan entire optimizer directory.
        
        Returns:
            List of audit results
        """
        self.results = []
        
        for py_file in self.root_dir.rglob("*.py"):
            # Skip test files and __pycache__
            if '__pycache__' in str(py_file) or 'test_' in py_file.name:
                continue
            
            result = self.audit_file(py_file)
            self.results.append(result)
        
        return self.results
    
    def generate_report(self) -> str:
        """Generate human-readable audit report.
        
        Returns:
            Formatted report string
        """
        report_lines = [
            "# Optimizer Module Logging Audit Report",
            "",
            f"Scanned {len(self.results)} files",
            "",
            "## Summary Statistics",
            "",
        ]
        
        files_with_logger = sum(1 for r in self.results if r.has_logger_init)
        total_methods = sum(len(r.methods_with_logging) + len(r.methods_without_logging) for r in self.results)
        methods_with_logging = sum(len(r.methods_with_logging) for r in self.results)
        methods_without_logging = sum(len(r.methods_without_logging) for r in self.results)
        
        report_lines.extend([
            f"- Files with logger initialized: {files_with_logger}/{len(self.results)}",
            f"- Methods with logging: {methods_with_logging}",
            f"- Critical methods WITHOUT logging: {methods_without_logging}",
            f"- Coverage: {100*methods_with_logging/(methods_with_logging+methods_without_logging) if methods_with_logging+methods_without_logging > 0 else 0:.1f}%",
            "",
            "## Files Requiring Attention",
            "",
        ])
        
        # Files with critical methods missing logging
        for result in sorted(self.results, key=lambda r: len(r.methods_without_logging), reverse=True):
            if result.methods_without_logging or result.issues:
                report_lines.append(f"### {result.file_path}")
                
                if result.class_name:
                    report_lines.append(f"**Class**: {result.class_name}")
                report_lines.append("")
                
                if result.methods_without_logging:
                    report_lines.append(f"**Critical methods without logging**:")
                    for method in result.methods_without_logging:
                        report_lines.append(f"  - [ ] {method}()")
                    report_lines.append("")
                
                if result.issues:
                    report_lines.append(f"**Issues**:")
                    for issue in result.issues:
                        report_lines.append(f"  - {issue}")
                    report_lines.append("")
        
        # Logging patterns summary
        report_lines.extend([
            "## Logging Patterns Used",
            "",
        ])
        
        all_patterns = {}
        for result in self.results:
            for pattern, count in result.logging_patterns.items():
                all_patterns[pattern] = all_patterns.get(pattern, 0) + count
        
        for pattern, count in sorted(all_patterns.items(), key=lambda x: x[1], reverse=True):
            report_lines.append(f"- {pattern}: {count}")
        
        report_lines.extend([
            "",
            "## Recommendations",
            "",
            "1. Add logger initialization to files missing it",
            "2. Add logging to critical methods (generate, critique, optimize, validate)",
            "3. Replace print() and f-string debug code with structured logger.info()",
            "4. Use structured logging with context (session_id, round_num, etc.)",
            "5. Consider using JSON formatter for machine-readable logs",
        ])
        
        return "\n".join(report_lines)


def main():
    """Run logging audit and print report."""
    auditor = LoggingAuditor()
    auditor.audit_directory()
    report = auditor.generate_report()
    print(report)
    
    # Return results for further processing
    return auditor.results


if __name__ == "__main__":
    main()
