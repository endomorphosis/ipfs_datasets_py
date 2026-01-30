"""
Tests for format detection utilities.

Tests native MIME type detection, magic number detection,
and content analysis.
"""

import pytest
import tempfile
from pathlib import Path

from ipfs_datasets_py.file_converter.format_detector import (
    FormatDetector,
    detect_format,
    EXTENSION_MIME_TYPES,
    MAGIC_SIGNATURES,
)


class TestFormatDetectorBasics:
    """Test basic FormatDetector functionality."""
    
    def test_initialization(self):
        """Test detector initialization."""
        detector = FormatDetector()
        assert detector is not None
    
    def test_initialization_no_magic(self):
        """Test detector without magic library."""
        detector = FormatDetector(use_magic=False)
        assert detector is not None
        assert not detector._magic_available


class TestExtensionDetection:
    """Test extension-based MIME type detection."""
    
    @pytest.fixture
    def detector(self):
        return FormatDetector(use_magic=False)  # Force native detection
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_text_file_extension(self, detector, temp_dir):
        """Test .txt file detection."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("Plain text content")
        
        mime_type = detector.detect_file(test_file)
        assert mime_type == 'text/plain'
    
    def test_markdown_extension(self, detector, temp_dir):
        """Test .md file detection."""
        test_file = temp_dir / "test.md"
        test_file.write_text("# Markdown")
        
        mime_type = detector.detect_file(test_file)
        assert mime_type == 'text/markdown'
    
    def test_json_extension(self, detector, temp_dir):
        """Test .json file detection."""
        test_file = temp_dir / "test.json"
        test_file.write_text('{"key": "value"}')
        
        mime_type = detector.detect_file(test_file)
        assert mime_type == 'application/json'
    
    def test_html_extension(self, detector, temp_dir):
        """Test .html file detection."""
        test_file = temp_dir / "test.html"
        test_file.write_text("<html><body>Content</body></html>")
        
        mime_type = detector.detect_file(test_file)
        assert mime_type == 'text/html'
    
    def test_csv_extension(self, detector, temp_dir):
        """Test .csv file detection."""
        test_file = temp_dir / "test.csv"
        test_file.write_text("name,age\nAlice,30")
        
        mime_type = detector.detect_file(test_file)
        assert mime_type == 'text/csv'


class TestMagicNumberDetection:
    """Test magic number (file signature) detection."""
    
    @pytest.fixture
    def detector(self):
        return FormatDetector(use_magic=False)
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_pdf_signature(self, detector, temp_dir):
        """Test PDF signature detection."""
        test_file = temp_dir / "test.pdf"
        # Write PDF signature
        test_file.write_bytes(b'%PDF-1.4\n')
        
        mime_type = detector.detect_file(test_file)
        assert mime_type == 'application/pdf'
    
    def test_jpeg_signature(self, detector, temp_dir):
        """Test JPEG signature detection."""
        test_file = temp_dir / "test.jpg"
        # Write JPEG signature
        test_file.write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 10)
        
        mime_type = detector.detect_file(test_file)
        assert mime_type == 'image/jpeg'
    
    def test_png_signature(self, detector, temp_dir):
        """Test PNG signature detection."""
        test_file = temp_dir / "test.png"
        # Write PNG signature
        test_file.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 10)
        
        mime_type = detector.detect_file(test_file)
        assert mime_type == 'image/png'
    
    def test_gif_signature(self, detector, temp_dir):
        """Test GIF signature detection."""
        test_file = temp_dir / "test.gif"
        # Write GIF signature
        test_file.write_bytes(b'GIF89a' + b'\x00' * 10)
        
        mime_type = detector.detect_file(test_file)
        assert mime_type == 'image/gif'


class TestContentAnalysis:
    """Test content-based format detection."""
    
    @pytest.fixture
    def detector(self):
        return FormatDetector(use_magic=False)
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_xml_content_detection(self, detector, temp_dir):
        """Test XML detection by content."""
        test_file = temp_dir / "test.unknown"
        test_file.write_text('<?xml version="1.0"?><data><item>value</item></data>')
        
        mime_type = detector.detect_file(test_file)
        assert mime_type == 'application/xml'
    
    def test_html_content_detection(self, detector, temp_dir):
        """Test HTML detection by content."""
        test_file = temp_dir / "test.unknown"
        test_file.write_text('<!DOCTYPE html><html><body></body></html>')
        
        mime_type = detector.detect_file(test_file)
        assert mime_type == 'text/html'
    
    def test_json_content_detection(self, detector, temp_dir):
        """Test JSON detection by content."""
        test_file = temp_dir / "test.unknown"
        test_file.write_text('{"key": "value", "number": 42}')
        
        mime_type = detector.detect_file(test_file)
        assert mime_type == 'application/json'


class TestCategoryDetection:
    """Test MIME type categorization."""
    
    @pytest.fixture
    def detector(self):
        return FormatDetector()
    
    def test_text_category(self, detector):
        """Test text category detection."""
        assert detector.get_category('text/plain') == 'text'
        assert detector.get_category('text/html') == 'text'
        assert detector.get_category('text/markdown') == 'text'
    
    def test_image_category(self, detector):
        """Test image category detection."""
        assert detector.get_category('image/jpeg') == 'image'
        assert detector.get_category('image/png') == 'image'
        assert detector.get_category('image/gif') == 'image'
    
    def test_audio_category(self, detector):
        """Test audio category detection."""
        assert detector.get_category('audio/mpeg') == 'audio'
        assert detector.get_category('audio/wav') == 'audio'
    
    def test_video_category(self, detector):
        """Test video category detection."""
        assert detector.get_category('video/mp4') == 'video'
        assert detector.get_category('video/webm') == 'video'
    
    def test_document_category(self, detector):
        """Test document category detection."""
        assert detector.get_category('application/pdf') == 'document'


class TestExtensionLookup:
    """Test MIME type to extension lookup."""
    
    @pytest.fixture
    def detector(self):
        return FormatDetector()
    
    def test_get_extension_jpeg(self, detector):
        """Test getting extension for JPEG."""
        ext = detector.get_extension('image/jpeg')
        assert ext == '.jpg'
    
    def test_get_extension_pdf(self, detector):
        """Test getting extension for PDF."""
        ext = detector.get_extension('application/pdf')
        assert ext == '.pdf'
    
    def test_get_extension_unknown(self, detector):
        """Test getting extension for unknown type."""
        ext = detector.get_extension('application/unknown')
        assert ext is None


class TestSupportCheck:
    """Test format support checking."""
    
    @pytest.fixture
    def detector(self):
        return FormatDetector(use_magic=False)
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_supported_format(self, detector, temp_dir):
        """Test checking if format is supported."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("Content")
        
        assert detector.is_supported(test_file)
    
    def test_unsupported_format(self, detector, temp_dir):
        """Test checking unsupported format."""
        test_file = temp_dir / "test.xyz"
        test_file.write_bytes(b'\x00\x01\x02\x03')
        
        # Should return False for completely unknown format
        # (though it might detect as binary or fallback)
        result = detector.is_supported(test_file)
        # Just check it doesn't crash
        assert isinstance(result, bool)


