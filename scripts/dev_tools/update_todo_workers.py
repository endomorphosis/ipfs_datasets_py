#!/usr/bin/env python3
"""
Update existing TODO.md files with worker assignments.

This is an adhoc tool created on-the-fly by Claude Code to handle worker assignment updates.
Created for: Adding worker assignments to existing TODO files after splitting.

Usage:
    python update_todo_workers.py --base-dir /path/to/ipfs_datasets_py
    
Examples:
    # Basic usage with default settings
    python update_todo_workers.py
    
    # With custom base directory
    python update_todo_workers.py --base-dir /custom/path/ipfs_datasets_py
    
    # With verbose output
    python update_todo_workers.py --verbose
"""

import argparse
import sys
from pathlib import Path

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Update existing TODO.md files with worker assignments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument('--base-dir', type=str,
                       default='/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py',
                       help='Base directory containing subdirectories (default: %(default)s)')
    parser.add_argument('--assignments-file', type=str,
                       help='JSON file with custom worker assignments (optional)')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose output')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be done without making changes')
    
    return parser.parse_args()

def get_default_worker_assignments():
    """Get the default worker assignments."""
    return {
        'audit': 70,
        'config': 74,
        'embeddings': 66,
        'ipfs_embeddings_py': 72,
        'ipld': 62,
        'llm': 68,
        'logic_integration': 75,
        'mcp_tools': 71,
        'multimedia': 69,
        'optimizers': 65,
        'rag': 64,
        'search': 67,
        'utils': 61,
        'vector_stores': 63,
        'wikipedia_x': 73
    }

def main():
    args = parse_arguments()
    
    try:
        # Use default worker assignments (could be extended to load from file)
        worker_assignments = get_default_worker_assignments()
        base_dir = Path(args.base_dir)
        
        if not base_dir.exists():
            print(f"Error: Base directory {base_dir} does not exist", file=sys.stderr)
            sys.exit(1)
        
        if args.verbose:
            print(f"Processing TODO.md files in: {base_dir}")
            print(f"Worker assignments: {worker_assignments}")
            
        updated_count = 0
        skipped_count = 0
        
        for subdir, worker_id in worker_assignments.items():
            todo_path = base_dir / subdir / 'TODO.md'
            
            if not todo_path.exists():
                if args.verbose:
                    print(f"Skipping {subdir}: TODO.md does not exist")
                skipped_count += 1
                continue
            
            # Read existing content
            with open(todo_path, 'r') as f:
                content = f.read()
            
            # Check if worker assignment already exists
            if "## Worker Assignment" in content:
                if args.verbose:
                    print(f"Worker assignment already exists in {subdir}/TODO.md")
                skipped_count += 1
                continue
            
            # Add worker assignment after the title
            lines = content.split('\n')
            new_lines = []
            
            for i, line in enumerate(lines):
                new_lines.append(line)
                
                # Add worker assignment after the title
                if line.startswith(f"# TODO List for {subdir}/"):
                    new_lines.append("")
                    new_lines.append("## Worker Assignment")
                    new_lines.append(f"**Worker {worker_id}**: Complete TDD tasks for {subdir}/ directory")
            
            # Write updated content (unless dry run)
            if not args.dry_run:
                with open(todo_path, 'w') as f:
                    f.write('\n'.join(new_lines))
                print(f"Updated {subdir}/TODO.md with Worker {worker_id} assignment")
            else:
                print(f"[DRY RUN] Would update {subdir}/TODO.md with Worker {worker_id} assignment")
            
            updated_count += 1
        
        # Summary
        if args.verbose or args.dry_run:
            print(f"\nSummary:")
            print(f"  Updated: {updated_count}")
            print(f"  Skipped: {skipped_count}")
            if args.dry_run:
                print("  (No changes made - dry run mode)")
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()