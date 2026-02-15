"""Tests for InputDetector.

This module tests the input detection and classification system.
"""

import pytest
import os
import tempfile
from pathlib import Path

from ipfs_datasets_py.processors.core import (
    InputDetector,
    detect_input,
    detect_format,
    InputType,
    ProcessingContext,
)


class TestInputDetector:
    """Tests for InputDetector class."""
    
    def test_init(self):
        """Test detector initialization.
        
        GIVEN: InputDetector class
        WHEN: Creating detector
        THEN: Detector is created successfully
        """
        detector = InputDetector()
        assert detector is not None
    
    def test_detect_none_raises_error(self):
        """Test that None input raises error.
        
        GIVEN: None input
        WHEN: Calling detect()
        THEN: ValueError is raised
        """
        detector = InputDetector()
        with pytest.raises(ValueError, match="cannot be None"):
            detector.detect(None)


class TestURLDetection:
    """Tests for URL detection."""
    
    def test_detect_http_url(self):
        """Test detecting HTTP URL.
        
        GIVEN: HTTP URL string
        WHEN: Detecting input type
        THEN: Classified as URL with correct metadata
        """
        detector = InputDetector()
        context = detector.detect("https://example.com/page.html")
        
        assert context.input_type == InputType.URL
        assert context.metadata['scheme'] == 'https'
        assert context.metadata['netloc'] == 'example.com'
        assert context.metadata['format'] == 'html'
    
    def test_detect_http_without_extension(self):
        """Test detecting HTTP URL without extension.
        
        GIVEN: HTTP URL without file extension
        WHEN: Detecting input type
        THEN: Classified as URL
        """
        detector = InputDetector()
        context = detector.detect("http://example.com/path")
        
        assert context.input_type == InputType.URL
        assert context.metadata['scheme'] == 'http'
    
    def test_detect_ipfs_protocol_url(self):
        """Test detecting IPFS protocol URL.
        
        GIVEN: IPFS protocol URL
        WHEN: Detecting input type
        THEN: Classified as IPFS_CID
        """
        detector = InputDetector()
        context = detector.detect("ipfs://QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG")
        
        assert context.input_type == InputType.IPFS_CID
        assert 'cid' in context.metadata
        assert context.metadata['protocol'] == 'ipfs'
    
    def test_detect_ipfs_path_url(self):
        """Test detecting IPFS path URL.
        
        GIVEN: IPFS path format URL
        WHEN: Detecting input type
        THEN: Classified as IPFS_CID
        """
        detector = InputDetector()
        context = detector.detect("/ipfs/QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG")
        
        assert context.input_type == InputType.IPFS_CID
        assert 'cid' in context.metadata
        assert context.metadata['path_format'] == '/ipfs/'
    
    def test_detect_bare_cid(self):
        """Test detecting bare IPFS CID.
        
        GIVEN: Bare IPFS CID (no protocol)
        WHEN: Detecting input type
        THEN: Classified as IPFS_CID
        """
        detector = InputDetector()
        context = detector.detect("QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG")
        
        assert context.input_type == InputType.IPFS_CID
        assert context.metadata['cid'] == "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG"
    
    def test_detect_ipns_protocol(self):
        """Test detecting IPNS protocol URL.
        
        GIVEN: IPNS protocol URL
        WHEN: Detecting input type
        THEN: Classified as IPNS
        """
        detector = InputDetector()
        context = detector.detect("ipns://example.com")
        
        assert context.input_type == InputType.IPNS
        assert context.metadata['name'] == 'example.com'
        assert context.metadata['protocol'] == 'ipns'
    
    def test_detect_ipns_path(self):
        """Test detecting IPNS path URL.
        
        GIVEN: IPNS path format URL
        WHEN: Detecting input type
        THEN: Classified as IPNS
        """
        detector = InputDetector()
        context = detector.detect("/ipns/example.com")
        
        assert context.input_type == InputType.IPNS
        assert context.metadata['name'] == 'example.com'


