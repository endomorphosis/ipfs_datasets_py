"""Tests for core_operations module."""

import pytest


@pytest.mark.asyncio
async def test_dataset_loader_import():
    """Test that DatasetLoader can be imported."""
    from ipfs_datasets_py.core_operations import DatasetLoader
    
    loader = DatasetLoader()
    assert loader is not None


@pytest.mark.asyncio
async def test_ipfs_pinner_import():
    """Test that IPFSPinner can be imported."""
    from ipfs_datasets_py.core_operations import IPFSPinner
    
    pinner = IPFSPinner()
    assert pinner is not None


@pytest.mark.asyncio
async def test_ipfs_pinner_dict_content():
    """Test IPFSPinner with dict content."""
    from ipfs_datasets_py.core_operations import IPFSPinner
    
    pinner = IPFSPinner()
    result = await pinner.pin({"test": "data"})
    
    assert result["status"] == "success"
    assert "cid" in result
    assert result["content_type"] == "data"


@pytest.mark.asyncio
async def test_ipfs_pinner_nonexistent_file():
    """Test IPFSPinner with nonexistent file."""
    from ipfs_datasets_py.core_operations import IPFSPinner
    
    pinner = IPFSPinner()
    result = await pinner.pin("/nonexistent/path/to/file.txt")
    
    assert result["status"] == "error"
    assert "does not exist" in result["message"]


@pytest.mark.asyncio  
async def test_dataset_loader_validation():
    """Test DatasetLoader input validation."""
    from ipfs_datasets_py.core_operations import DatasetLoader
    
    loader = DatasetLoader()
    
    # Test empty string
    result = await loader.load("")
    assert result["status"] == "error"
    
    # Test Python file rejection
    result = await loader.load("test.py")
    assert result["status"] == "error"
    assert "Python files" in result["message"]
    
    # Test executable rejection
    result = await loader.load("test.exe")
    assert result["status"] == "error"
    assert "Executable files" in result["message"]


@pytest.mark.asyncio
async def test_core_operations_exports():
    """Test that all core operations are exported."""
    from ipfs_datasets_py.core_operations import (
        DatasetLoader,
        DatasetSaver,
        DatasetConverter,
        IPFSPinner,
        IPFSGetter,
    )
    
    assert DatasetLoader is not None
    assert DatasetSaver is not None
    assert DatasetConverter is not None
    assert IPFSPinner is not None
    assert IPFSGetter is not None
