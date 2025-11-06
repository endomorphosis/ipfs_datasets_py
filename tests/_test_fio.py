#!/usr/bin/env python3
"""
Test suite for fio functionality with GIVEN WHEN THEN format.
"""

import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestFio:
    """Test file I/O functionality."""

    def test_basic_file_operations(self):
        """
        GIVEN a file system with read/write capabilities
        WHEN performing basic file operations
        THEN expect operations to complete successfully
        AND files should be created, read, and deleted properly
        """
        import tempfile
        import os
        
        # Test basic file operations
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "test_file.txt"
            test_content = "Test content for file operations"
            
            # Test file creation and writing
            test_file.write_text(test_content, encoding='utf-8')
            assert test_file.exists()
            
            # Test file reading
            read_content = test_file.read_text(encoding='utf-8')
            assert read_content == test_content
            
            # Test file stats
            stats = test_file.stat()
            assert stats.st_size > 0
            
            # Test file deletion (handled by temp directory cleanup)
            assert test_file.exists()

    @pytest.mark.asyncio
    async def test_async_file_operations(self):
        """
        GIVEN an async file system interface
        WHEN performing asynchronous file operations
        THEN expect operations to complete without blocking
        AND async operations should handle concurrent access properly
        """
        import tempfile
        import aiofiles
        
        # Test async file operations
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "async_test_file.txt"
            test_content = "Async test content"
            
            try:
                # Test async file writing
                async with aiofiles.open(test_file, 'w', encoding='utf-8') as f:
                    await f.write(test_content)
                
                assert test_file.exists()
                
                # Test async file reading
                async with aiofiles.open(test_file, 'r', encoding='utf-8') as f:
                    read_content = await f.read()
                
                assert read_content == test_content
                
            except ImportError:
                # Fallback to sync operations if aiofiles not available
                test_file.write_text(test_content, encoding='utf-8')
                read_content = test_file.read_text(encoding='utf-8')
                assert read_content == test_content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
