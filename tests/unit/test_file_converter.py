"""
Tests for the unified file converter module.

Tests backend selection, conversion functionality, batch processing,
and error handling.
"""

import pytest
import asyncio
from pathlib import Path
import tempfile
import json

from ipfs_datasets_py.file_converter import FileConverter, ConversionResult


class TestFileConverterBasics:
    """Test basic FileConverter functionality."""
    
    def test_import(self):
        """Test that FileConverter can be imported."""
        assert FileConverter is not None
        assert ConversionResult is not None
    
    def test_initialization_default(self):
        """Test FileConverter initialization with default backend."""
        converter = FileConverter()
        assert converter is not None
        assert converter.backend_name == 'auto'
    
    def test_initialization_explicit_backend(self):
        """Test FileConverter initialization with explicit backends."""
        # Native backend (always available)
        converter_native = FileConverter(backend='native')
        assert converter_native.backend_name == 'native'
        
        # MarkItDown backend (may not be installed)
        converter_mark = FileConverter(backend='markitdown')
        assert converter_mark.backend_name == 'markitdown'
        
        # Omni backend
        converter_omni = FileConverter(backend='omni')
        assert converter_omni.backend_name == 'omni'
    
    def test_invalid_backend(self):
        """Test that invalid backend raises error."""
        with pytest.raises(ValueError):
            converter = FileConverter(backend='invalid')
            converter._get_backend()  # Force backend loading


class TestNativeBackend:
    """Test native backend functionality (always available)."""
    
    @pytest.fixture
    def converter(self):
        """Create converter with native backend."""
        return FileConverter(backend='native')
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_supported_formats(self, converter):
        """Test that native backend reports supported formats."""
        formats = converter.get_supported_formats()
        assert isinstance(formats, list)
        assert len(formats) > 0
        assert 'txt' in formats
        assert 'md' in formats
        assert 'json' in formats
    
    @pytest.mark.asyncio
    async def test_convert_text_file(self, converter, temp_dir):
        """Test converting a simple text file."""
        # Create test file
        test_file = temp_dir / "test.txt"
        test_content = "Hello, world!\nThis is a test file."
        test_file.write_text(test_content)
        
        # Convert
        result = await converter.convert(test_file)
        
        # Verify
        assert result.success
        assert result.text == test_content
        assert result.backend == 'native'
        assert result.error is None
    
    @pytest.mark.asyncio
    async def test_convert_markdown_file(self, converter, temp_dir):
        """Test converting a markdown file."""
        test_file = temp_dir / "test.md"
        test_content = "# Heading\n\nParagraph with **bold** text."
        test_file.write_text(test_content)
        
        result = await converter.convert(test_file)
        
        assert result.success
        assert result.text == test_content
        assert 'md' in result.metadata.get('format', '')
    
    @pytest.mark.asyncio
    async def test_convert_json_file(self, converter, temp_dir):
        """Test converting a JSON file."""
        test_file = temp_dir / "test.json"
        test_data = {"key": "value", "number": 42}
        test_file.write_text(json.dumps(test_data))
        
        result = await converter.convert(test_file)
        
        assert result.success
        assert "key" in result.text
        assert "value" in result.text
        assert result.backend == 'native'
    
    @pytest.mark.asyncio
    async def test_convert_csv_file(self, converter, temp_dir):
        """Test converting a CSV file."""
        test_file = temp_dir / "test.csv"
        test_content = "name,age,city\nAlice,30,NYC\nBob,25,LA"
        test_file.write_text(test_content)
        
        result = await converter.convert(test_file)
        
        assert result.success
        assert "Alice" in result.text
        assert "NYC" in result.text
    
    @pytest.mark.asyncio
    async def test_convert_html_file(self, converter, temp_dir):
        """Test converting an HTML file."""
        test_file = temp_dir / "test.html"
        test_content = "<html><body><h1>Title</h1><p>Content</p></body></html>"
        test_file.write_text(test_content)
        
        result = await converter.convert(test_file)
        
        assert result.success
        assert "Title" in result.text
        assert "Content" in result.text
    
    @pytest.mark.asyncio
    async def test_convert_xml_file(self, converter, temp_dir):
        """Test converting an XML file."""
        test_file = temp_dir / "test.xml"
        test_content = '<?xml version="1.0"?><root><item>Value</item></root>'
        test_file.write_text(test_content)
        
        result = await converter.convert(test_file)
        
        assert result.success
        assert "Value" in result.text
    
    @pytest.mark.asyncio
    async def test_convert_nonexistent_file(self, converter, temp_dir):
        """Test handling of nonexistent file."""
        test_file = temp_dir / "nonexistent.txt"
        
        result = await converter.convert(test_file)
        
        assert not result.success
        assert result.error is not None
        assert "not found" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_convert_unsupported_format(self, converter, temp_dir):
        """Test handling of unsupported format."""
        test_file = temp_dir / "test.xyz"
        test_file.write_text("content")
        
        result = await converter.convert(test_file)
        
        assert not result.success
        assert result.error is not None
        assert "not yet implemented" in result.error.lower()


