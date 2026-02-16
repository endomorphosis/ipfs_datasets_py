"""
Tests for lineage import migration scripts.

Tests both Python and Shell migration scripts to ensure they correctly
update import statements from legacy to new lineage package.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


# Sample Python code with old imports
SAMPLE_CODE_OLD = '''
"""Test module with old imports."""
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import EnhancedLineageTracker
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage_enhanced import (
    CrossDocumentLineageEnhancer,
    DetailedLineageIntegrator
)

def test_function():
    """Test function."""
    tracker = EnhancedLineageTracker()
    return tracker
'''


@pytest.fixture
def temp_test_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_file(temp_test_dir):
    """Create a sample Python file with old imports."""
    test_file = temp_test_dir / "test_module.py"
    test_file.write_text(SAMPLE_CODE_OLD)
    return test_file


def test_python_migration_dry_run(sample_file):
    """Test Python migration script in dry-run mode."""
    # GIVEN a file with old imports
    assert "cross_document_lineage" in sample_file.read_text()
    
    # WHEN running migration in dry-run mode
    script = Path(__file__).parent.parent.parent.parent / "scripts" / "migration" / "migrate_lineage_imports.py"
    result = subprocess.run(
        [sys.executable, str(script), "--dry-run", str(sample_file)],
        capture_output=True,
        text=True
    )
    
    # THEN it should succeed
    assert result.returncode == 0
    
    # THEN file should not be modified
    assert "cross_document_lineage" in sample_file.read_text()


def test_python_migration_single_file(sample_file):
    """Test Python migration script on a single file."""
    # GIVEN a file with old imports
    original_content = sample_file.read_text()
    assert "cross_document_lineage" in original_content
    
    # WHEN running migration
    script = Path(__file__).parent.parent.parent.parent / "scripts" / "migration" / "migrate_lineage_imports.py"
    result = subprocess.run(
        [sys.executable, str(script), "--verbose", str(sample_file)],
        capture_output=True,
        text=True
    )
    
    # THEN it should succeed
    assert result.returncode == 0
    
    # THEN file should be modified
    new_content = sample_file.read_text()
    assert "from ipfs_datasets_py.knowledge_graphs.lineage import" in new_content
    
    # THEN backup should exist
    backup_file = Path(str(sample_file) + ".backup")
    assert backup_file.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