class TestFileDetection:
    """Tests for file detection."""
    
    def test_detect_existing_file(self):
        """Test detecting existing file.
        
        GIVEN: Path to existing file
        WHEN: Detecting input type
        THEN: Classified as FILE with metadata
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("test content")
            temp_path = f.name
        
        try:
            detector = InputDetector()
            context = detector.detect(temp_path)
            
            assert context.input_type == InputType.FILE
            assert context.metadata['format'] == 'txt'
            assert context.metadata['extension'] == 'txt'
            assert 'size' in context.metadata
            assert context.metadata['filename'].endswith('.txt')
        finally:
            os.unlink(temp_path)
    
    def test_detect_pdf_file(self):
        """Test detecting PDF file with magic bytes.
        
        GIVEN: PDF file with magic bytes
        WHEN: Detecting input type
        THEN: Format detected as PDF
        """
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.pdf', delete=False) as f:
            f.write(b'%PDF-1.4\n')  # PDF magic bytes
            temp_path = f.name
        
        try:
            detector = InputDetector()
            context = detector.detect(temp_path)
            
            assert context.input_type == InputType.FILE
            assert context.metadata['format'] == 'pdf'
            assert context.metadata.get('format_from_magic') == 'pdf'
        finally:
            os.unlink(temp_path)
    
    def test_detect_file_no_extension(self):
        """Test detecting file without extension.
        
        GIVEN: File path without extension
        WHEN: Detecting input type
        THEN: Classified as FILE
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='', delete=False) as f:
            f.write("test")
            temp_path = f.name
        
        try:
            detector = InputDetector()
            context = detector.detect(temp_path)
            
            assert context.input_type == InputType.FILE
            assert 'size' in context.metadata
        finally:
            os.unlink(temp_path)


class TestFolderDetection:
    """Tests for folder detection."""
    
    def test_detect_existing_folder(self):
        """Test detecting existing folder.
        
        GIVEN: Path to existing folder
        WHEN: Detecting input type
        THEN: Classified as FOLDER with metadata
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            detector = InputDetector()
            context = detector.detect(temp_dir)
            
            assert context.input_type == InputType.FOLDER
            assert context.metadata['format'] == 'folder'
            assert 'file_count' in context.metadata
    
    def test_detect_folder_with_files(self):
        """Test detecting folder with files.
        
        GIVEN: Folder with multiple files
        WHEN: Detecting input type
        THEN: File count is included in metadata
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create some files
            for i in range(3):
                Path(temp_dir, f'file{i}.txt').write_text(f'content {i}')
            
            detector = InputDetector()
            context = detector.detect(temp_dir)
            
            assert context.input_type == InputType.FOLDER
            assert context.metadata['file_count'] == 3
            assert 'files' in context.metadata


class TestTextDetection:
    """Tests for text detection."""
    
    def test_detect_text_string(self):
        """Test detecting plain text.
        
        GIVEN: Text string
        WHEN: Detecting input type
        THEN: Classified as TEXT
        """
        detector = InputDetector()
        context = detector.detect("This is some text content")
        
        assert context.input_type == InputType.TEXT
        assert context.metadata['format'] == 'text'
        assert context.metadata['length'] == 25
    
    def test_detect_empty_string_as_text(self):
        """Test detecting empty string.
        
        GIVEN: Empty string
        WHEN: Detecting input type
        THEN: Classified as TEXT
        """
        detector = InputDetector()
        context = detector.detect("")
        
        assert context.input_type == InputType.TEXT
        assert context.metadata['length'] == 0


class TestBinaryDetection:
    """Tests for binary data detection."""
    
    def test_detect_binary_bytes(self):
        """Test detecting binary data.
        
        GIVEN: Binary bytes
        WHEN: Detecting input type
        THEN: Classified as BINARY
        """
        detector = InputDetector()
        data = b'\x00\x01\x02\x03\x04'
        context = detector.detect(data)
        
        assert context.input_type == InputType.BINARY
        assert context.metadata['size'] == 5
    
    def test_detect_pdf_bytes(self):
        """Test detecting PDF from bytes.
        
        GIVEN: Binary data with PDF magic bytes
        WHEN: Detecting input type
        THEN: Format detected as PDF
        """
        detector = InputDetector()
        data = b'%PDF-1.4\nsome pdf content'
        context = detector.detect(data)
        
        assert context.input_type == InputType.BINARY
        assert context.metadata['format'] == 'pdf'