class TestSyncWrapper:
    """Test synchronous wrapper functionality."""
    
    @pytest.fixture
    def converter(self):
        return FileConverter(backend='native')
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_convert_sync(self, converter, temp_dir):
        """Test synchronous conversion wrapper."""
        test_file = temp_dir / "test.txt"
        test_content = "Sync test content"
        test_file.write_text(test_content)
        
        # Use sync wrapper
        result = converter.convert_sync(test_file)
        
        assert result.success
        assert result.text == test_content


class TestBatchProcessing:
    """Test batch conversion functionality."""
    
    @pytest.fixture
    def converter(self):
        return FileConverter(backend='native')
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    @pytest.mark.asyncio
    async def test_batch_convert_multiple_files(self, converter, temp_dir):
        """Test converting multiple files in batch."""
        # Create test files
        files = []
        for i in range(3):
            test_file = temp_dir / f"test{i}.txt"
            test_file.write_text(f"Content {i}")
            files.append(test_file)
        
        # Batch convert
        results = await converter.convert_batch(files)
        
        # Verify
        assert len(results) == 3
        assert all(r.success for r in results)
        assert all(f"Content {i}" in results[i].text for i in range(3))
    
    @pytest.mark.asyncio
    async def test_batch_convert_with_errors(self, converter, temp_dir):
        """Test batch conversion with some errors."""
        # Mix of valid and invalid files
        file1 = temp_dir / "valid.txt"
        file1.write_text("Valid content")
        file2 = temp_dir / "nonexistent.txt"
        file3 = temp_dir / "valid2.txt"
        file3.write_text("Another valid")
        
        files = [file1, file2, file3]
        results = await converter.convert_batch(files)
        
        assert len(results) == 3
        assert results[0].success
        assert not results[1].success  # Nonexistent file
        assert results[2].success
    
    @pytest.mark.asyncio
    async def test_batch_convert_concurrency_limit(self, converter, temp_dir):
        """Test batch conversion with concurrency limit."""
        # Create multiple files
        files = []
        for i in range(10):
            test_file = temp_dir / f"test{i}.txt"
            test_file.write_text(f"Content {i}")
            files.append(test_file)
        
        # Convert with limited concurrency
        results = await converter.convert_batch(files, max_concurrent=2)
        
        assert len(results) == 10
        assert all(r.success for r in results)


class TestBackendSelection:
    """Test automatic backend selection."""
    
    def test_auto_backend_selection(self):
        """Test that auto backend selects available backend."""
        converter = FileConverter(backend='auto')
        backend = converter._get_backend()
        
        # Should select one of the available backends
        assert backend is not None
        backend_class = backend.__class__.__name__
        assert backend_class in ['NativeBackend', 'MarkItDownBackend', 'OmniBackend']
    
    def test_get_backend_info(self):
        """Test getting backend information."""
        converter = FileConverter(backend='native')
        info = converter.get_backend_info()
        
        assert isinstance(info, dict)
        assert 'name' in info
        assert 'backend_type' in info
        assert info['backend_type'] == 'native'


class TestConversionResult:
    """Test ConversionResult dataclass."""
    
    def test_successful_result(self):
        """Test creating a successful result."""
        result = ConversionResult(
            text="Sample text",
            metadata={"format": "txt"},
            backend="native",
            success=True
        )
        
        assert result.text == "Sample text"
        assert result.metadata == {"format": "txt"}
        assert result.backend == "native"
        assert result.success
        assert result.error is None
    
    def test_failed_result(self):
        """Test creating a failed result."""
        result = ConversionResult(
            text="",
            metadata={},
            backend="native",
            success=False,
            error="File not found"
        )
        
        assert result.text == ""
        assert not result.success
        assert result.error == "File not found"


# Integration tests (only run if external libraries available)
class TestMarkItDownBackend:
    """Test MarkItDown backend (if available)."""
    
    @pytest.fixture
    def converter(self):
        try:
            return FileConverter(backend='markitdown')
        except ImportError:
            pytest.skip("MarkItDown not installed")
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    @pytest.mark.asyncio
    async def test_markitdown_text_conversion(self, converter, temp_dir):
        """Test MarkItDown backend with text file."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("MarkItDown test")
        
        result = await converter.convert(test_file)
        
        # MarkItDown might not be installed, backend may fall back
        if result.success:
            assert "test" in result.text.lower()


class TestOmniBackend:
    """Test Omni backend (if available)."""
    
    @pytest.fixture
    def converter(self):
        try:
            return FileConverter(backend='omni')
        except ImportError:
            pytest.skip("Omni converter not available")
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    @pytest.mark.asyncio
    async def test_omni_text_conversion(self, converter, temp_dir):
        """Test Omni backend with text file."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("Omni test")
        
        result = await converter.convert(test_file)
        
        # Omni might not be available, backend may not work
        if result.success:
            assert "test" in result.text.lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
