"""
Tests for enhanced text extractors.

Tests PDF, DOCX, XLSX, and HTML extraction with fallback handling.
"""

import pytest
import tempfile
from pathlib import Path

from ipfs_datasets_py.file_converter.text_extractors import (
    PDFExtractor,
    DOCXExtractor,
    XLSXExtractor,
    HTMLExtractor,
    ExtractorRegistry,
    extract_text,
    ExtractionResult,
)


class TestExtractionResult:
    """Test ExtractionResult dataclass."""
    
    def test_successful_result(self):
        """Test creating successful result."""
        result = ExtractionResult(
            text="Sample text",
            metadata={"pages": 1},
            success=True
        )
        
        assert result.text == "Sample text"
        assert result.metadata == {"pages": 1}
        assert result.success
        assert result.error is None
    
    def test_failed_result(self):
        """Test creating failed result."""
        result = ExtractionResult(
            text="",
            success=False,
            error="Extraction failed"
        )
        
        assert result.text == ""
        assert not result.success
        assert result.error == "Extraction failed"


class TestPDFExtractor:
    """Test PDF extraction."""
    
    @pytest.fixture
    def extractor(self):
        return PDFExtractor()
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_initialization(self, extractor):
        """Test extractor initialization."""
        assert extractor is not None
        # At least one method should be available or both False
        assert isinstance(extractor.pdfplumber_available, bool)
        assert isinstance(extractor.pypdf2_available, bool)
    
    def test_supported_formats(self, extractor):
        """Test supported formats list."""
        formats = extractor.supported_formats
        assert 'application/pdf' in formats
    
    def test_can_extract_pdf(self, extractor, temp_dir):
        """Test can_extract for PDF file."""
        if not (extractor.pdfplumber_available or extractor.pypdf2_available):
            pytest.skip("No PDF libraries available")
        
        pdf_file = temp_dir / "test.pdf"
        pdf_file.write_bytes(b'%PDF-1.4\n')  # Minimal PDF signature
        
        assert extractor.can_extract(pdf_file)
    
    def test_cannot_extract_non_pdf(self, extractor, temp_dir):
        """Test can_extract returns False for non-PDF."""
        txt_file = temp_dir / "test.txt"
        txt_file.write_text("Not a PDF")
        
        assert not extractor.can_extract(txt_file)
    
    def test_extract_no_libraries(self, extractor, temp_dir):
        """Test extraction when no libraries available."""
        # Temporarily disable libraries
        original_plumber = extractor.pdfplumber_available
        original_pypdf2 = extractor.pypdf2_available
        
        extractor.pdfplumber_available = False
        extractor.pypdf2_available = False
        
        pdf_file = temp_dir / "test.pdf"
        pdf_file.write_bytes(b'%PDF-1.4\n')
        
        result = extractor.extract(pdf_file)
        
        # Restore
        extractor.pdfplumber_available = original_plumber
        extractor.pypdf2_available = original_pypdf2
        
        assert not result.success
        assert "available" in result.error.lower()


class TestDOCXExtractor:
    """Test DOCX extraction."""
    
    @pytest.fixture
    def extractor(self):
        return DOCXExtractor()
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_initialization(self, extractor):
        """Test extractor initialization."""
        assert extractor is not None
        assert isinstance(extractor.docx_available, bool)
    
    def test_supported_formats(self, extractor):
        """Test supported formats list."""
        formats = extractor.supported_formats
        assert 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' in formats
    
    def test_can_extract_docx(self, extractor, temp_dir):
        """Test can_extract for DOCX file."""
        if not extractor.docx_available:
            pytest.skip("python-docx not available")
        
        docx_file = temp_dir / "test.docx"
        docx_file.write_bytes(b'PK\x03\x04')  # ZIP signature (DOCX is ZIP-based)
        
        assert extractor.can_extract(docx_file)
    
    def test_cannot_extract_non_docx(self, extractor, temp_dir):
        """Test can_extract returns False for non-DOCX."""
        txt_file = temp_dir / "test.txt"
        txt_file.write_text("Not a DOCX")
        
        assert not extractor.can_extract(txt_file)
    
    def test_extract_no_library(self, extractor, temp_dir):
        """Test extraction when library not available."""
        original = extractor.docx_available
        extractor.docx_available = False
        
        docx_file = temp_dir / "test.docx"
        docx_file.write_bytes(b'PK\x03\x04')
        
        result = extractor.extract(docx_file)
        
        extractor.docx_available = original
        
        assert not result.success
        assert "python-docx" in result.error


