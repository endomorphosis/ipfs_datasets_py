#!/usr/bin/env python3
"""
Python Test Conflict Cleanup Script

This script systematically removes Python cache files and identifies
duplicate test modules that are causing pytest import conflicts.
"""

import os
import shutil
from pathlib import Path
from typing import List, Dict, Set
import subprocess


def remove_pycache_files(root_dir: str) -> int:
    """
    Remove all __pycache__ directories and .pyc files recursively.
    
    Args:
        root_dir: Root directory to start cleanup from
        
    Returns:
        Number of cache directories/files removed
    """
    removed_count = 0
    
    for root, dirs, files in os.walk(root_dir):
        # Remove __pycache__ directories
        if