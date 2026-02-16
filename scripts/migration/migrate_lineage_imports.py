#!/usr/bin/env python3
"""
Automated migration script for knowledge_graphs lineage imports.

This script updates legacy import statements to use the new lineage package structure.

Usage:
    python migrate_lineage_imports.py [options] <path>

Options:
    --dry-run          Show what would be changed without modifying files
    --backup           Create .backup files before modifying (default: True)
    --no-backup        Don't create backup files
    --verbose          Show detailed progress information
    --rollback         Restore files from .backup files
    --validate         Validate changes after migration

Examples:
    # Migrate a single file with preview
    python migrate_lineage_imports.py --dry-run myfile.py
    
    # Migrate entire directory with backups
    python migrate_lineage_imports.py --backup src/
    
    # Rollback changes
    python migrate_lineage_imports.py --rollback src/
"""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from typing import List, Tuple, Dict

# Migration patterns
MIGRATIONS = [
    # Pattern 1: from ...cross_document_lineage import
    (
        r'from\s+(\.|ipfs_datasets_py\.knowledge_graphs\.)cross_document_lineage\s+import',
        r'from \1lineage import'
    ),
    # Pattern 2: from ...cross_document_lineage_enhanced import
    (
        r'from\s+(\.|ipfs_datasets_py\.knowledge_graphs\.)cross_document_lineage_enhanced\s+import',
        r'from \1lineage import'
    ),
    # Pattern 3: import ...cross_document_lineage
    (
        r'import\s+(\.|ipfs_datasets_py\.knowledge_graphs\.)cross_document_lineage\b',
        r'import \1lineage'
    ),
    # Pattern 4: import ...cross_document_lineage_enhanced
    (
        r'import\s+(\.|ipfs_datasets_py\.knowledge_graphs\.)cross_document_lineage_enhanced\b',
        r'import \1lineage'
    ),
]


