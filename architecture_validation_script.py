#!/usr/bin/env python3
"""
Architecture Validation Script for Phase 2

Validates that all MCP tools follow the thin wrapper pattern and architectural best practices.
Scans all tool files and generates comprehensive compliance reports.
"""

import ast
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional


@dataclass
class ToolAnalysis:
    """Analysis results for a single tool file."""
    file_path: str
    category: str
    line_count: int
    has_core_imports: bool
    core_modules_used: List[str]
    has_docstring: bool
    docstring_mentions_core: bool
    has_error_handling: bool
    complexity_score: float
    compliance_issues: List[str]
    compliance_level: str  # "exemplary", "compliant", "needs_review", "needs_refactoring"


class ArchitectureValidator:
    """Validates MCP tool architecture compliance."""

    def __init__(self, tools_dir: str = "ipfs_datasets_py/mcp_server/tools"):
        self.tools_dir = Path(tools_dir)
        self.results: List[ToolAnalysis] = []
        
        # Compliance thresholds
        self.IDEAL_LINE_COUNT = 100
        self.ACCEPTABLE_LINE_COUNT = 150
        self.MAX_LINE_COUNT = 200
        
        # Expected core module patterns
        self.core_module_patterns = [
            r'ipfs_datasets_py\.',
            r'from ipfs_datasets_py',
        ]
        
        # Complexity indicators
        self.complexity_keywords = [
            'for ', 'while ', 'if ', 'else:', 'elif ',
            'try:', 'except:', 'with ', 'class ', 'def '
        ]

    def scan_all_tools(self) -> List[ToolAnalysis]:
        """Scan all tool files and analyze them."""
        tool_files = list(self.tools_dir.rglob("*.py"))
        
        # Filter out __init__.py and test files
        tool_files = [
            f for f in tool_files
            if f.name != "__init__.py" and "test" not in f.name.lower()
        ]
        
        print(f"Scanning {len(tool_files)} tool files...")
        
        for tool_file in tool_files:
            try:
                analysis = self.analyze_tool_file(tool_file)
                self.results.append(analysis)
            except Exception as e:
                print(f"Error analyzing {tool_file}: {e}")
        
        return self.results

    def analyze_tool_file(self, file_path: Path) -> ToolAnalysis:
        """Analyze a single tool file for compliance."""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Get category from directory structure
        relative_path = file_path.relative_to(self.tools_dir)
        category = relative_path.parts[0] if len(relative_path.parts) > 1 else "root"
        
        # Basic metrics
        lines = content.split('\n')
        line_count = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
        
        # Check for core module imports
        has_core_imports, core_modules = self.check_core_imports(content)
        
        # Check docstring
        has_docstring, docstring_mentions_core = self.check_docstring(content)
        
        # Check error handling
        has_error_handling = self.check_error_handling(content)
        
        # Calculate complexity score
        complexity_score = self.calculate_complexity(content)
        
        # Determine compliance issues
        compliance_issues = self.identify_compliance_issues(
            line_count, has_core_imports, has_docstring, 
            docstring_mentions_core, has_error_handling, complexity_score
        )
        
        # Determine compliance level
        compliance_level = self.determine_compliance_level(line_count, compliance_issues)
        
        return ToolAnalysis(
            file_path=str(file_path),
            category=category,
            line_count=line_count,
            has_core_imports=has_core_imports,
            core_modules_used=core_modules,
            has_docstring=has_docstring,
            docstring_mentions_core=docstring_mentions_core,
            has_error_handling=has_error_handling,
            complexity_score=complexity_score,
            compliance_issues=compliance_issues,
            compliance_level=compliance_level
        )

    def check_core_imports(self, content: str) -> Tuple[bool, List[str]]:
        """Check if file imports from core modules."""
        core_modules = []
        has_core_imports = False
        
        for pattern in self.core_module_patterns:
            matches = re.findall(pattern + r'[\w.]+', content)
            if matches:
                has_core_imports = True
                core_modules.extend(matches)
        
        return has_core_imports, list(set(core_modules))

    def check_docstring(self, content: str) -> Tuple[bool, bool]:
        """Check for module docstring and if it mentions core modules."""
        try:
            tree = ast.parse(content)
            docstring = ast.get_docstring(tree)
            
            if docstring:
                mentions_core = any(
                    keyword in docstring.lower() 
                    for keyword in ['core', 'wrapper', 'delegates', 'uses']
                )
                return True, mentions_core
            return False, False
        except:
            return False, False

    def check_error_handling(self, content: str) -> bool:
        """Check if file has proper error handling."""
        has_try_except = 'try:' in content and 'except' in content
        has_raise = 'raise' in content
        return has_try_except or has_raise

    def calculate_complexity(self, content: str) -> float:
        """Calculate code complexity score (0-100)."""
        # Count complexity indicators
        complexity_count = sum(content.count(kw) for kw in self.complexity_keywords)
        
        # Normalize by line count
        lines = len(content.split('\n'))
        if lines == 0:
            return 0.0
        
        # Score: fewer indicators per line = lower complexity (better)
        score = (complexity_count / lines) * 100
        return min(score, 100.0)

    def identify_compliance_issues(
        self, line_count: int, has_core_imports: bool, 
        has_docstring: bool, docstring_mentions_core: bool,
        has_error_handling: bool, complexity_score: float
    ) -> List[str]:
        """Identify compliance issues."""
        issues = []
        
        if line_count > self.MAX_LINE_COUNT:
            issues.append(f"Exceeds maximum line count ({line_count} > {self.MAX_LINE_COUNT})")
        elif line_count > self.ACCEPTABLE_LINE_COUNT:
            issues.append(f"Exceeds acceptable line count ({line_count} > {self.ACCEPTABLE_LINE_COUNT})")
        
        if not has_core_imports:
            issues.append("Missing imports from core modules (ipfs_datasets_py.*)")
        
        if not has_docstring:
            issues.append("Missing module docstring")
        elif not docstring_mentions_core:
            issues.append("Docstring doesn't explain core module usage")
        
        if not has_error_handling:
            issues.append("Missing error handling (try/except or raise)")
        
        if complexity_score > 30:
            issues.append(f"High complexity score ({complexity_score:.1f} > 30)")
        
        return issues

    def determine_compliance_level(self, line_count: int, issues: List[str]) -> str:
        """Determine overall compliance level."""
        if not issues and line_count <= self.IDEAL_LINE_COUNT:
            return "exemplary"
        elif len(issues) <= 1 and line_count <= self.ACCEPTABLE_LINE_COUNT:
            return "compliant"
        elif line_count <= self.MAX_LINE_COUNT:
            return "needs_review"
        else:
            return "needs_refactoring"

    def generate_report(self) -> Dict:
        """Generate comprehensive compliance report."""
        total_tools = len(self.results)
        
        # Count by compliance level
        compliance_counts = defaultdict(int)
        for result in self.results:
            compliance_counts[result.compliance_level] += 1
        
        # Tools by category
        category_stats = defaultdict(lambda: {"total": 0, "compliant": 0})
        for result in self.results:
            category_stats[result.category]["total"] += 1
            if result.compliance_level in ["exemplary", "compliant"]:
                category_stats[result.category]["compliant"] += 1
        
        # Top issues
        all_issues = []
        for result in self.results:
            all_issues.extend(result.compliance_issues)
        
        issue_counts = defaultdict(int)
        for issue in all_issues:
            # Normalize issue text
            normalized = re.sub(r'\(.*?\)', '', issue).strip()
            issue_counts[normalized] += 1
        
        # Top thick tools (most lines)
        thick_tools = sorted(
            [r for r in self.results if r.line_count > self.ACCEPTABLE_LINE_COUNT],
            key=lambda x: x.line_count,
            reverse=True
        )[:20]
        
        # Exemplary thin tools
        exemplary_tools = sorted(
            [r for r in self.results if r.compliance_level == "exemplary"],
            key=lambda x: x.line_count
        )[:10]
        
        # Calculate overall compliance score
        compliant_count = compliance_counts["exemplary"] + compliance_counts["compliant"]
        compliance_score = (compliant_count / total_tools * 100) if total_tools > 0 else 0
        
        return {
            "summary": {
                "total_tools": total_tools,
                "compliance_score": round(compliance_score, 2),
                "by_level": dict(compliance_counts),
                "compliant_count": compliant_count,
                "needs_attention_count": total_tools - compliant_count
            },
            "category_statistics": dict(category_stats),
            "top_issues": [
                {"issue": issue, "count": count}
                for issue, count in sorted(
                    issue_counts.items(), key=lambda x: x[1], reverse=True
                )[:10]
            ],
            "thick_tools": [
                {
                    "file": t.file_path,
                    "category": t.category,
                    "lines": t.line_count,
                    "issues": t.compliance_issues
                }
                for t in thick_tools
            ],
            "exemplary_tools": [
                {
                    "file": t.file_path,
                    "category": t.category,
                    "lines": t.line_count,
                    "core_modules": t.core_modules_used[:3]
                }
                for t in exemplary_tools
            ]
        }

    def save_reports(self, output_dir: str = "."):
        """Save JSON and human-readable reports."""
        output_path = Path(output_dir)
        
        # Generate report data
        report = self.generate_report()
        
        # Save JSON report
        json_file = output_path / "architecture_validation_report.json"
        with open(json_file, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"✓ JSON report saved to {json_file}")
        
        # Save detailed results
        detailed_file = output_path / "architecture_validation_detailed.json"
        with open(detailed_file, 'w') as f:
            json.dump([asdict(r) for r in self.results], f, indent=2)
        print(f"✓ Detailed results saved to {detailed_file}")
        
        # Generate human-readable summary
        self.print_summary(report)
        
        return report

    def print_summary(self, report: Dict):
        """Print human-readable summary."""
        print("\n" + "="*80)
        print("ARCHITECTURE VALIDATION REPORT - PHASE 2")
        print("="*80)
        
        summary = report["summary"]
        print(f"\n📊 OVERALL STATISTICS")
        print(f"   Total tools analyzed: {summary['total_tools']}")
        print(f"   Compliance score: {summary['compliance_score']:.1f}%")
        print(f"   ✓ Compliant: {summary['compliant_count']}")
        print(f"   ⚠ Needs attention: {summary['needs_attention_count']}")
        
        print(f"\n📈 COMPLIANCE BREAKDOWN")
        for level, count in summary['by_level'].items():
            percentage = (count / summary['total_tools'] * 100)
            icon = {"exemplary": "⭐", "compliant": "✓", "needs_review": "⚠", "needs_refactoring": "❌"}.get(level, "•")
            print(f"   {icon} {level.replace('_', ' ').title()}: {count} ({percentage:.1f}%)")
        
        print(f"\n🔝 TOP 10 ISSUES")
        for i, issue_data in enumerate(report['top_issues'][:10], 1):
            print(f"   {i}. {issue_data['issue']} ({issue_data['count']} tools)")
        
        print(f"\n❌ TOP 10 THICK TOOLS (Need Refactoring)")
        for i, tool in enumerate(report['thick_tools'][:10], 1):
            filename = Path(tool['file']).name
            print(f"   {i}. {filename} ({tool['lines']} lines)")
            if tool['issues']:
                print(f"      Issues: {', '.join(tool['issues'][:2])}")
        
        print(f"\n⭐ TOP 10 EXEMPLARY THIN WRAPPERS")
        for i, tool in enumerate(report['exemplary_tools'][:10], 1):
            filename = Path(tool['file']).name
            modules = ', '.join([m.split('.')[-1] for m in tool['core_modules'][:2]]) if tool['core_modules'] else 'N/A'
            print(f"   {i}. {filename} ({tool['lines']} lines) - Uses: {modules}")
        
        print("\n" + "="*80)


def main():
    """Run architecture validation."""
    validator = ArchitectureValidator()
    
    print("🔍 Starting architecture validation for Phase 2...")
    print("   Scanning ipfs_datasets_py/mcp_server/tools/")
    print()
    
    # Scan all tools
    validator.scan_all_tools()
    
    # Generate and save reports
    report = validator.save_reports()
    
    # Exit code based on compliance score
    compliance_score = report["summary"]["compliance_score"]
    if compliance_score >= 80:
        print(f"\n✅ Architecture validation PASSED (score: {compliance_score:.1f}%)")
        return 0
    elif compliance_score >= 60:
        print(f"\n⚠️  Architecture validation MARGINAL (score: {compliance_score:.1f}%)")
        print("   Some tools need attention but overall architecture is acceptable.")
        return 0
    else:
        print(f"\n❌ Architecture validation NEEDS WORK (score: {compliance_score:.1f}%)")
        print("   Significant refactoring needed to meet thin wrapper standards.")
        return 1


if __name__ == "__main__":
    exit(main())
