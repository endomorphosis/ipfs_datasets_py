#!/usr/bin/env python3
"""
Stub File Analysis Tool - Worker 177

Cross-references existing stub files with docstring audit results to identify
which files have stubs and which still need comprehensive documentation.
"""

import argparse
import json
import os
from pathlib import Path
from typing import Dict, List, Set, Tuple


def find_stub_files(root_dir: Path) -> Dict[str, List[str]]:
    """
    Find all existing stub files and map them to their source files.
    
    Args:
        root_dir: Root directory to search
        
    Returns:
        Dictionary mapping source file paths to list of stub files
    """
    stub_files = {}
    
    # Find all stub files
    for stub_file in root_dir.rglob("*_stubs.md"):
        stub_path = str(stub_file)
        
        # Try to infer the source file from stub file name
        stub_name = stub_file.stem  # e.g., "audit_logger_stubs"
        source_name = stub_name.replace("_stubs", "")  # e.g., "audit_logger"
        
        # Look for the source file in the same directory or parent directories
        search_dirs = [stub_file.parent]
        if "tests/" in str(stub_file):
            # For test stubs, look in the main source tree
            main_source_dir = root_dir / "ipfs_datasets_py"
            search_dirs.append(main_source_dir)
            # Add subdirectories that match the test structure
            relative_path = stub_file.relative_to(root_dir / "tests")
            possible_source = main_source_dir
            for part in relative_path.parts[:-1]:  # Skip the filename
                if not part.endswith("_"):
                    possible_source = possible_source / part.rstrip("_")
            search_dirs.append(possible_source)
        
        found_source = None
        for search_dir in search_dirs:
            potential_sources = [
                search_dir / f"{source_name}.py",
                search_dir / "__init__.py" if source_name.endswith("_init") else None,
            ]
            
            for potential in potential_sources:
                if potential and potential.exists():
                    found_source = str(potential)
                    break
            
            if found_source:
                break
        
        if found_source:
            if found_source not in stub_files:
                stub_files[found_source] = []
            stub_files[found_source].append(stub_path)
        else:
            # Store unmapped stub files with a special key
            unmapped_key = f"UNMAPPED: {stub_path}"
            stub_files[unmapped_key] = [stub_path]
    
    return stub_files


def analyze_stub_coverage(audit_report_path: Path, root_dir: Path) -> Dict[str, any]:
    """
    Analyze which files have stubs vs which need documentation work.
    
    Args:
        audit_report_path: Path to the docstring audit report JSON
        root_dir: Root directory of the project
        
    Returns:
        Analysis results dictionary
    """
    # Load the audit report
    with open(audit_report_path, 'r') as f:
        audit_data = json.load(f)
    
    # Find existing stub files
    stub_files = find_stub_files(root_dir)
    
    # Create normalized path mappings
    def normalize_path(path_str):
        """Normalize paths for comparison"""
        path = Path(path_str)
        if path.is_absolute():
            try:
                return str(path.relative_to(root_dir))
            except ValueError:
                return str(path)
        return str(path)
    
    # Map audit files to normalized paths
    files_needing_work = []
    files_comprehensive = []
    
    for file_info in audit_data["files_by_status"]["needs_enhancement"]:
        normalized = normalize_path(file_info["file_path"])
        files_needing_work.append((normalized, file_info))
    
    for file_info in audit_data["files_by_status"]["comprehensive"]:
        normalized = normalize_path(file_info["file_path"])
        files_comprehensive.append((normalized, file_info))
    
    # Normalize stub file paths
    normalized_stub_files = {}
    for source_path, stub_list in stub_files.items():
        if not source_path.startswith("UNMAPPED:"):
            normalized_source = normalize_path(source_path)
            normalized_stub_files[normalized_source] = stub_list
        else:
            normalized_stub_files[source_path] = stub_list
    
    # Analyze coverage
    analysis = {
        "summary": {
            "total_files_needing_work": len(files_needing_work),
            "files_with_stubs": 0,
            "files_without_stubs": 0,
            "unmapped_stubs": 0,
            "total_stub_files": len([f for files in stub_files.values() for f in files])
        },
        "files_with_stubs_but_need_work": [],
        "files_without_stubs_need_work": [],
        "comprehensive_files_with_stubs": [],
        "unmapped_stub_files": [],
        "stub_file_mapping": normalized_stub_files
    }
    
    # Check which files needing work have stubs
    for normalized_path, file_info in files_needing_work:
        if normalized_path in normalized_stub_files:
            analysis["files_with_stubs_but_need_work"].append({
                "file_path": normalized_path,
                "stub_files": normalized_stub_files[normalized_path],
                "audit_info": file_info
            })
            analysis["summary"]["files_with_stubs"] += 1
        else:
            analysis["files_without_stubs_need_work"].append({
                "file_path": normalized_path,
                "audit_info": file_info
            })
            analysis["summary"]["files_without_stubs"] += 1
    
    # Check comprehensive files with stubs
    for normalized_path, file_info in files_comprehensive:
        if normalized_path in normalized_stub_files:
            analysis["comprehensive_files_with_stubs"].append({
                "file_path": normalized_path,
                "stub_files": normalized_stub_files[normalized_path],
                "audit_info": file_info
            })
    
    # Find unmapped stub files
    for source_path, stub_list in stub_files.items():
        if source_path.startswith("UNMAPPED:"):
            analysis["unmapped_stub_files"].extend(stub_list)
            analysis["summary"]["unmapped_stubs"] += len(stub_list)
    
    return analysis


