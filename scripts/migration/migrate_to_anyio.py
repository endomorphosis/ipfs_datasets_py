#!/usr/bin/env python3
"""Automated migration script from asyncio to anyio."""

import argparse
import sys
from pathlib import Path
from typing import List
import json

from anyio_migration_helpers import migrate_file


def find_python_files(root_dir: Path, exclude_dirs: List[str] = None) -> List[Path]:
    """Find all Python files in directory tree."""
    if exclude_dirs is None:
        exclude_dirs = ['__pycache__', '.git', '.pytest_cache', 'venv', 'env']
    
    python_files = []
    for path in root_dir.rglob('*.py'):
        if any(excluded in path.parts for excluded in exclude_dirs):
            continue
        python_files.append(path)
    
    return python_files


def has_asyncio_imports(file_path: Path) -> bool:
    """Check if file has asyncio imports."""
    try:
        content = file_path.read_text()
        return 'import anyio' in content or 'from asyncio' in content
    except Exception:
        return False


def migrate_directory(
    directory: Path,
    dry_run: bool = False,
    exclude_dirs: List[str] = None
) -> dict:
    """Migrate all Python files in directory."""
    print(f"Scanning {directory} for Python files with asyncio imports...")
    
    all_files = find_python_files(directory, exclude_dirs)
    print(f"Found {len(all_files)} Python files")
    
    files_to_migrate = [f for f in all_files if has_asyncio_imports(f)]
    print(f"Found {len(files_to_migrate)} files with asyncio imports")
    
    if not files_to_migrate:
        print("No files to migrate!")
        return {'total': 0, 'migrated': 0, 'errors': 0}
    
    results = []
    for i, file_path in enumerate(files_to_migrate, 1):
        print(f"[{i}/{len(files_to_migrate)}] Processing {file_path.relative_to(directory)}...")
        result = migrate_file(file_path, dry_run)
        results.append(result)
        
        if result.get('error'):
            print(f"  ERROR: {result['error']}")
        elif result['changed']:
            print(f"  ✓ Migrated ({result['simple_replacements']} replacements)")
            if result['complex_patterns']:
                print(f"  ⚠ Manual review needed: {', '.join(result['complex_patterns'])}")
        else:
            print(f"  - No changes needed")
    
    stats = {
        'total': len(results),
        'migrated': sum(1 for r in results if r['changed']),
        'errors': sum(1 for r in results if r.get('error')),
        'needs_review': sum(1 for r in results if r.get('complex_patterns')),
        'fully_migrated': sum(1 for r in results if r.get('migrated')),
        'results': results
    }
    
    return stats


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Migrate Python code from asyncio to anyio')
    parser.add_argument('directory', type=Path, nargs='?', default=Path('.'), 
                       help='Directory to migrate (default: current directory)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be changed without writing files')
    parser.add_argument('--exclude', action='append', default=[],
                       help='Directory names to exclude')
    parser.add_argument('--output-json', type=Path, help='Write results to JSON file')
    
    args = parser.parse_args()
    
    if not args.directory.exists():
        print(f"Error: Directory {args.directory} does not exist")
        sys.exit(1)
    
    print("=" * 70)
    print("ASYNCIO TO ANYIO MIGRATION TOOL")
    print("=" * 70)
    print()
    
    if args.dry_run:
        print("DRY RUN MODE - No files will be modified")
        print()
    
    stats = migrate_directory(args.directory, dry_run=args.dry_run, exclude_dirs=args.exclude or None)
    
    print()
    print("=" * 70)
    print("MIGRATION SUMMARY")
    print("=" * 70)
    print(f"Total files processed: {stats['total']}")
    print(f"Files migrated: {stats['migrated']}")
    print(f"Fully migrated (no manual review): {stats['fully_migrated']}")
    print(f"Need manual review: {stats['needs_review']}")
    print(f"Errors: {stats['errors']}")
    
    if args.output_json:
        with open(args.output_json, 'w') as f:
            json.dump(stats, f, indent=2)
        print(f"\nDetailed report saved to: {args.output_json}")
    
    if stats['errors'] > 0:
        sys.exit(1)
    elif not args.dry_run:
        print("\n✓ Migration complete!")
        if stats['needs_review'] > 0:
            print(f"⚠ {stats['needs_review']} files need manual review")
    
    sys.exit(0)


if __name__ == '__main__':
    main()
