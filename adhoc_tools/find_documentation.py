#!/usr/bin/env python3
"""
Find all TODO.md and CHANGELOG.md files in a directory tree and report their last modification times.

This is an adhoc tool created on-the-fly by Claude Code to scan for project documentation files.
Created for: Monitoring and tracking TODO and CHANGELOG files across the project structure.

Usage:
    python find_documentation.py --directory /path/to/search
    
Examples:
    # Search current directory
    python find_documentation.py
    
    # Search specific directory with verbose output
    python find_documentation.py --directory /home/user/project --verbose
    
    # Output to file
    python find_documentation.py --output documentation_report.json
    
    # Include additional file patterns
    python find_documentation.py --patterns "*.md" "README*"
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Find TODO.md and CHANGELOG.md files with modification timestamps",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument('--directory', '-d', type=str, default='.',
                       help='Directory to search (default: current directory)')
    parser.add_argument('--output', '-o', type=str,
                       help='Output JSON file path (default: stdout)')
    parser.add_argument('--patterns', nargs='*', 
                       default=['TODO.md', 'CHANGELOG.md'],
                       help='File patterns to search for (default: TODO.md CHANGELOG.md)')
    parser.add_argument('--recursive', '-r', action='store_true', default=True,
                       help='Search recursively (default: True)')
    parser.add_argument('--include-hidden', action='store_true',
                       help='Include hidden directories (starting with .)')
    parser.add_argument('--exclude-dirs', nargs='*', 
                       default=['.git', '__pycache__', '.pytest_cache', 'node_modules'],
                       help='Directories to exclude from search')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose output')
    parser.add_argument('--format', choices=['json', 'table', 'csv'], default='json',
                       help='Output format (default: json)')
    
    return parser.parse_args()

def should_exclude_directory(dir_path: Path, exclude_dirs: List[str], include_hidden: bool) -> bool:
    """Check if a directory should be excluded from search."""
    dir_name = dir_path.name
    
    # Check if hidden directory should be excluded
    if not include_hidden and dir_name.startswith('.'):
        return True
    
    # Check explicit exclusions
    if dir_name in exclude_dirs:
        return True
        
    return False

def find_documentation_files(directory: Path, patterns: List[str], recursive: bool = True, 
                           include_hidden: bool = False, exclude_dirs: List[str] = None,
                           verbose: bool = False) -> Dict[str, Dict]:
    """
    Find documentation files matching patterns in directory tree.
    
    Returns:
        Dict mapping file paths to metadata (modification time, size, etc.)
    """
    if exclude_dirs is None:
        exclude_dirs = []
    
    found_files = {}
    
    def search_directory(current_dir: Path):
        """Recursively search directory for matching files."""
        try:
            for item in current_dir.iterdir():
                if item.is_file():
                    # Check if file matches any pattern
                    for pattern in patterns:
                        if item.match(pattern):
                            if verbose:
                                print(f"Found: {item}")
                            
                            # Get file metadata
                            stat = item.stat()
                            modification_time = datetime.fromtimestamp(stat.st_mtime)
                            
                            found_files[str(item.absolute())] = {
                                'filename': item.name,
                                'directory': str(item.parent.absolute()),
                                'size_bytes': stat.st_size,
                                'last_modified': modification_time.isoformat(),
                                'last_modified_timestamp': stat.st_mtime,
                                'relative_path': str(item.relative_to(directory))
                            }
                            break  # Don't double-count files matching multiple patterns
                
                elif item.is_dir() and recursive:
                    # Check if directory should be excluded
                    if not should_exclude_directory(item, exclude_dirs, include_hidden):
                        search_directory(item)
                        
        except PermissionError:
            if verbose:
                print(f"Permission denied: {current_dir}")
        except Exception as e:
            if verbose:
                print(f"Error accessing {current_dir}: {e}")
    
    search_directory(directory)
    return found_files

def format_output(data: Dict[str, Dict], format_type: str) -> str:
    """Format the output data according to specified format."""
    if format_type == 'json':
        return json.dumps(data, indent=2, sort_keys=True)
    
    elif format_type == 'table':
        if not data:
            return "No documentation files found."
        
        # Create table header
        output = []
        output.append("Documentation Files Report")
        output.append("=" * 50)
        output.append(f"{'File':<30} {'Last Modified':<20} {'Size':<10}")
        output.append("-" * 60)
        
        # Sort by modification time (newest first)
        sorted_files = sorted(data.items(), 
                            key=lambda x: x[1]['last_modified_timestamp'], 
                            reverse=True)
        
        for file_path, metadata in sorted_files:
            filename = metadata['relative_path']
            mod_time = metadata['last_modified'][:19]  # Remove microseconds
            size = f"{metadata['size_bytes']} B"
            output.append(f"{filename:<30} {mod_time:<20} {size:<10}")
        
        output.append("")
        output.append(f"Total files found: {len(data)}")
        return "\n".join(output)
    
    elif format_type == 'csv':
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(['file_path', 'filename', 'directory', 'relative_path', 
                        'last_modified', 'size_bytes'])
        
        # Write data rows
        for file_path, metadata in data.items():
            writer.writerow([
                file_path,
                metadata['filename'],
                metadata['directory'],
                metadata['relative_path'],
                metadata['last_modified'],
                metadata['size_bytes']
            ])
        
        return output.getvalue()

def main():
    """Main function."""
    args = parse_arguments()
    
    try:
        # Validate directory
        search_dir = Path(args.directory).resolve()
        if not search_dir.exists():
            print(f"Error: Directory '{search_dir}' does not exist", file=sys.stderr)
            sys.exit(1)
        
        if not search_dir.is_dir():
            print(f"Error: '{search_dir}' is not a directory", file=sys.stderr)
            sys.exit(1)
        
        if args.verbose:
            print(f"Searching directory: {search_dir}")
            print(f"Patterns: {args.patterns}")
            print(f"Recursive: {args.recursive}")
            print(f"Include hidden: {args.include_hidden}")
            print(f"Exclude directories: {args.exclude_dirs}")
            print("")
        
        # Find documentation files
        found_files = find_documentation_files(
            directory=search_dir,
            patterns=args.patterns,
            recursive=args.recursive,
            include_hidden=args.include_hidden,
            exclude_dirs=args.exclude_dirs,
            verbose=args.verbose
        )
        
        if args.verbose:
            print(f"\nFound {len(found_files)} documentation files")
        
        # Format output
        formatted_output = format_output(found_files, args.format)
        
        # Write output
        if args.output:
            output_path = Path(args.output)
            with open(output_path, 'w') as f:
                f.write(formatted_output)
            if args.verbose:
                print(f"Results written to: {output_path}")
        else:
            print(formatted_output)
        
        # Summary for verbose mode
        if args.verbose and found_files:
            print(f"\nSummary:")
            print(f"  Total files: {len(found_files)}")
            
            # Find most recently modified
            most_recent = max(found_files.items(), 
                            key=lambda x: x[1]['last_modified_timestamp'])
            print(f"  Most recent: {most_recent[1]['relative_path']} ({most_recent[1]['last_modified'][:19]})")
            
            # Find oldest
            oldest = min(found_files.items(), 
                        key=lambda x: x[1]['last_modified_timestamp'])
            print(f"  Oldest: {oldest[1]['relative_path']} ({oldest[1]['last_modified'][:19]})")
        
    except KeyboardInterrupt:
        print("\nOperation cancelled by user", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()