class LineageMigrator:
    """Handles migration of lineage imports."""
    
    def __init__(self, dry_run=False, backup=True, verbose=False):
        self.dry_run = dry_run
        self.backup = backup
        self.verbose = verbose
        self.stats = {
            'files_scanned': 0,
            'files_modified': 0,
            'lines_changed': 0,
            'patterns_matched': {},
        }
    
    def log(self, message: str, level: str = 'INFO'):
        """Log message if verbose mode enabled."""
        if self.verbose or level == 'ERROR':
            print(f"[{level}] {message}")
    
    def find_python_files(self, path: Path) -> List[Path]:
        """Find all Python files in path."""
        if path.is_file():
            return [path] if path.suffix == '.py' else []
        
        python_files = []
        for root, dirs, files in os.walk(path):
            # Skip common non-source directories
            dirs[:] = [d for d in dirs if d not in {
                '__pycache__', '.git', '.pytest_cache', 'node_modules',
                '.venv', 'venv', 'env', '.backup'
            }]
            
            for file in files:
                if file.endswith('.py'):
                    python_files.append(Path(root) / file)
        
        return python_files
    
    def migrate_file(self, file_path: Path) -> Tuple[bool, int]:
        """
        Migrate a single file.
        
        Returns:
            (modified, lines_changed): Whether file was modified and number of lines changed
        """
        self.stats['files_scanned'] += 1
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            self.log(f"Error reading {file_path}: {e}", 'ERROR')
            return False, 0
        
        original_content = content
        lines_changed = 0
        
        # Apply all migration patterns
        for pattern, replacement in MIGRATIONS:
            matches = re.findall(pattern, content)
            if matches:
                content_before = content
                content = re.sub(pattern, replacement, content)
                if content != content_before:
                    pattern_key = pattern[:50]  # Truncate for display
                    self.stats['patterns_matched'][pattern_key] = \
                        self.stats['patterns_matched'].get(pattern_key, 0) + len(matches)
                    lines_changed += len(matches)
        
        if content == original_content:
            return False, 0
        
        # Show changes
        if self.verbose or self.dry_run:
            print(f"\n{'='*60}")
            print(f"File: {file_path}")
            print(f"Lines changed: {lines_changed}")
            if self.dry_run:
                # Show diff
                original_lines = original_content.split('\n')
                new_lines = content.split('\n')
                for i, (old, new) in enumerate(zip(original_lines, new_lines), 1):
                    if old != new:
                        print(f"  Line {i}:")
                        print(f"    - {old}")
                        print(f"    + {new}")
        
        if self.dry_run:
            return True, lines_changed
        
        # Create backup if requested
        if self.backup:
            backup_path = Path(str(file_path) + '.backup')
            try:
                shutil.copy2(file_path, backup_path)
                self.log(f"Created backup: {backup_path}")
            except Exception as e:
                self.log(f"Error creating backup for {file_path}: {e}", 'ERROR')
                return False, 0
        
        # Write modified content
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.log(f"Modified: {file_path}")
            self.stats['files_modified'] += 1
            self.stats['lines_changed'] += lines_changed
            return True, lines_changed
        except Exception as e:
            self.log(f"Error writing {file_path}: {e}", 'ERROR')
            return False, 0
    
    def migrate(self, path: Path) -> bool:
        """Migrate all files in path."""
        python_files = self.find_python_files(path)
        
        if not python_files:
            print(f"No Python files found in {path}")
            return True
        
        print(f"Found {len(python_files)} Python file(s) to scan")
        if self.dry_run:
            print("DRY RUN MODE - No files will be modified\n")
        
        for file_path in python_files:
            self.migrate_file(file_path)
        
        return True
    
    def rollback(self, path: Path) -> bool:
        """Rollback migration by restoring from backup files."""
        if path.is_file():
            backup_path = Path(str(path) + '.backup')
            if backup_path.exists():
                shutil.copy2(backup_path, path)
                print(f"Restored: {path}")
                backup_path.unlink()
                return True
            else:
                print(f"No backup found for {path}")
                return False
        
        # Rollback directory
        restored = 0
        for root, dirs, files in os.walk(path):
            for file in files:
                if file.endswith('.py.backup'):
                    backup_path = Path(root) / file
                    original_path = Path(str(backup_path).replace('.backup', ''))
                    try:
                        shutil.copy2(backup_path, original_path)
                        print(f"Restored: {original_path}")
                        backup_path.unlink()
                        restored += 1
                    except Exception as e:
                        print(f"Error restoring {original_path}: {e}")
        
        if restored == 0:
            print(f"No backup files found in {path}")
        else:
            print(f"\nRestored {restored} file(s)")
        
        return restored > 0
    
    def validate(self, path: Path) -> bool:
        """Validate migration by checking for old imports."""
        python_files = self.find_python_files(path)
        issues = []
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for old import patterns
                for pattern, _ in MIGRATIONS:
                    matches = re.findall(pattern, content)
                    if matches:
                        issues.append((file_path, pattern, matches))
            except Exception as e:
                print(f"Error validating {file_path}: {e}")
        
        if issues:
            print("\nValidation FAILED - Found old import patterns:")
            for file_path, pattern, matches in issues:
                print(f"  {file_path}")
                print(f"    Pattern: {pattern[:60]}")
                print(f"    Matches: {len(matches)}")
            return False
        
        print("\nValidation PASSED - No old import patterns found")
        return True
    
    def print_stats(self):
        """Print migration statistics."""
        print(f"\n{'='*60}")
        print("Migration Statistics")
        print(f"{'='*60}")
        print(f"Files scanned:    {self.stats['files_scanned']}")
        print(f"Files modified:   {self.stats['files_modified']}")
        print(f"Lines changed:    {self.stats['lines_changed']}")
        
        if self.stats['patterns_matched']:
            print(f"\nPatterns matched:")
            for pattern, count in self.stats['patterns_matched'].items():
                print(f"  {pattern}... : {count} matches")
        
        print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description='Migrate knowledge_graphs lineage imports',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        'path',
        type=Path,
        help='Path to file or directory to migrate'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be changed without modifying files'
    )
    parser.add_argument(
        '--backup',
        action='store_true',
        default=True,
        help='Create .backup files before modifying (default: True)'
    )
    parser.add_argument(
        '--no-backup',
        action='store_true',
        help='Don\'t create backup files'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show detailed progress information'
    )
    parser.add_argument(
        '--rollback',
        action='store_true',
        help='Restore files from .backup files'
    )
    parser.add_argument(
        '--validate',
        action='store_true',
        help='Validate changes after migration'
    )
    
    args = parser.parse_args()
    
    if not args.path.exists():
        print(f"Error: Path not found: {args.path}")
        return 1
    
    # Handle --no-backup flag
    if args.no_backup:
        args.backup = False
    
    migrator = LineageMigrator(
        dry_run=args.dry_run,
        backup=args.backup,
        verbose=args.verbose
    )
    
    try:
        if args.rollback:
            success = migrator.rollback(args.path)
        else:
            success = migrator.migrate(args.path)
            if success and not args.dry_run:
                migrator.print_stats()
                
                if args.validate:
                    print("\nRunning validation...")
                    success = migrator.validate(args.path)
        
        return 0 if success else 1
    
    except KeyboardInterrupt:
        print("\nMigration interrupted by user")
        return 130
    except Exception as e:
        print(f"Error during migration: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
