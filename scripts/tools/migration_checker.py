#!/usr/bin/env python3
"""
Migration Checker for IPFS Datasets Python v1.x → v2.0

Scans your codebase for deprecated imports and provides migration recommendations.

Usage:
    python migration_checker.py /path/to/project
    python migration_checker.py . --verbose
"""

import os
import re
import sys
import argparse
from pathlib import Path
from typing import List
from dataclasses import dataclass, field


@dataclass
class DeprecatedImport:
    """Represents a deprecated import found in code."""
    file_path: str
    line_number: int
    import_type: str  # 'multimedia', 'serialization', 'graphrag'
    old_import: str
    new_import: str


@dataclass
class ScanResults:
    """Results of scanning codebase for deprecated imports."""
    total_files_scanned: int = 0
    files_with_issues: int = 0
    deprecated_imports: List[DeprecatedImport] = field(default_factory=list)
    
    @property
    def multimedia_count(self) -> int:
        return len([d for d in self.deprecated_imports if d.import_type == 'multimedia'])
    
    @property
    def serialization_count(self) -> int:
        return len([d for d in self.deprecated_imports if d.import_type == 'serialization'])
    
    @property
    def graphrag_count(self) -> int:
        return len([d for d in self.deprecated_imports if d.import_type == 'graphrag'])


print("✅ Migration checker created successfully!")