class TestFormatDetection:
    """Tests for format detection from magic bytes."""
    
    def test_detect_pdf_magic(self):
        """Test PDF magic bytes detection.
        
        GIVEN: File with PDF magic bytes
        WHEN: Detecting format
        THEN: Returns 'pdf'
        """
        with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f:
            f.write(b'%PDF-1.4\n')
            temp_path = f.name
        
        try:
            detector = InputDetector()
            format = detector.detect_format(temp_path)
            assert format == 'pdf'
        finally:
            os.unlink(temp_path)
    
    def test_detect_png_magic(self):
        """Test PNG magic bytes detection.
        
        GIVEN: File with PNG magic bytes
        WHEN: Detecting format
        THEN: Returns 'png'
        """
        with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f:
            f.write(b'\x89PNG\r\n\x1a\n')
            temp_path = f.name
        
        try:
            detector = InputDetector()
            format = detector.detect_format(temp_path)
            assert format == 'png'
        finally:
            os.unlink(temp_path)
    
    def test_detect_no_magic_bytes(self):
        """Test file with no recognized magic bytes.
        
        GIVEN: File with unrecognized content
        WHEN: Detecting format
        THEN: Returns None
        """
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("plain text")
            temp_path = f.name
        
        try:
            detector = InputDetector()
            format = detector.detect_format(temp_path)
            # Plain text has no magic bytes
            assert format is None
        finally:
            os.unlink(temp_path)


class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    def test_detect_input_function(self):
        """Test detect_input convenience function.
        
        GIVEN: Input data
        WHEN: Using detect_input() function
        THEN: Returns ProcessingContext
        """
        context = detect_input("https://example.com")
        
        assert isinstance(context, ProcessingContext)
        assert context.input_type == InputType.URL
    
    def test_detect_format_function(self):
        """Test detect_format convenience function.
        
        GIVEN: File with magic bytes
        WHEN: Using detect_format() function
        THEN: Returns format string
        """
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.pdf', delete=False) as f:
            f.write(b'%PDF-1.4\n')
            temp_path = f.name
        
        try:
            format = detect_format(temp_path)
            assert format == 'pdf'
        finally:
            os.unlink(temp_path)


class TestMetadataExtraction:
    """Tests for metadata extraction."""
    
    def test_extract_metadata_from_url(self):
        """Test extracting metadata from URL.
        
        GIVEN: URL input
        WHEN: Extracting metadata
        THEN: Returns metadata dict
        """
        detector = InputDetector()
        metadata = detector.extract_metadata("https://example.com/page.html")
        
        assert 'scheme' in metadata
        assert metadata['scheme'] == 'https'
        assert metadata['format'] == 'html'
    
    def test_extract_metadata_from_file(self):
        """Test extracting metadata from file.
        
        GIVEN: File input
        WHEN: Extracting metadata
        THEN: Returns file metadata
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("test")
            temp_path = f.name
        
        try:
            detector = InputDetector()
            metadata = detector.extract_metadata(temp_path)
            
            assert 'size' in metadata
            assert metadata['format'] == 'txt'
        finally:
            os.unlink(temp_path)


class TestSessionID:
    """Tests for session ID generation."""
    
    def test_auto_generate_session_id(self):
        """Test automatic session ID generation.
        
        GIVEN: Input without session_id option
        WHEN: Detecting input
        THEN: Session ID is auto-generated
        """
        detector = InputDetector()
        context = detector.detect("test text")
        
        assert context.session_id is not None
        assert len(context.session_id) > 0
    
    def test_custom_session_id(self):
        """Test providing custom session ID.
        
        GIVEN: Input with session_id option
        WHEN: Detecting input
        THEN: Custom session ID is used
        """
        detector = InputDetector()
        context = detector.detect("test text", session_id="custom-123")
        
        assert context.session_id == "custom-123"