def main():
    """Main function for stub file analysis."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze stub file coverage vs docstring audit")
    parser.add_argument('--audit-report', '-a', default='docstring_audit_report.json',
                       help='Path to docstring audit report JSON')
    parser.add_argument('--root-dir', '-r', default='.',
                       help='Root directory of the project')
    parser.add_argument('--output', '-o', help='Output file for analysis results (JSON)')
    parser.add_argument('--show-mappings', action='store_true',
                       help='Show detailed stub file mappings')
    
    args = parser.parse_args()
    
    root_dir = Path(args.root_dir).resolve()
    audit_report_path = Path(args.audit_report)
    
    if not audit_report_path.exists():
        print(f"Error: Audit report not found: {audit_report_path}")
        return 1
    
    print("Analyzing stub file coverage...")
    analysis = analyze_stub_coverage(audit_report_path, root_dir)
    
    # Print summary
    print("\n" + "="*60)
    print("STUB FILE COVERAGE ANALYSIS - Worker 177")
    print("="*60)
    
    summary = analysis["summary"]
    print(f"Total files needing documentation work: {summary['total_files_needing_work']}")
    print(f"Files with existing stubs: {summary['files_with_stubs']}")
    print(f"Files without stubs: {summary['files_without_stubs']}")
    print(f"Total stub files found: {summary['total_stub_files']}")
    print(f"Unmapped stub files: {summary['unmapped_stubs']}")
    
    if summary['total_files_needing_work'] > 0:
        coverage_percent = (summary['files_with_stubs'] / summary['total_files_needing_work']) * 100
        print(f"Stub coverage: {coverage_percent:.1f}%")
    
    # Show files that have stubs but still need work
    if analysis["files_with_stubs_but_need_work"]:
        print(f"\n📋 FILES WITH STUBS THAT STILL NEED DOCSTRING WORK ({len(analysis['files_with_stubs_but_need_work'])}):")
        print("-" * 60)
        for item in analysis["files_with_stubs_but_need_work"][:10]:  # Show first 10
            print(f"  📄 {item['file_path']}")
            for stub in item['stub_files']:
                print(f"    📝 {Path(stub).name}")
            audit = item['audit_info']
            total_items = audit.get('total_classes', 0) + audit.get('total_functions', 0)
            comprehensive_items = audit.get('comprehensive_classes', 0) + audit.get('comprehensive_functions', 0)
            if total_items > 0:
                completion = (comprehensive_items / total_items) * 100
                print(f"    📊 Documentation: {completion:.0f}% comprehensive ({comprehensive_items}/{total_items})")
            print()
        
        if len(analysis["files_with_stubs_but_need_work"]) > 10:
            print(f"    ... and {len(analysis['files_with_stubs_but_need_work']) - 10} more files")
    
    # Show high-priority files without stubs
    if analysis["files_without_stubs_need_work"]:
        print(f"\n❌ HIGH-PRIORITY FILES WITHOUT STUBS ({len(analysis['files_without_stubs_need_work'])}):")
        print("-" * 60)
        
        # Sort by number of classes + functions to prioritize
        priority_files = []
        for item in analysis["files_without_stubs_need_work"]:
            audit = item['audit_info']
            total_items = audit.get('total_classes', 0) + audit.get('total_functions', 0)
            priority_files.append((total_items, item))
        
        priority_files.sort(key=lambda x: x[0], reverse=True)  # Highest priority first
        
        for total_items, item in priority_files[:15]:  # Show top 15
            if total_items > 0:  # Only show files with actual content
                print(f"  📄 {item['file_path']}")
                audit = item['audit_info']
                print(f"    📊 {audit.get('total_classes', 0)} classes, {audit.get('total_functions', 0)} functions")
                comprehensive_items = audit.get('comprehensive_classes', 0) + audit.get('comprehensive_functions', 0)
                completion = (comprehensive_items / total_items) * 100 if total_items > 0 else 0
                print(f"    📊 Documentation: {completion:.0f}% comprehensive")
                print()
    
    # Show unmapped stub files
    if analysis["unmapped_stub_files"]:
        print(f"\n🔍 UNMAPPED STUB FILES ({len(analysis['unmapped_stub_files'])}):")
        print("-" * 60)
        for stub_file in analysis["unmapped_stub_files"]:
            print(f"  📝 {stub_file}")
    
    # Show mapping details if requested
    if args.show_mappings:
        print(f"\n🗂️  STUB FILE MAPPINGS:")
        print("-" * 60)
        for source_path, stub_list in analysis["stub_file_mapping"].items():
            if not source_path.startswith("UNMAPPED:"):
                print(f"  📄 {source_path}")
                for stub in stub_list:
                    print(f"    📝 {stub}")
                print()
    
    # Save detailed analysis if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(analysis, f, indent=2, default=str)
        print(f"\nDetailed analysis saved to: {args.output}")
    
    return 0


if __name__ == "__main__":
    exit(main())
