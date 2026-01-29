#!/usr/bin/env python3
"""
Docstring Audit Tool - Worker 177

Analyzes the current state of docstring documentation across the ipfs_datasets_py codebase
to identify what has been completed and what still needs comprehensive documentation.
"""

import os
import ast
import json
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict


def analyze_docstring_quality(docstring: str) -> Dict[str, Any]:
    """
    Analyze the quality and completeness of a docstring.
    
    Args:
        docstring: The docstring to analyze
        
    Returns:
        Dictionary with quality metrics and completeness indicators
    """
    if not docstring:
        return {
            'has_docstring': False,
            'quality_score': 0,
            'sections': [],
            'is_comprehensive': False,
            'needs_enhancement': True
        }
    
    docstring = docstring.strip()
    lines = docstring.split('\n')
    
    # Look for comprehensive docstring indicators
    has_args = any('Args:' in line or 'Arguments:' in line or 'Parameters:' in line for line in lines)
    has_returns = any('Returns:' in line or 'Return:' in line for line in lines)
    has_raises = any('Raises:' in line or 'Exceptions:' in line for line in lines)
    has_examples = any('Examples:' in line or 'Example:' in line for line in lines)
    has_notes = any('Notes:' in line or 'Note:' in line for line in lines)
    
    # Check for comprehensive format indicators
    comprehensive_indicators = [
        'comprehensive', 'enterprise-grade', 'distributed', 'IPFS', 
        'content-addressable', 'metadata management', 'batch processing'
    ]
    has_comprehensive_language = any(indicator.lower() in docstring.lower() 
                                   for indicator in comprehensive_indicators)
    
    # Calculate quality score
    quality_score = 0
    sections = []
    
    if len(docstring) > 50:
        quality_score += 20
    if len(docstring) > 200:
        quality_score += 20
    if has_args:
        quality_score += 20
        sections.append('Args')
    if has_returns:
        quality_score += 15
        sections.append('Returns')
    if has_raises:
        quality_score += 10
        sections.append('Raises')
    if has_examples:
        quality_score += 10
        sections.append('Examples')
    if has_notes:
        quality_score += 5
        sections.append('Notes')
    if has_comprehensive_language:
        quality_score += 10
    
    # Determine if comprehensive
    is_comprehensive = (
        quality_score >= 80 and 
        len(docstring) > 500 and
        has_args and has_returns and has_examples
    )
    
    return {
        'has_docstring': True,
        'quality_score': min(quality_score, 100),
        'sections': sections,
        'is_comprehensive': is_comprehensive,
        'needs_enhancement': quality_score < 80,
        'length': len(docstring),
        'has_comprehensive_language': has_comprehensive_language
    }


def extract_file_info(file_path: Path) -> Dict[str, Any]:
    """
    Extract information about classes and functions in a Python file.
    
    Args:
        file_path: Path to the Python file
        
    Returns:
        Dictionary with file analysis results
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        tree = ast.parse(content)
        
        file_info = {
            'file_path': str(file_path),
            'classes': [],
            'functions': [],
            'module_docstring': None,
            'total_classes': 0,
            'total_functions': 0,
            'comprehensive_classes': 0,
            'comprehensive_functions': 0,
            'needs_work': False
        }
        
        # Check module docstring
        if (tree.body and isinstance(tree.body[0], ast.Expr) 
            and isinstance(tree.body[0].value, ast.Constant)):
            module_docstring = tree.body[0].value.value
            file_info['module_docstring'] = analyze_docstring_quality(module_docstring)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                docstring = ast.get_docstring(node)
                quality = analyze_docstring_quality(docstring)
                
                class_info = {
                    'name': node.name,
                    'line': node.lineno,
                    'docstring_quality': quality,
                    'methods': []
                }
                
                # Analyze methods
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        method_docstring = ast.get_docstring(item)
                        method_quality = analyze_docstring_quality(method_docstring)
                        
                        class_info['methods'].append({
                            'name': item.name,
                            'line': item.lineno,
                            'is_public': not item.name.startswith('_'),
                            'docstring_quality': method_quality
                        })
                
                file_info['classes'].append(class_info)
                file_info['total_classes'] += 1
                if quality['is_comprehensive']:
                    file_info['comprehensive_classes'] += 1
                    
            elif isinstance(node, ast.FunctionDef) and node.col_offset == 0:
                # Top-level function
                docstring = ast.get_docstring(node)
                quality = analyze_docstring_quality(docstring)
                
                function_info = {
                    'name': node.name,
                    'line': node.lineno,
                    'is_public': not node.name.startswith('_'),
                    'docstring_quality': quality
                }
                
                file_info['functions'].append(function_info)
                file_info['total_functions'] += 1
                if quality['is_comprehensive']:
                    file_info['comprehensive_functions'] += 1
        
        # Determine if file needs work
        total_items = file_info['total_classes'] + file_info['total_functions']
        comprehensive_items = file_info['comprehensive_classes'] + file_info['comprehensive_functions']
        
        if total_items > 0:
            comprehensive_ratio = comprehensive_items / total_items
            file_info['needs_work'] = comprehensive_ratio < 0.8
        
        return file_info
        
    except Exception as e:
        return {
            'file_path': str(file_path),
            'error': str(e),
            'needs_work': True
        }


def scan_directory(directory: Path) -> List[Dict[str, Any]]:
    """
    Scan a directory for Python files and analyze their docstrings.
    
    Args:
        directory: Directory to scan
        
    Returns:
        List of file analysis results
    """
    results = []
    
    for py_file in directory.rglob("*.py"):
        # Skip test files and __pycache__
        if '__pycache__' in str(py_file) or 'test_' in py_file.name:
            continue
            
        file_info = extract_file_info(py_file)
        results.append(file_info)
    
    return results


def generate_report(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generate a comprehensive report of docstring status.
    
    Args:
        results: List of file analysis results
        
    Returns:
        Summary report dictionary
    """
    report = {
        'summary': {
            'total_files': len(results),
            'files_needing_work': 0,
            'files_comprehensive': 0,
            'total_classes': 0,
            'comprehensive_classes': 0,
            'total_functions': 0,
            'comprehensive_functions': 0
        },
        'files_by_status': {
            'comprehensive': [],
            'needs_enhancement': [],
            'errors': []
        },
        'recommendations': []
    }
    
    for file_info in results:
        if 'error' in file_info:
            report['files_by_status']['errors'].append(file_info)
            continue
            
        if file_info['needs_work']:
            report['summary']['files_needing_work'] += 1
            report['files_by_status']['needs_enhancement'].append(file_info)
        else:
            report['summary']['files_comprehensive'] += 1
            report['files_by_status']['comprehensive'].append(file_info)
        
        report['summary']['total_classes'] += file_info['total_classes']
        report['summary']['comprehensive_classes'] += file_info['comprehensive_classes']
        report['summary']['total_functions'] += file_info['total_functions']
        report['summary']['comprehensive_functions'] += file_info['comprehensive_functions']
    
    # Generate recommendations
    if report['summary']['files_needing_work'] > 0:
        report['recommendations'].append(
            f"Priority: {report['summary']['files_needing_work']} files need docstring enhancement"
        )
    
    if report['summary']['total_classes'] > report['summary']['comprehensive_classes']:
        missing_classes = report['summary']['total_classes'] - report['summary']['comprehensive_classes']
        report['recommendations'].append(
            f"Classes: {missing_classes} classes need comprehensive docstrings"
        )
    
    if report['summary']['total_functions'] > report['summary']['comprehensive_functions']:
        missing_functions = report['summary']['total_functions'] - report['summary']['comprehensive_functions']
        report['recommendations'].append(
            f"Functions: {missing_functions} functions need comprehensive docstrings"
        )
    
    return report