class TestConvenienceFunction:
    """Test convenience function."""
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_detect_format_function(self, temp_dir):
        """Test detect_format convenience function."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("Content")
        
        mime_type = detect_format(test_file)
        assert mime_type == 'text/plain'


class TestErrorHandling:
    """Test error handling in format detection."""
    
    @pytest.fixture
    def detector(self):
        return FormatDetector()
    
    def test_nonexistent_file(self, detector):
        """Test handling of nonexistent file."""
        mime_type = detector.detect_file('nonexistent.txt')
        assert mime_type is None
    
    def test_directory(self, detector):
        """Test handling of directory instead of file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Directories might fail or return None
            mime_type = detector.detect_file(tmpdir)
            # Just check it doesn't crash
            assert mime_type is None or isinstance(mime_type, str)


class TestExtensionMimeTypeMap:
    """Test completeness of extension map."""
    
    def test_common_extensions_exist(self):
        """Test that common extensions are in the map."""
        common = ['.txt', '.pdf', '.jpg', '.png', '.mp3', '.mp4', 
                  '.html', '.json', '.csv', '.docx', '.xlsx']
        
        for ext in common:
            assert ext in EXTENSION_MIME_TYPES, f"{ext} missing from map"
    
    def test_mime_types_valid(self):
        """Test that MIME types are properly formatted."""
        for mime_type in EXTENSION_MIME_TYPES.values():
            assert '/' in mime_type, f"Invalid MIME type: {mime_type}"
            parts = mime_type.split('/')
            assert len(parts) == 2, f"Invalid MIME type format: {mime_type}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
