#!/usr/bin/env python3
"""
Test script to verify cleanup functionality
"""

import os
from pathlib import Path

def test_cleanup():
    """Test the cleanup functionality."""
    print("=== ROOT DIRECTORY CLEANUP TEST ===")
    print(f"Current directory: {os.getcwd()}")
    print(f"Project root: {Path.cwd()}")
    
    # List current files in root
    root_files = list(Path('.').glob('*'))
    print(f"\nCurrent root directory contains {len(root_files)} items:")
    
    # Categorize files
    migration_docs = []
    validation_scripts = []
    utility_scripts = []
    temp_dirs = []
    keep_files = []
    
    for item in root_files:
        name = item.name
        if name.startswith('.'):
            continue
            
        if any(keyword in name.lower() for keyword in ['migration', 'phase', 'integration', 'completion']):
            if name.endswith('.md'):
                migration_docs.append(name)
            elif name.endswith('.py'):
                validation_scripts.append(name)
        elif name in ['start_fastapi.py', 'deploy.py', 'simple_fastapi.py', 'cleanup_implementation.py']:
            utility_scripts.append(name)
        elif name in ['migration_temp', 'migration_logs', 'migration_scripts', 'test_results']:
            temp_dirs.append(name)
        elif name in ['README.md', 'LICENSE', 'requirements.txt', 'pyproject.toml', 'setup.py', 'Dockerfile']:
            keep_files.append(name)
    
    print(f"\nMigration docs to archive: {len(migration_docs)}")
    for doc in migration_docs[:5]:  # Show first 5
        print(f"  - {doc}")
    if len(migration_docs) > 5:
        print(f"  ... and {len(migration_docs) - 5} more")
    
    print(f"\nValidation scripts to archive: {len(validation_scripts)}")  
    for script in validation_scripts[:5]:  # Show first 5
        print(f"  - {script}")
    if len(validation_scripts) > 5:
        print(f"  ... and {len(validation_scripts) - 5} more")
    
    print(f"\nUtility scripts to move: {len(utility_scripts)}")
    for script in utility_scripts:
        print(f"  - {script}")
    
    print(f"\nTemporary directories to archive: {len(temp_dirs)}")
    for dir_name in temp_dirs:
        print(f"  - {dir_name}")
    
    print(f"\nCore files to keep in root: {len(keep_files)}")
    for file_name in keep_files:
        print(f"  - {file_name}")
    
    # Calculate cleanup impact
    total_items = len(root_files)
    items_to_move = len(migration_docs) + len(validation_scripts) + len(utility_scripts) + len(temp_dirs)
    items_to_keep = len(keep_files) + 5  # Core directories
    
    print(f"\n=== CLEANUP IMPACT ===")
    print(f"Total items in root: {total_items}")
    print(f"Items to move/archive: {items_to_move}")
    print(f"Items to keep in root: {items_to_keep}")
    print(f"Reduction percentage: {(items_to_move / total_items * 100):.1f}%")
    
    return True

if __name__ == "__main__":
    test_cleanup()
