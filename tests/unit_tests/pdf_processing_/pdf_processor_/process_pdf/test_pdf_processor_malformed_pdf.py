"""
Test cases for PDF-specific validation issues in process_pdf method.

This module tests the process_pdf method's handling of various PDF format
issues, including corrupted files, invalid formats, and protected documents.
Shared terminology: "invalid PDF" refers to files that don't conform to
PDF specification or cannot be processed.
"""

import pytest
from pathlib import Path
from typing import Any
from PIL import Image
from reportlab.pdfgen import canvas


from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor


from .conftest import get_error_messages


@pytest.fixture
def password_protected_pdf_file(tmp_path) -> str:
    """Create password-protected PDF file mock."""
    protected_pdf = tmp_path / "protected.pdf"
    # Mock a password-protected PDF structure
    protected_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Encrypt 2 0 R >>\nendobj\n%%EOF"
    protected_pdf.write_bytes(protected_content)
    return str(protected_pdf)

@pytest.fixture
def image_as_pdf_file(tmp_path) -> str:
    """Create an image file renamed with PDF extension."""
    image_as_pdf = tmp_path / "image.pdf"
    # Create a simple image using PIL
    image = Image.new('RGB', (100, 100), color='red')
    image.save(str(image_as_pdf), 'JPEG')
    return str(image_as_pdf)

@pytest.fixture
def corrupted_pdf_file(tmp_path) -> str:
    """Create corrupted PDF file using reportlab."""
    
    corrupted_pdf = tmp_path / "corrupted.pdf"
    # Create a valid PDF first
    c = canvas.Canvas(str(corrupted_pdf))
    c.drawString(100, 750, "Test PDF")
    c.save()
    
    # Corrupt the PDF by truncating it
    with open(corrupted_pdf, 'rb') as f:
        content = f.read()
    
    # Write back only partial content to corrupt it
    with open(corrupted_pdf, 'wb') as f:
        f.write(content[:len(content)//2])
    
    return str(corrupted_pdf)

@pytest.fixture
def empty_pdf_file(tmp_path) -> str:
    """Create empty PDF file."""
    empty_pdf = tmp_path / "empty.pdf"
    empty_pdf.write_bytes(b"")
    return str(empty_pdf)

@pytest.fixture
def truncated_pdf_file(tmp_path) -> str:
    """Create truncated PDF with only header."""
    truncated_pdf = tmp_path / "truncated.pdf"
    truncated_pdf.write_bytes(b"%PDF-1.4\n")
    return str(truncated_pdf)



@pytest.mark.asyncio
@pytest.mark.parametrize("file_fixture", 
    [msg for msg in get_error_messages().keys()]
)
class TestProcessPdfFormatValidation:
    """
    Test PDF format validation for the process_pdf method.
    
    Tests the process_pdf method's ability to validate PDF file format
    and reject various types of invalid or problematic PDF documents.
    
    Shared terminology:
    - "invalid PDF": File that doesn't conform to PDF specification
    - "corrupted PDF": PDF with damaged internal structure
    - "protected PDF": Password-protected or encrypted PDF
    """
    async def test_when_non_pdf_file_provided_then_returns_error_status(
        self, 
        file_fixture,
        default_pdf_processor,
        valid_metadata,
        bad_pdf_files,
    ):
        """
        GIVEN a file with PDF extension but different format
        WHEN process_pdf is called
        THEN returns dictionary with status='error'
        """
        expected_status = 'error'
        bad_pdf_file = bad_pdf_files[file_fixture]['file']

        result = await default_pdf_processor.process_pdf(bad_pdf_file, valid_metadata)

        assert result['status'] == expected_status, \
            f"Expected status to be {expected_status}, got {result['status']} instead."

    @pytest.mark.asyncio
    async def test_when_invalid_pdf_provided_then_returns_expected_error_message(
        self,
        file_fixture,
        default_pdf_processor: PDFProcessor,
        valid_metadata,
        expected_messages,
        bad_pdf_files,
    ):
        """
        GIVEN various invalid PDF files
        WHEN process_pdf is called
        THEN returns dictionary with expected error message
        """
        expected_message = expected_messages[file_fixture]
        pdf_file = bad_pdf_files[file_fixture]['file']
        print(f"Testing file fixture: {file_fixture} with file: {pdf_file}")

        result = await default_pdf_processor.process_pdf(pdf_file, valid_metadata)

        assert expected_message in result['error'], \
            f"Expected error message to contain '{expected_message}', got '{result['error']}' instead." 


class TestProcessPdfIndividualMalformedPdfs:

    @pytest.mark.asyncio
    async def test_when_corrupted_pdf_provided_then_returns_error_status(
        self, 
        default_pdf_processor, 
        corrupted_pdf_file, 
        valid_metadata
    ):
        """
        GIVEN a corrupted PDF file
        WHEN process_pdf is called
        THEN returns dictionary with status='error'
        """
        result = await default_pdf_processor.process_pdf(corrupted_pdf_file, valid_metadata)
        
        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_when_empty_pdf_provided_then_returns_error_status(
        self, 
        default_pdf_processor, 
        empty_pdf_file, 
        valid_metadata
    ):
        """
        GIVEN an empty PDF file
        WHEN process_pdf is called
        THEN returns dictionary with status='error'
        """
        result = await default_pdf_processor.process_pdf(empty_pdf_file, valid_metadata)
        
        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_when_password_protected_pdf_provided_then_returns_error_status(
        self, 
        default_pdf_processor, 
        password_protected_pdf_file, 
        valid_metadata
    ):
        """
        GIVEN a password-protected PDF
        WHEN process_pdf is called
        THEN returns dictionary with status='error'
        """
        result = await default_pdf_processor.process_pdf(password_protected_pdf_file, valid_metadata)
        
        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_when_zero_pages_pdf_provided_then_returns_error_status(
        self, 
        default_pdf_processor, 
        zero_pages_pdf_file, 
        valid_metadata
    ):
        """
        GIVEN a PDF with zero pages
        WHEN process_pdf is called
        THEN returns dictionary with status='error'
        """
        result = await default_pdf_processor.process_pdf(zero_pages_pdf_file, valid_metadata)
        
        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_when_image_file_with_pdf_extension_provided_then_returns_error_status(
        self, 
        default_pdf_processor, 
        image_as_pdf_file,
        valid_metadata
    ):
        """
        GIVEN an image file renamed with PDF extension
        WHEN process_pdf is called
        THEN returns dictionary with status='error'
        """
        result = await default_pdf_processor.process_pdf(image_as_pdf_file, valid_metadata)
        
        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_when_truncated_pdf_provided_then_returns_error_status(
        self, 
        default_pdf_processor, 
        truncated_pdf_file,
        valid_metadata
    ):
        """
        GIVEN a truncated PDF file
        WHEN process_pdf is called
        THEN returns dictionary with status='error'
        """
        result = await default_pdf_processor.process_pdf(truncated_pdf_file, valid_metadata)

        assert result['status'] == 'error'