class TestXLSXExtractor:
    """Test XLSX extraction."""
    
    @pytest.fixture
    def extractor(self):
        return XLSXExtractor()
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_initialization(self, extractor):
        """Test extractor initialization."""
        assert extractor is not None
        assert isinstance(extractor.openpyxl_available, bool)
    
    def test_supported_formats(self, extractor):
        """Test supported formats list."""
        formats = extractor.supported_formats
        assert 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' in formats
    
    def test_can_extract_xlsx(self, extractor, temp_dir):
        """Test can_extract for XLSX file."""
        if not extractor.openpyxl_available:
            pytest.skip("openpyxl not available")
        
        xlsx_file = temp_dir / "test.xlsx"
        xlsx_file.write_bytes(b'PK\x03\x04')  # ZIP signature
        
        assert extractor.can_extract(xlsx_file)
    
    def test_cannot_extract_non_xlsx(self, extractor, temp_dir):
        """Test can_extract returns False for non-XLSX."""
        txt_file = temp_dir / "test.txt"
        txt_file.write_text("Not XLSX")
        
        assert not extractor.can_extract(txt_file)
    
    def test_extract_no_library(self, extractor, temp_dir):
        """Test extraction when library not available."""
        original = extractor.openpyxl_available
        extractor.openpyxl_available = False
        
        xlsx_file = temp_dir / "test.xlsx"
        xlsx_file.write_bytes(b'PK\x03\x04')
        
        result = extractor.extract(xlsx_file)
        
        extractor.openpyxl_available = original
        
        assert not result.success
        assert "openpyxl" in result.error


class TestHTMLExtractor:
    """Test HTML extraction."""
    
    @pytest.fixture
    def extractor(self):
        return HTMLExtractor()
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_initialization(self, extractor):
        """Test extractor initialization."""
        assert extractor is not None
        assert isinstance(extractor.bs4_available, bool)
    
    def test_supported_formats(self, extractor):
        """Test supported formats list."""
        formats = extractor.supported_formats
        assert 'text/html' in formats
    
    def test_can_extract_html(self, extractor, temp_dir):
        """Test can_extract for HTML file."""
        html_file = temp_dir / "test.html"
        html_file.write_text("<html><body>Test</body></html>")
        
        assert extractor.can_extract(html_file)
    
    def test_can_extract_htm(self, extractor, temp_dir):
        """Test can_extract for .htm file."""
        htm_file = temp_dir / "test.htm"
        htm_file.write_text("<html><body>Test</body></html>")
        
        assert extractor.can_extract(htm_file)
    
    def test_cannot_extract_non_html(self, extractor, temp_dir):
        """Test can_extract returns False for non-HTML."""
        txt_file = temp_dir / "test.txt"
        txt_file.write_text("Not HTML")
        
        assert not extractor.can_extract(txt_file)
    
    def test_extract_basic_html(self, extractor, temp_dir):
        """Test basic HTML extraction."""
        html_file = temp_dir / "test.html"
        html_content = "<html><body><h1>Title</h1><p>Paragraph</p></body></html>"
        html_file.write_text(html_content)
        
        result = extractor.extract(html_file)
        
        assert result.success
        assert "Title" in result.text
        assert "Paragraph" in result.text
    
    def test_extract_with_script_tags(self, extractor, temp_dir):
        """Test that script tags are removed."""
        html_file = temp_dir / "test.html"
        html_content = """
        <html>
        <head><script>alert('test');</script></head>
        <body>
            <p>Content</p>
            <script>console.log('test');</script>
        </body>
        </html>
        """
        html_file.write_text(html_content)
        
        result = extractor.extract(html_file)
        
        assert result.success
        assert "Content" in result.text
        # Script content should be removed
        assert "alert" not in result.text
        assert "console.log" not in result.text
    
    def test_extract_with_style_tags(self, extractor, temp_dir):
        """Test that style tags are removed."""
        html_file = temp_dir / "test.html"
        html_content = """
        <html>
        <head><style>body { color: red; }</style></head>
        <body><p>Content</p></body>
        </html>
        """
        html_file.write_text(html_content)
        
        result = extractor.extract(html_file)
        
        assert result.success
        assert "Content" in result.text
        # Style content should be removed
        assert "color: red" not in result.text


