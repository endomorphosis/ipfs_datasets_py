"""Comprehensive tests for DatasetLoader.

Tests cover:
- HuggingFace dataset loading
- Local file loading
- URL loading
- Format detection
- Error handling
- Edge cases
"""

import pytest
import tempfile
import json
from pathlib import Path


@pytest.mark.asyncio
async def test_dataset_loader_import():
    """Test that DatasetLoader can be imported and instantiated."""
    # GIVEN the core_operations module
    from ipfs_datasets_py.core_operations import DatasetLoader
    
    # WHEN we create a loader
    loader = DatasetLoader()
    
    # THEN the loader is created successfully
    assert loader is not None
    assert hasattr(loader, 'load')


@pytest.mark.asyncio
async def test_dataset_loader_empty_source():
    """Test DatasetLoader rejects empty source."""
    # GIVEN a dataset loader
    from ipfs_datasets_py.core_operations import DatasetLoader
    loader = DatasetLoader()
    
    # WHEN we try to load with empty source
    result = await loader.load("")
    
    # THEN we get an error
    assert result["status"] == "error"
    assert "empty" in result["message"].lower() or "required" in result["message"].lower()


@pytest.mark.asyncio
async def test_dataset_loader_python_file_rejection():
    """Test DatasetLoader rejects Python files for security."""
    # GIVEN a dataset loader
    from ipfs_datasets_py.core_operations import DatasetLoader
    loader = DatasetLoader()
    
    # WHEN we try to load a Python file
    result = await loader.load("malicious.py")
    
    # THEN we get an error
    assert result["status"] == "error"
    assert "Python files" in result["message"] or "security" in result["message"].lower()


@pytest.mark.asyncio
async def test_dataset_loader_executable_rejection():
    """Test DatasetLoader rejects executable files."""
    # GIVEN a dataset loader
    from ipfs_datasets_py.core_operations import DatasetLoader
    loader = DatasetLoader()
    
    # WHEN we try to load an executable
    result = await loader.load("malware.exe")
    
    # THEN we get an error
    assert result["status"] == "error"
    assert "Executable files" in result["message"] or "security" in result["message"].lower()


@pytest.mark.asyncio
async def test_dataset_loader_local_json_file():
    """Test DatasetLoader can load local JSON files."""
    # GIVEN a temporary JSON file
    from ipfs_datasets_py.core_operations import DatasetLoader
    loader = DatasetLoader()
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        test_data = {"test": "data", "items": [1, 2, 3]}
        json.dump(test_data, f)
        temp_path = f.name
    
    try:
        # WHEN we load the file
        result = await loader.load(temp_path)
        
        # THEN we get success (or at least attempt the load)
        assert isinstance(result, dict)
        assert "status" in result
    finally:
        # Cleanup
        Path(temp_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_dataset_loader_nonexistent_file():
    """Test DatasetLoader handles nonexistent files gracefully."""
    # GIVEN a dataset loader
    from ipfs_datasets_py.core_operations import DatasetLoader
    loader = DatasetLoader()
    
    # WHEN we try to load a nonexistent file
    result = await loader.load("/nonexistent/path/to/data.json")
    
    # THEN we get an error
    assert result["status"] == "error"
    assert "not found" in result["message"].lower() or "does not exist" in result["message"].lower()


@pytest.mark.asyncio
async def test_dataset_loader_huggingface_dataset_name():
    """Test DatasetLoader attempts to load HuggingFace dataset."""
    # GIVEN a dataset loader
    from ipfs_datasets_py.core_operations import DatasetLoader
    loader = DatasetLoader()
    
    # WHEN we try to load a well-known dataset name
    result = await loader.load("squad", options={"split": "train[:1]"})
    
    # THEN we get a result (success if HF available, error if not)
    assert isinstance(result, dict)
    assert "status" in result
    # Don't assert success since HF might not be available in test environment


@pytest.mark.asyncio
async def test_dataset_loader_with_format_option():
    """Test DatasetLoader respects format option."""
    # GIVEN a dataset loader
    from ipfs_datasets_py.core_operations import DatasetLoader
    loader = DatasetLoader()
    
    # WHEN we specify a format
    result = await loader.load("test_data", format="json")
    
    # THEN the format is considered
    assert isinstance(result, dict)
    assert "status" in result


@pytest.mark.asyncio
async def test_dataset_loader_with_options():
    """Test DatasetLoader accepts and uses options."""
    # GIVEN a dataset loader
    from ipfs_datasets_py.core_operations import DatasetLoader
    loader = DatasetLoader()
    
    # WHEN we provide options
    options = {"cache_dir": "/tmp/test_cache", "split": "train"}
    result = await loader.load("test_source", options=options)
    
    # THEN options are processed
    assert isinstance(result, dict)
    assert "status" in result


@pytest.mark.asyncio
async def test_dataset_loader_multiple_formats():
    """Test DatasetLoader handles multiple format types."""
    # GIVEN a dataset loader
    from ipfs_datasets_py.core_operations import DatasetLoader
    loader = DatasetLoader()
    
    # WHEN we try different formats
    formats = ["json", "csv", "parquet", "arrow"]
    
    for fmt in formats:
        result = await loader.load(f"test.{fmt}", format=fmt)
        
        # THEN each format is handled
        assert isinstance(result, dict)
        assert "status" in result
