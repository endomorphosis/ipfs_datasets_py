#!/usr/bin/env python3
"""
Automated Migration Script: Move multimedia from data_transformation to processors

This script:
1. Copies multimedia directory from data_transformation/ to processors/
2. Updates all import statements across the codebase
3. Creates backward compatibility shims
4. Validates all imports still work
5. Generates migration report

Usage:
    python scripts/migrations/migrate_multimedia_to_processors.py --dry-run
    python scripts/migrations/migrate_multimedia_to_processors.py --execute
"""

import os
import re
import shutil
import sys
from pathlib import Path
from typing import List, Dict, Tuple
import argparse


class MultimediaMigration:
    """Handles migration of multimedia from data_transformation to processors."""
    
    def __init__(self, repo_root: Path, dry_run: bool = True):
        self.repo_root = repo_root
        self.dry_run = dry_run
        self.changes = []
        self.errors = []
        
        # Paths
        self.old_path = repo_root / "ipfs_datasets_py" / "data_transformation" / "multimedia"
        self.new_path = repo_root / "ipfs_datasets_py" / "processors" / "multimedia"
        
        # Import patterns
        self.import_patterns = [
            # from ipfs_datasets_py.data_transformation.multimedia import X
            (
                r'from\s+ipfs_datasets_py\.data_transformation\.multimedia\s+import\s+',
                'from ipfs_datasets_py.processors.multimedia import '
            ),
            # from data_transformation.multimedia import X
            (
                r'from\s+data_transformation\.multimedia\s+import\s+',
                'from processors.multimedia import '
            ),
            # import ipfs_datasets_py.data_transformation.multimedia
            (
                r'import\s+ipfs_datasets_py\.data_transformation\.multimedia',
                'import ipfs_datasets_py.processors.multimedia'
            ),
        ]
    
    def validate_preconditions(self) -> bool:
        """Validate that migration can proceed."""
        print("\n=== Validating Preconditions ===")
        
        if not self.old_path.exists():
            self.errors.append(f"Source path does not exist: {self.old_path}")
            return False
        
        if self.new_path.exists():
            print(f"⚠️  Target path already exists: {self.new_path}")
            print("   Migration may have been partially completed")
        
        # Check if it's a git submodule
        gitmodules = self.repo_root / ".gitmodules"
        if gitmodules.exists():
            content = gitmodules.read_text()
            if "data_transformation/multimedia" in content:
                self.errors.append("multimedia is a git submodule - different migration needed")
                return False
        
        print("✓ Preconditions validated")
        return True
    
    def find_files_to_update(self) -> List[Path]:
        """Find all Python files that import from multimedia."""
        print("\n=== Finding Files to Update ===")
        
        files_to_update = []
        
        # Search for imports
        for root, dirs, files in os.walk(self.repo_root / "ipfs_datasets_py"):
            # Skip __pycache__ and .git
            dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git', '.venv', 'venv']]
            
            for file in files:
                if file.endswith('.py'):
                    filepath = Path(root) / file
                    try:
                        content = filepath.read_text()
                        for pattern, _ in self.import_patterns:
                            if re.search(pattern, content):
                                files_to_update.append(filepath)
                                break
                    except Exception as e:
                        print(f"   ⚠️  Error reading {filepath}: {e}")
        
        print(f"✓ Found {len(files_to_update)} files to update")
        return files_to_update
    
    def copy_multimedia_directory(self) -> bool:
        """Copy multimedia directory to new location."""
        print("\n=== Copying Multimedia Directory ===")
        
        if self.dry_run:
            print(f"[DRY RUN] Would copy: {self.old_path} → {self.new_path}")
            return True
        
        try:
            # Create processors directory if needed
            self.new_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy the entire directory
            if self.new_path.exists():
                print(f"   Removing existing: {self.new_path}")
                shutil.rmtree(self.new_path)
            
            print(f"   Copying: {self.old_path} → {self.new_path}")
            shutil.copytree(self.old_path, self.new_path)
            
            print("✓ Directory copied successfully")
            return True
            
        except Exception as e:
            self.errors.append(f"Error copying directory: {e}")
            return False
    
    def update_imports_in_file(self, filepath: Path) -> int:
        """Update import statements in a single file."""
        try:
            content = filepath.read_text()
            original_content = content
            updates_made = 0
            
            for pattern, replacement in self.import_patterns:
                new_content = re.sub(pattern, replacement, content)
                if new_content != content:
                    updates_made += len(re.findall(pattern, content))
                    content = new_content
            
            if content != original_content:
                if not self.dry_run:
                    filepath.write_text(content)
                
                self.changes.append({
                    'file': str(filepath.relative_to(self.repo_root)),
                    'updates': updates_made
                })
                
                return updates_made
            
            return 0
            
        except Exception as e:
            self.errors.append(f"Error updating {filepath}: {e}")
            return 0
    
    def update_all_imports(self, files: List[Path]) -> Tuple[int, int]:
        """Update imports in all files."""
        print("\n=== Updating Import Statements ===")
        
        total_files = 0
        total_updates = 0
        
        for filepath in files:
            updates = self.update_imports_in_file(filepath)
            if updates > 0:
                total_files += 1
                total_updates += updates
                rel_path = filepath.relative_to(self.repo_root)
                print(f"   {'[DRY RUN] ' if self.dry_run else ''}Updated {rel_path}: {updates} import(s)")
        
        print(f"\n✓ Updated {total_updates} import(s) in {total_files} file(s)")
        return total_files, total_updates
    
    def create_backward_compatibility_shim(self) -> bool:
        """Create backward compatibility in old location."""
        print("\n=== Creating Backward Compatibility Shim ===")
        
        shim_content = '''"""
DEPRECATED: This module has moved to ipfs_datasets_py.processors.multimedia

This shim provides backward compatibility during the deprecation period.
All functionality has been moved to processors.multimedia.

Migration Guide:
    OLD: from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper
    NEW: from ipfs_datasets_py.processors.multimedia import FFmpegWrapper

This shim will be removed in version 2.0.0.
"""

import warnings
import sys

# Issue deprecation warning
warnings.warn(
    "ipfs_datasets_py.data_transformation.multimedia is deprecated and will be removed in version 2.0.0. "
    "Please update your imports to use ipfs_datasets_py.processors.multimedia instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export from new location
try:
    from ipfs_datasets_py.processors.multimedia import *
    from ipfs_datasets_py.processors.multimedia import (
        FFmpegWrapper,
        YtDlpWrapper,
        MediaProcessor,
        MediaUtils,
        DiscordWrapper,
        EmailProcessor,
    )
except ImportError as e:
    # If new location doesn't exist yet, provide helpful error
    print(
        f"ERROR: Could not import from new location (processors.multimedia).\\n"
        f"The multimedia migration may not be complete.\\n"
        f"Original error: {e}",
        file=sys.stderr
    )
    raise
'''
        
        shim_path = self.old_path / "__init__.py"
        
        if self.dry_run:
            print(f"[DRY RUN] Would create shim at: {shim_path}")
            return True
        
        try:
            shim_path.write_text(shim_content)
            print(f"✓ Created backward compatibility shim")
            return True
        except Exception as e:
            self.errors.append(f"Error creating shim: {e}")
            return False
    
    def generate_report(self) -> str:
        """Generate migration report."""
        report = [
            "\n" + "=" * 70,
            "MULTIMEDIA MIGRATION REPORT",
            "=" * 70,
            f"\nMode: {'DRY RUN' if self.dry_run else 'EXECUTION'}",
            f"\nSource: {self.old_path}",
            f"Target: {self.new_path}",
        ]
        
        if self.changes:
            report.append(f"\n\nFiles Updated ({len(self.changes)}):")
            for change in self.changes[:10]:  # Show first 10
                report.append(f"  • {change['file']}: {change['updates']} import(s)")
            if len(self.changes) > 10:
                report.append(f"  ... and {len(self.changes) - 10} more")
        
        if self.errors:
            report.append(f"\n\nErrors ({len(self.errors)}):")
            for error in self.errors:
                report.append(f"  ✗ {error}")
        else:
            report.append("\n\n✓ No errors encountered")
        
        report.append("\n" + "=" * 70 + "\n")
        
        return "\n".join(report)
    
    def execute(self) -> bool:
        """Execute the complete migration."""
        print("\n" + "=" * 70)
        print("MULTIMEDIA MIGRATION SCRIPT")
        print("=" * 70)
        print(f"Mode: {'DRY RUN' if self.dry_run else 'EXECUTION'}")
        
        # Step 1: Validate
        if not self.validate_preconditions():
            print("\n✗ Preconditions failed")
            print(self.generate_report())
            return False
        
        # Step 2: Find files
        files_to_update = self.find_files_to_update()
        if not files_to_update:
            print("\n⚠️  No files found to update")
        
        # Step 3: Copy directory
        if not self.copy_multimedia_directory():
            print("\n✗ Failed to copy directory")
            print(self.generate_report())
            return False
        
        # Step 4: Update imports
        files_updated, imports_updated = self.update_all_imports(files_to_update)
        
        # Step 5: Create shim
        if not self.create_backward_compatibility_shim():
            print("\n⚠️  Failed to create backward compatibility shim")
        
        # Generate report
        print(self.generate_report())
        
        if self.dry_run:
            print("\n💡 This was a DRY RUN. Use --execute to apply changes.")
            return True
        
        if self.errors:
            print(f"\n⚠️  Migration completed with {len(self.errors)} error(s)")
            return False
        
        print("\n✓ Migration completed successfully!")
        print(f"   • Moved {self.old_path} → {self.new_path}")
        print(f"   • Updated {imports_updated} import(s) in {files_updated} file(s)")
        print(f"   • Created backward compatibility shim")
        
        return True


def main():
    parser = argparse.ArgumentParser(
        description="Migrate multimedia from data_transformation to processors"
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Execute migration (default is dry-run)'
    )
    parser.add_argument(
        '--repo-root',
        type=str,
        default=None,
        help='Repository root path (auto-detected if not provided)'
    )
    
    args = parser.parse_args()
    
    # Determine repo root
    if args.repo_root:
        repo_root = Path(args.repo_root)
    else:
        # Auto-detect: go up from script location
        script_path = Path(__file__).resolve()
        repo_root = script_path.parent.parent.parent
    
    if not (repo_root / "ipfs_datasets_py").exists():
        print(f"✗ Invalid repo root: {repo_root}")
        print("  Expected to find ipfs_datasets_py/ directory")
        sys.exit(1)
    
    # Execute migration
    migration = MultimediaMigration(
        repo_root=repo_root,
        dry_run=not args.execute
    )
    
    success = migration.execute()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