def main():
    """Main function for docstring audit tool."""
    parser = argparse.ArgumentParser(description="Audit docstring documentation status")
    parser.add_argument('--directory', '-d', default='ipfs_datasets_py',
                       help='Directory to scan (default: ipfs_datasets_py)')
    parser.add_argument('--output', '-o', help='Output file for detailed report (JSON)')
    parser.add_argument('--summary-only', action='store_true',
                       help='Show only summary statistics')
    parser.add_argument('--priority-files', action='store_true',
                       help='Show only files that need work')
    
    args = parser.parse_args()
    
    # Scan directory
    directory = Path(args.directory)
    if not directory.exists():
        print(f"Error: Directory {directory} not found")
        return 1
    
    print(f"Scanning {directory} for Python files...")
    results = scan_directory(directory)
    
    # Generate report
    report = generate_report(results)
    
    # Print summary
    print("\n" + "="*60)
    print("DOCSTRING AUDIT SUMMARY - Worker 177")
    print("="*60)
    
    summary = report['summary']
    print(f"Total files analyzed: {summary['total_files']}")
    print(f"Files with comprehensive docs: {summary['files_comprehensive']}")
    print(f"Files needing enhancement: {summary['files_needing_work']}")
    print(f"Total classes: {summary['total_classes']}")
    print(f"Comprehensive classes: {summary['comprehensive_classes']}")
    print(f"Total functions: {summary['total_functions']}")
    print(f"Comprehensive functions: {summary['comprehensive_functions']}")
    
    if summary['total_classes'] > 0:
        class_percentage = (summary['comprehensive_classes'] / summary['total_classes']) * 100
        print(f"Class documentation: {class_percentage:.1f}% comprehensive")
    
    if summary['total_functions'] > 0:
        function_percentage = (summary['comprehensive_functions'] / summary['total_functions']) * 100
        print(f"Function documentation: {function_percentage:.1f}% comprehensive")
    
    # Print recommendations
    if report['recommendations']:
        print("\nRECOMMENDATIONS:")
        for rec in report['recommendations']:
            print(f"  • {rec}")
    
    # Show priority files if requested
    if args.priority_files or not args.summary_only:
        print("\n" + "="*60)
        print("FILES NEEDING ENHANCEMENT:")
        print("="*60)
        
        for file_info in report['files_by_status']['needs_enhancement']:
            rel_path = file_info['file_path'].replace(str(directory) + '/', '')
            print(f"\n📄 {rel_path}")
            
            if file_info['total_classes'] > 0:
                comprehensive_classes = file_info['comprehensive_classes']
                total_classes = file_info['total_classes']
                print(f"  Classes: {comprehensive_classes}/{total_classes} comprehensive")
                
                for class_info in file_info['classes']:
                    status = "✅" if class_info['docstring_quality']['is_comprehensive'] else "❌"
                    print(f"    {status} {class_info['name']} (line {class_info['line']})")
            
            if file_info['total_functions'] > 0:
                comprehensive_functions = file_info['comprehensive_functions']
                total_functions = file_info['total_functions']
                print(f"  Functions: {comprehensive_functions}/{total_functions} comprehensive")
                
                for func_info in file_info['functions']:
                    if func_info['is_public']:  # Only show public functions
                        status = "✅" if func_info['docstring_quality']['is_comprehensive'] else "❌"
                        print(f"    {status} {func_info['name']} (line {func_info['line']})")
    
    # Save detailed report if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nDetailed report saved to: {args.output}")
    
    # Return appropriate exit code
    return 0 if summary['files_needing_work'] == 0 else 1


if __name__ == "__main__":
    exit(main())
