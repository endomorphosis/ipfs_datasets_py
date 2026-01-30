"""
Tests for rich metadata extraction.
"""

import pytest
import tempfile
from pathlib import Path
from ipfs_datasets_py.file_converter import MetadataExtractor, extract_metadata


class TestMetadataExtractor:
    """Test MetadataExtractor class."""
    
    def test_initialization(self):
        """Test extractor initialization."""
        extractor = MetadataExtractor()
        assert extractor is not None
        
        extractor_no_ipfs = MetadataExtractor(enable_ipfs=False)
        assert extractor_no_ipfs.enable_ipfs is False
    
    def test_extract_basic_metadata(self):
        """Test extraction of basic file metadata."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test content for metadata extraction")
            temp_path = f.name
        
        try:
            extractor = MetadataExtractor()
            metadata = extractor.extract(temp_path)
            
            # Check structure
            assert 'file' in metadata
            assert 'hashes' in metadata
            assert 'format' in metadata
            assert 'extraction_time' in metadata
            
            # Check file properties
            assert metadata['file']['name'] == Path(temp_path).name
            assert metadata['file']['size'] > 0
            assert metadata['file']['extension'] == '.txt'
            
        finally:
            Path(temp_path).unlink()
    
    def test_extract_hashes(self):
        """Test hash calculation."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test content")
            temp_path = f.name
        
        try:
            extractor = MetadataExtractor()
            metadata = extractor.extract(temp_path)
            
            # Check hashes exist
            assert 'md5' in metadata['hashes']
            assert 'sha256' in metadata['hashes']
            
            # Check hash formats (hexadecimal strings)
            assert len(metadata['hashes']['md5']) == 32
            assert len(metadata['hashes']['sha256']) == 64
            
        finally:
            Path(temp_path).unlink()
    
    def test_extract_format_info(self):
        """Test format information extraction."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{"test": "data"}')
            temp_path = f.name
        
        try:
            extractor = MetadataExtractor()
            metadata = extractor.extract(temp_path)
            
            # Check format info
            assert 'mime_type' in metadata['format']
            assert metadata['format']['extension'] == '.json'
            
        finally:
            Path(temp_path).unlink()
    
    def test_human_readable_size(self):
        """Test human-readable size formatting."""
        extractor = MetadataExtractor()
        
        assert extractor._human_readable_size(100) == "100.00 B"
        assert extractor._human_readable_size(1024) == "1.00 KB"
        assert extractor._human_readable_size(1024 * 1024) == "1.00 MB"
        assert extractor._human_readable_size(1024 * 1024 * 1024) == "1.00 GB"
    
    def test_extract_batch(self):
        """Test batch metadata extraction."""
        files = []
        try:
            # Create multiple temp files
            for i in range(3):
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                    f.write(f"Content {i}")
                    files.append(f.name)
            
            extractor = MetadataExtractor()
            results = extractor.extract_batch(files)
            
            assert len(results) == 3
            for file_path in files:
                assert file_path in results
                assert 'file' in results[file_path]
                assert 'hashes' in results[file_path]
        
        finally:
            for file_path in files:
                Path(file_path).unlink(missing_ok=True)
    
    def test_extract_nonexistent_file(self):
        """Test extraction from nonexistent file."""
        extractor = MetadataExtractor()
        
        with pytest.raises(FileNotFoundError):
            extractor.extract('/nonexistent/file.txt')
    
    def test_convenience_function(self):
        """Test extract_metadata convenience function."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test content")
            temp_path = f.name
        
        try:
            metadata = extract_metadata(temp_path)
            
            assert metadata is not None
            assert 'file' in metadata
            assert 'hashes' in metadata
            
        finally:
            Path(temp_path).unlink()


class TestMetadataIntegration:
    """Test metadata extractor integration."""
    
    def test_with_different_file_types(self):
        """Test metadata extraction for different file types."""
        test_files = [
            ('test.txt', 'text content'),
            ('test.json', '{"key": "value"}'),
            ('test.md', '# Markdown'),
        ]
        
        files_created = []
        try:
            for filename, content in test_files:
                with tempfile.NamedTemporaryFile(
                    mode='w', 
                    suffix=Path(filename).suffix, 
                    delete=False
                ) as f:
                    f.write(content)
                    files_created.append(f.name)
            
            extractor = MetadataExtractor()
            
            for file_path in files_created:
                metadata = extractor.extract(file_path)
                assert metadata is not None
                assert metadata['file']['size'] > 0
                assert len(metadata['hashes']['md5']) == 32
        
        finally:
            for file_path in files_created:
                Path(file_path).unlink(missing_ok=True)