class TestExtractorRegistry:
    """Test extractor registry."""
    
    @pytest.fixture
    def registry(self):
        return ExtractorRegistry()
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_initialization(self, registry):
        """Test registry initialization."""
        assert registry is not None
        assert len(registry.extractors) > 0
    
    def test_get_extractor_html(self, registry, temp_dir):
        """Test getting extractor for HTML."""
        html_file = temp_dir / "test.html"
        html_file.write_text("<html></html>")
        
        extractor = registry.get_extractor(html_file)
        assert extractor is not None
        assert isinstance(extractor, HTMLExtractor)
    
    def test_get_extractor_unknown(self, registry, temp_dir):
        """Test getting extractor for unknown format."""
        unknown_file = temp_dir / "test.xyz"
        unknown_file.write_bytes(b'\x00\x01\x02')
        
        extractor = registry.get_extractor(unknown_file)
        assert extractor is None
    
    def test_extract_html(self, registry, temp_dir):
        """Test extraction through registry."""
        html_file = temp_dir / "test.html"
        html_file.write_text("<html><body><p>Test content</p></body></html>")
        
        result = registry.extract(html_file)
        
        assert result.success
        assert "Test content" in result.text
    
    def test_extract_unsupported(self, registry, temp_dir):
        """Test extraction of unsupported format."""
        unknown_file = temp_dir / "test.xyz"
        unknown_file.write_bytes(b'\x00\x01\x02')
        
        result = registry.extract(unknown_file)
        
        assert not result.success
        assert "No extractor" in result.error
    
    def test_get_supported_formats(self, registry):
        """Test getting list of supported formats."""
        formats = registry.get_supported_formats()
        
        assert isinstance(formats, list)
        # Should have at least HTML (always available)
        assert len(formats) > 0


class TestConvenienceFunction:
    """Test convenience function."""
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_extract_text_html(self, temp_dir):
        """Test extract_text convenience function."""
        html_file = temp_dir / "test.html"
        html_file.write_text("<html><body><p>Simple test</p></body></html>")
        
        result = extract_text(html_file)
        
        assert result.success
        assert "Simple test" in result.text
    
    def test_extract_text_unsupported(self, temp_dir):
        """Test extract_text with unsupported format."""
        unknown_file = temp_dir / "test.xyz"
        unknown_file.write_bytes(b'\x00\x01\x02')
        
        result = extract_text(unknown_file)
        
        assert not result.success


class TestHTMLMetadata:
    """Test HTML metadata extraction."""
    
    @pytest.fixture
    def extractor(self):
        return HTMLExtractor()
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_extract_title(self, extractor, temp_dir):
        """Test extracting HTML title."""
        html_file = temp_dir / "test.html"
        html_content = "<html><head><title>Test Title</title></head><body>Content</body></html>"
        html_file.write_text(html_content)
        
        result = extractor.extract(html_file)
        
        if result.success and extractor.bs4_available:
            # Only check if BeautifulSoup is available
            assert 'title' in result.metadata or 'method' in result.metadata


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
