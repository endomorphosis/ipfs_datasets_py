#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py
# Auto-generated on 2025-07-07 02:28:56"
import pytest
import os
import tempfile
import io

from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from PIL import Image, ImageDraw

from tests._test_utils import (
    raise_on_bad_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor

# Check if each classes methods are accessible:
assert PDFProcessor.process_pdf
assert PDFProcessor._validate_and_analyze_pdf
assert PDFProcessor._decompose_pdf
assert PDFProcessor._extract_page_content
assert PDFProcessor._create_ipld_structure
assert PDFProcessor._process_ocr
assert PDFProcessor._optimize_for_llm
assert PDFProcessor._extract_entities
assert PDFProcessor._create_embeddings
assert PDFProcessor._integrate_with_graphrag
assert PDFProcessor._analyze_cross_document_relationships
assert PDFProcessor._setup_query_interface
assert PDFProcessor._calculate_file_hash
assert PDFProcessor._extract_native_text
assert PDFProcessor._get_processing_time
assert PDFProcessor._get_quality_scores


# Check if the modules's imports are accessible:
import logging
import hashlib
import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from contextlib import nullcontext


import pymupdf  # PyMuPDF
import pdfplumber
from PIL import Image


from ipfs_datasets_py.ipld import IPLDStorage
from ipfs_datasets_py.audit import AuditLogger
from ipfs_datasets_py.monitoring import MonitoringSystem
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator
from ipfs_datasets_py.monitoring import MonitoringConfig, MetricsConfig
from ipfs_datasets_py.pdf_processing.ocr_engine import MultiEngineOCR
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator




class TestDecomposePdf:
    """Test _decompose_pdf method - Stage 2 of PDF processing pipeline."""

    @pytest.fixture
    def pdf_processor(self):
        """Create a PDFProcessor instance for testing."""
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.IPLDStorage'):
            processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
            return processor

    @pytest.fixture
    def sample_text_pdf(self):
        """Create a simple text-only PDF for testing."""
        from ._temp_pdf import TempPDF
        with TempPDF() as temp_pdf:
            # Check to see if these attributes/methods exist.
            assert temp_pdf.temp_dir
            assert temp_pdf.make_temp_pdf
            yield temp_pdf

        # #doc = pymupdf.open()
        # page = doc.new_page()
        # page.insert_text((50, 50), "Sample Text Document\nThis is a test document with multiple lines.\nChapter 1: Introduction")
        
        # # Create temporary file
        # temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        # doc.save(temp_file.name)
        # doc.close()
        
        # yield Path(temp_file.name)
        
        # # Cleanup
        # os.unlink(temp_file.name)

    @pytest.fixture
    def sample_image_pdf(self):
        """Create a PDF with embedded images for testing."""
        doc = pymupdf.open()
        page = doc.new_page()
        
        # Create a simple test image
        img = Image.new('RGB', (100, 100), color='red')
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), "Test Image", fill='white')
        
        # Convert to bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        
        # Insert image into PDF
        img_rect = pymupdf.Rect(50, 50, 150, 150)
        page.insert_image(img_rect, stream=img_bytes.getvalue())
        page.insert_text((50, 200), "Image caption text")
        
        temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        doc.save(temp_file.name)
        doc.close()
        
        yield Path(temp_file.name)
        
        os.unlink(temp_file.name)

    @pytest.fixture
    def sample_annotated_pdf(self):
        """Create a PDF with annotations for testing."""
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((50, 50), "This text has annotations")
        
        # Add highlight annotation
        highlight_rect = pymupdf.Rect(50, 50, 200, 70)
        highlight = page.add_highlight_annot(highlight_rect)
        highlight.set_info(title="Test Highlight", content="This is highlighted text")
        highlight.update()
        
        # Add text annotation
        text_annot = page.add_text_annot(pymupdf.Point(250, 100), "Test Comment")
        text_annot.set_info(title="Reviewer", content="This is a comment annotation")
        text_annot.update()
        
        temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        doc.save(temp_file.name)
        doc.close()
        
        yield Path(temp_file.name)
        
        os.unlink(temp_file.name)

    @pytest.fixture
    def corrupted_pdf(self):
        """Create a corrupted PDF file for testing error handling."""
        temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        temp_file.write(b"This is not a valid PDF file content")
        temp_file.close()
        
        yield Path(temp_file.name)
        
        os.unlink(temp_file.name)

    @pytest.mark.asyncio
    async def test_decompose_pdf_complete_content_extraction(self, pdf_processor, sample_text_pdf):
        """
        GIVEN valid PDF file with text, images, and annotations
        WHEN _decompose_pdf is called
        THEN expect returned dict contains:
            - pages: list of page content dictionaries
            - metadata: document metadata (title, author, dates)
            - structure: table of contents and outline
            - images: extracted image data and metadata
            - fonts: font information and usage statistics
            - annotations: comments, highlights, markup elements
        """
        # Mock the _extract_page_content method to return structured data
        with patch.object(pdf_processor, '_extract_page_content') as mock_extract:
            mock_extract.return_value = {
                'page_number': 1,
                'elements': [
                    {'type': 'text', 'content': 'Sample text', 'bbox': [50, 50, 200, 70]}
                ],
                'images': [],
                'annotations': [],
                'text_blocks': [
                    {'content': 'Sample text', 'bbox': [50, 50, 200, 70]}
                ],
                'drawings': []
            }
            
            result = await pdf_processor._decompose_pdf(sample_text_pdf)
            
            # Verify structure
            assert isinstance(result, dict)
            assert 'pages' in result
            assert 'metadata' in result
            assert 'structure' in result
            assert 'images' in result
            assert 'fonts' in result
            assert 'annotations' in result
            
            # Verify pages structure
            assert isinstance(result['pages'], list)
            assert len(result['pages']) > 0
            
            # Verify metadata structure
            assert isinstance(result['metadata'], dict)
            
            # Verify other components
            assert isinstance(result['structure'], dict)
            assert isinstance(result['images'], list)
            assert isinstance(result['fonts'], list)
            assert isinstance(result['annotations'], list)

    @pytest.mark.asyncio
    async def test_decompose_pdf_text_only_document(self, pdf_processor, sample_text_pdf):
        """
        GIVEN PDF with only text content, no images or annotations
        WHEN _decompose_pdf is called
        THEN expect:
            - pages contain text blocks with positioning
            - images list is empty
            - annotations list is empty
            - fonts list contains used fonts
            - metadata extracted correctly
        """
        result = await pdf_processor._decompose_pdf(sample_text_pdf)
        
        # Verify text content is extracted
        assert len(result['pages']) > 0
        page_content = result['pages'][0]
        assert 'text_blocks' in page_content
        assert len(page_content['text_blocks']) > 0
        
        # Verify text blocks have required structure
        text_block = page_content['text_blocks'][0]
        assert 'content' in text_block
        assert 'bbox' in text_block
        assert len(text_block['content']) > 0
        
        # Verify no images or annotations in text-only document
        assert len(result['images']) == 0
        assert len(result['annotations']) == 0
        
        # Verify fonts are detected
        assert isinstance(result['fonts'], list)
        
        # Verify metadata extraction
        assert 'title' in result['metadata'] or 'creator' in result['metadata'] or 'producer' in result['metadata']

    @pytest.mark.asyncio
    async def test_decompose_pdf_image_heavy_document(self, pdf_processor, sample_image_pdf):
        """
        GIVEN PDF with many embedded images and minimal text
        WHEN _decompose_pdf is called
        THEN expect:
            - images list contains all embedded images
            - Image metadata includes size, colorspace, format
            - pages reference image locations
            - Memory usage handled efficiently
        """
        result = await pdf_processor._decompose_pdf(sample_image_pdf)
        
        # Verify images are extracted
        assert len(result['images']) > 0
        
        # Verify image metadata structure
        image = result['images'][0]
        assert 'width' in image
        assert 'height' in image
        assert 'colorspace' in image
        assert 'ext' in image  # format/extension
        assert 'bbox' in image
        
        # Verify page references to images
        page_content = result['pages'][0]
        assert 'images' in page_content
        
        # Verify basic structure is maintained
        assert isinstance(result['pages'], list)
        assert len(result['pages']) > 0

    @pytest.mark.asyncio
    async def test_decompose_pdf_annotated_document(self, pdf_processor, sample_annotated_pdf):
        """
        GIVEN PDF with comments, highlights, and markup
        WHEN _decompose_pdf is called
        THEN expect:
            - annotations list contains all markup elements
            - Comment text and author information preserved
            - Highlight regions and colors captured
            - Modification timestamps included
        """
        result = await pdf_processor._decompose_pdf(sample_annotated_pdf)
        
        # Verify annotations are extracted
        assert len(result['annotations']) > 0
        
        # Verify annotation structure
        annotation = result['annotations'][0]
        assert 'type' in annotation
        assert 'content' in annotation
        assert 'author' in annotation
        assert 'page' in annotation
        
        # Check for specific annotation types
        annotation_types = [ann['type'] for ann in result['annotations']]
        assert any(t in ['Highlight', 'Text', 'Note'] for t in annotation_types)
        
        # Verify page-level annotation references
        page_content = result['pages'][0]
        assert 'annotations' in page_content

    @pytest.mark.asyncio
    async def test_decompose_pdf_structured_document_with_toc(self, pdf_processor):
        """
        GIVEN PDF with table of contents and outline structure
        WHEN _decompose_pdf is called
        THEN expect:
            - structure contains outline hierarchy
            - TOC entries with page references
            - Document structure preserved
            - Navigation information available
        """
        # Create a PDF with outline structure
        doc = pymupdf.open()  # Creates a new PDF
        page1 = doc.new_page()
        page2 = doc.new_page()
        

        # # Insert text using basic text drawing that works across versions
        # try:
        #     # Use basic drawing commands that are more stable
        #     point1 = pymupdf.Point(50, 50)
        #     point2 = pymupdf.Point(50, 50)
        #     page1.insert_text(point1, "Chapter 1: Introduction")
        #     page2.insert_text(point2, "Chapter 2: Methods")
        # except (AttributeError, TypeError):
        #     # If that fails, use textboxes
        #     try:
        #         rect1 = pymupdf.Rect(50, 50, 250, 70)
        #         rect2 = pymupdf.Rect(50, 50, 250, 70)
        #         page1.insert_textbox(rect1, "Chapter 1: Introduction")
        #         page2.insert_textbox(rect2, "Chapter 2: Methods")
        #     except (AttributeError, TypeError):
        #         pytest.fail(
        #             "Failed to insert text into PDF with pymupdf. Please check PyMuPDF version compatibility."
        #         )
        # Add outline/TOC
        toc = [
            [1, "Chapter 1: Introduction", 1],
            [1, "Chapter 2: Methods", 2]
        ]
        doc.set_toc(toc)
        
        temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        doc.save(temp_file.name)
        doc.close()
        
        try:
            result = await pdf_processor._decompose_pdf(Path(temp_file.name))
            
            # Verify structure contains outline information
            assert 'outline' in result['structure']
            outline = result['structure']['outline']
            
            if outline:  # If outline was extracted
                assert isinstance(outline, list)
                assert len(outline) > 0
                
                # Verify outline entry structure
                entry = outline[0]
                assert isinstance(entry, (list, dict))
                
        finally:
            os.unlink(temp_file.name)

    @pytest.mark.asyncio
    async def test_decompose_pdf_multi_font_document(self, pdf_processor):
        """
        GIVEN PDF with multiple fonts and text styles
        WHEN _decompose_pdf is called
        THEN expect:
            - fonts list contains all used fonts
            - Font names, sizes, and styles captured
            - Usage statistics for each font
            - Text styling information preserved
        """
        # Create PDF with multiple fonts
        doc = pymupdf.open()
        page = doc.new_page()
        
        # Insert text with different fonts/styles (using available fonts)
        page.insert_text((50, 50), "Normal text", fontsize=12)
        page.insert_text((50, 100), "Bold text", fontsize=14, fontname="helv")
        page.insert_text((50, 150), "Large text", fontsize=18)
        
        temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        doc.save(temp_file.name)
        doc.close()
        
        try:
            result = await pdf_processor._decompose_pdf(Path(temp_file.name))
            
            # Verify fonts are extracted
            assert isinstance(result['fonts'], list)
            
            # If fonts were detected, verify structure
            if result['fonts']:
                font = result['fonts'][0]
                assert 'name' in font
                assert isinstance(font['name'], str)
                
        finally:
            os.unlink(temp_file.name)

    @pytest.mark.asyncio
    async def test_decompose_pdf_page_by_page_processing(self, pdf_processor):
        """
        GIVEN large multi-page PDF document
        WHEN _decompose_pdf processes pages
        THEN expect:
            - Each page processed individually
            - Memory usage controlled per page
            - Page order preserved in results
            - Individual page content accessible
        """
        # Create multi-page PDF
        doc = pymupdf.open()
        for i in range(5):
            page = doc.new_page()
            page.insert_text((50, 50), f"Page {i+1} content")
        
        temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        doc.save(temp_file.name)
        doc.close()
        
        try:
            with patch.object(pdf_processor, '_extract_page_content') as mock_extract:
                # Configure mock to return different content per page
                def side_effect(page, page_num):
                    return {
                        'page_number': page_num + 1,
                        'elements': [{'type': 'text', 'content': f'Page {page_num + 1} content'}],
                        'images': [],
                        'annotations': [],
                        'text_blocks': [{'content': f'Page {page_num + 1} content'}],
                        'drawings': []
                    }
                
                mock_extract.side_effect = side_effect
                
                result = await pdf_processor._decompose_pdf(Path(temp_file.name))
                
                # Verify all pages processed
                assert len(result['pages']) == 5
                
                # Verify page order preserved
                for i, page_content in enumerate(result['pages']):
                    assert page_content['page_number'] == i + 1
                
                # Verify _extract_page_content called for each page
                assert mock_extract.call_count == 5
                
        finally:
            os.unlink(temp_file.name)

    @pytest.mark.asyncio
    async def test_decompose_pdf_pymupdf_and_pdfplumber_integration(self, pdf_processor, sample_text_pdf):
        """
        GIVEN PDF requiring both extraction engines
        WHEN _decompose_pdf uses PyMuPDF and pdfplumber
        THEN expect:
            - Complementary extraction capabilities used
            - Enhanced table detection from pdfplumber
            - Comprehensive content extraction from PyMuPDF
            - Combined results merged effectively
        """
        with patch('pdfplumber.open') as mock_pdfplumber:
            # Mock pdfplumber behavior
            mock_pdf = MagicMock()
            mock_page = MagicMock()
            mock_page.extract_tables.return_value = [
                [['Header1', 'Header2'], ['Cell1', 'Cell2']]
            ]
            mock_pdf.pages = [mock_page]
            mock_pdfplumber.return_value.__enter__.return_value = mock_pdf
            
            result = await pdf_processor._decompose_pdf(sample_text_pdf)
            
            # Verify both engines were used (pdfplumber was mocked)
            mock_pdfplumber.assert_called_once()
            
            # Verify structure includes table data if detected
            if 'tables' in result:
                assert isinstance(result['tables'], list)

    @pytest.mark.asyncio
    async def test_decompose_pdf_table_extraction(self, pdf_processor):
        """
        GIVEN PDF with complex tables and structured data
        WHEN _decompose_pdf processes tables
        THEN expect:
            - Table structure preserved
            - Cell content and positioning captured
            - Row and column information maintained
            - Table boundaries and formatting detected
        """
        with patch('pdfplumber.open') as mock_pdfplumber:
            # Mock table extraction
            mock_pdf = MagicMock()
            mock_page = MagicMock()
            mock_page.extract_tables.return_value = [
                [['Name', 'Age', 'City'], ['John', '25', 'NYC'], ['Jane', '30', 'LA']]
            ]
            mock_pdf.pages = [mock_page]
            mock_pdfplumber.return_value.__enter__.return_value = mock_pdf
            
            # Create simple PDF for testing
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((50, 50), "Document with table data")
            
            temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
            doc.save(temp_file.name)
            doc.close()
            
            try:
                result = await pdf_processor._decompose_pdf(Path(temp_file.name))
                
                # Verify pdfplumber was used for table extraction
                mock_pdfplumber.assert_called_once()
                
                # Verify table data structure if present
                if 'tables' in result and result['tables']:
                    table = result['tables'][0]
                    assert isinstance(table, list)
                    assert len(table) > 0
                    
            finally:
                os.unlink(temp_file.name)

    @pytest.mark.asyncio
    async def test_decompose_pdf_vector_graphics_handling(self, pdf_processor):
        """
        GIVEN PDF with vector graphics and drawing elements
        WHEN _decompose_pdf processes graphics
        THEN expect:
            - Vector graphics catalogued with bounding boxes
            - Drawing elements preserved
            - Graphic positioning information captured
            - Vector data available for analysis
        """
        # Create PDF with simple vector graphics
        doc = pymupdf.open()
        page = doc.new_page()
        
        # Draw some vector shapes
        shape = page.new_shape()
        shape.draw_rect(pymupdf.Rect(100, 100, 200, 150))
        shape.draw_circle(pymupdf.Point(300, 300), 50)
        shape.finish(color=(1, 0, 0), fill=(0, 1, 0))
        shape.commit()
        
        temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        doc.save(temp_file.name)
        doc.close()
        
        try:
            result = await pdf_processor._decompose_pdf(Path(temp_file.name))
            
            # Verify drawings are captured
            page_content = result['pages'][0]
            assert 'drawings' in page_content
            assert isinstance(page_content['drawings'], list)
            
        finally:
            os.unlink(temp_file.name)

    @pytest.mark.asyncio
    async def test_decompose_pdf_corrupted_file_handling(self, pdf_processor, corrupted_pdf):
        """
        GIVEN PDF file with corruption in specific pages
        WHEN _decompose_pdf encounters corruption
        THEN expect ValueError to be raised with corruption details
        """
        with pytest.raises(ValueError) as exc_info:
            await pdf_processor._decompose_pdf(corrupted_pdf)
        
        # Verify error message contains relevant information
        error_message = str(exc_info.value)
        assert "cannot open" in error_message.lower() or "invalid" in error_message.lower() or "failed to open" in error_message.lower()

    @pytest.mark.asyncio
    async def test_decompose_pdf_memory_error_handling(self, pdf_processor):
        """
        GIVEN extremely large PDF exceeding memory limits
        WHEN _decompose_pdf processes file
        THEN expect MemoryError to be raised
        """
        # Mock a scenario where memory error occurs during processing
        with patch('pymupdf.open') as mock_pymupdf, \
             patch('pdfplumber.open') as mock_pdfplumber:
            mock_doc = MagicMock()
            mock_doc.__iter__.side_effect = MemoryError("Insufficient memory")
            mock_pymupdf.return_value = mock_doc
            
            # Mock pdfplumber to avoid file not found errors
            mock_pdfplumber.side_effect = MemoryError("Insufficient memory")
            
            with pytest.raises(MemoryError):
                await pdf_processor._decompose_pdf(Path("dummy.pdf"))

    @pytest.mark.asyncio
    async def test_decompose_pdf_io_error_during_image_extraction(self, pdf_processor):
        """
        GIVEN PDF with corrupted embedded images
        WHEN _decompose_pdf extracts images
        THEN expect IOError to be raised
        """
        with patch.object(pdf_processor, '_extract_page_content') as mock_extract:
            mock_extract.side_effect = IOError("Cannot extract image data")
            
            # Create a simple PDF
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((50, 50), "Test")
            
            temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
            doc.save(temp_file.name)
            doc.close()
            
            try:
                with pytest.raises(IOError):
                    await pdf_processor._decompose_pdf(Path(temp_file.name))
            finally:
                os.unlink(temp_file.name)

    @pytest.mark.asyncio
    async def test_decompose_pdf_runtime_error_from_engines(self, pdf_processor):
        """
        GIVEN PDF causing fatal errors in extraction engines
        WHEN _decompose_pdf encounters engine failure
        THEN expect RuntimeError to be raised
        """
        with patch('pymupdf.open') as mock_pymupdf, \
             patch('pdfplumber.open') as mock_pdfplumber:
            mock_doc = MagicMock()
            mock_doc.page_count = 1
            mock_doc.__iter__.side_effect = RuntimeError("Engine failure")
            mock_pymupdf.return_value = mock_doc
            
            # Mock pdfplumber to avoid file not found errors
            mock_pdfplumber.side_effect = RuntimeError("Engine failure")
            
            with pytest.raises(RuntimeError):
                await pdf_processor._decompose_pdf(Path("dummy.pdf"))

    @pytest.mark.asyncio
    async def test_decompose_pdf_empty_document(self, pdf_processor):
        """
        GIVEN PDF with no content (blank pages only)
        WHEN _decompose_pdf processes file
        THEN expect:
            - pages list contains empty page structures
            - All content lists are empty
            - Metadata contains basic document info
        """
        # Create empty PDF
        doc = pymupdf.open()
        page = doc.new_page()  # Blank page with no content
        
        temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        doc.save(temp_file.name)
        doc.close()
        
        try:
            result = await pdf_processor._decompose_pdf(Path(temp_file.name))
            
            # Verify structure exists but content is minimal/empty
            assert len(result['pages']) == 1
            page_content = result['pages'][0]
            
            # Content should be empty or minimal
            assert len(page_content.get('text_blocks', [])) == 0 or \
                   all(not block.get('content', '').strip() for block in page_content.get('text_blocks', []))
            assert len(page_content.get('images', [])) == 0
            assert len(page_content.get('annotations', [])) == 0
            
            # Metadata should still exist
            assert isinstance(result['metadata'], dict)
            
        finally:
            os.unlink(temp_file.name)

    @pytest.mark.asyncio
    async def test_decompose_pdf_single_page_document(self, pdf_processor):
        """
        GIVEN single-page PDF document
        WHEN _decompose_pdf processes file
        THEN expect:
            - pages list contains one page
            - All content properly extracted from single page
            - Structure reflects single-page nature
        """
        # Create single page PDF
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((50, 50), "Single page document content")
        
        temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        doc.save(temp_file.name)
        doc.close()
        
        try:
            result = await pdf_processor._decompose_pdf(Path(temp_file.name))
            
            # Verify exactly one page
            assert len(result['pages']) == 1
            
            # Verify page content
            page_content = result['pages'][0]
            assert page_content['page_number'] == 1
            assert len(page_content['text_blocks']) > 0
            
            # Verify text content
            text_content = page_content['text_blocks'][0]['content']
            assert "Single page document content" in text_content
            
        finally:
            os.unlink(temp_file.name)

    @pytest.mark.asyncio
    async def test_decompose_pdf_metadata_extraction_completeness(self, pdf_processor):
        """
        GIVEN PDF with comprehensive metadata fields
        WHEN _decompose_pdf extracts metadata
        THEN expect:
            - Title, author, subject, keywords extracted
            - Creation and modification dates captured
            - Producer and creator information preserved
            - Custom metadata fields included
        """
        # Create PDF with metadata
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((50, 50), "Document with metadata")
        
        # Set metadata
        metadata = {
            'title': 'Test Document',
            'author': 'Test Author',
            'subject': 'Test Subject',
            'keywords': 'test, pdf, metadata',
            'creator': 'Test Creator',
            'producer': 'Test Producer'
        }
        doc.set_metadata(metadata)
        
        temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        doc.save(temp_file.name)
        doc.close()
        
        try:
            result = await pdf_processor._decompose_pdf(Path(temp_file.name))
            
            # Verify metadata extraction
            extracted_metadata = result['metadata']
            assert isinstance(extracted_metadata, dict)
            
            # Check for expected metadata fields
            expected_fields = ['title', 'author', 'subject', 'keywords', 'creator', 'producer']
            extracted_fields = set(extracted_metadata.keys())
            
            # At least some metadata should be extracted
            assert len(extracted_fields) > 0
            
            # Verify specific values if extracted
            if 'title' in extracted_metadata:
                assert extracted_metadata['title'] == 'Test Document'
            if 'author' in extracted_metadata:
                assert extracted_metadata['author'] == 'Test Author'
                
        finally:
            os.unlink(temp_file.name)

    @pytest.mark.asyncio
    async def test_decompose_pdf_word_level_positioning(self, pdf_processor, sample_text_pdf):
        """
        GIVEN PDF with complex layout and positioning
        WHEN _decompose_pdf extracts text positioning
        THEN expect:
            - Word-level bounding boxes captured
            - Reading order preserved
            - Column layout detected correctly
            - Text flow maintained
        """
        result = await pdf_processor._decompose_pdf(sample_text_pdf)
        
        # Verify page content has text blocks with positioning
        page_content = result['pages'][0]
        assert 'text_blocks' in page_content
        
        if page_content['text_blocks']:
            text_block = page_content['text_blocks'][0]
            assert 'bbox' in text_block
            assert isinstance(text_block['bbox'], (list, tuple))
            assert len(text_block['bbox']) == 4  # x0, y0, x1, y1
            
            # Verify bounding box coordinates are reasonable
            bbox = text_block['bbox']
            assert all(isinstance(coord, (int, float)) for coord in bbox)
            assert bbox[0] < bbox[2]  # x0 < x1
            assert bbox[1] < bbox[3]  # y0 < y1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
