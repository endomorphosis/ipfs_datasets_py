#!/usr/bin/env python3
"""
Rollback script for project reorganization.
Restores project state from backup created on 2025-06-27 16:23:41
"""

import shutil
import os
from pathlib import Path

def rollback():
    backup_path = Path("/home/barberb/ipfs_datasets_py_backup_20250627_162138")
    current_path = Path("/home/barberb/ipfs_datasets_py")
    
    if not backup_path.exists():
        print("❌ Backup directory not found!")
        return False
    
    print("🔄 Rolling back project reorganization...")
    
    # Remove current directory contents (except .git)
    for item in current_path.iterdir():
        if item.name != '.git':
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    
    # Restore from backup
    for item in backup_path.iterdir():
        if item.name != '.git':
            if item.is_dir():
                shutil.copytree(item, current_path / item.name)
            else:
                shutil.copy2(item, current_path / item.name)
    
    print("✅ Rollback completed successfully")
    return True

if __name__ == "__main__":
    rollback()
