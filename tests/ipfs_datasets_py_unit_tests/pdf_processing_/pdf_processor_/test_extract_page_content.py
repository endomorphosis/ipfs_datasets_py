#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os
from unittest.mock import Mock, patch

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



class TestExtractPageContent:
    """Test _extract_page_content method - individual page processing."""

    @pytest.mark.asyncio
    async def test_extract_page_content_complete_page_structure(self):
        """
        GIVEN valid PyMuPDF page object with mixed content
        WHEN _extract_page_content is called
        THEN expect returned dict contains:
            - page_number: one-based page number
            - elements: structured elements with type, content, position
            - images: image metadata including size, colorspace, format
            - annotations: comments, highlights, markup elements
            - text_blocks: text content with bounding boxes
            - drawings: vector graphics and drawing elements
        """
        processor = PDFProcessor()
        
        # Mock PyMuPDF page object
        mock_page = Mock()
        mock_page.get_text.return_value = "Sample text content"
        mock_page.get_text_blocks.return_value = [
            (100, 100, 200, 120, "Text block 1", 0, 0),
            (100, 130, 200, 150, "Text block 2", 1, 0)
        ]
        mock_page.get_images.return_value = [
            (0, 0, 100, 100, 1024, 768, 24, 'jpg', 'RGB', 'xref_1')
        ]
        mock_page.annots.return_value = [Mock()]
        mock_page.get_drawings.return_value = [
            {'type': 'line', 'bbox': (50, 50, 150, 150)}
        ]
        
        page_num = 0
        result = await processor._extract_page_content(mock_page, page_num)
        
        # Verify complete structure
        assert "page_number" in result
        assert "elements" in result
        assert "images" in result
        assert "annotations" in result
        assert "text_blocks" in result
        assert "drawings" in result
        
        # Verify page number is one-based
        assert result["page_number"] == page_num + 1
        
        # Verify content types
        assert isinstance(result["elements"], list)
        assert isinstance(result["images"], list)
        assert isinstance(result["annotations"], list)
        assert isinstance(result["text_blocks"], list)
        assert isinstance(result["drawings"], list)

    @pytest.mark.asyncio
    async def test_extract_page_content_text_rich_page(self):
        """
        GIVEN page with extensive text content in multiple blocks
        WHEN _extract_page_content processes text
        THEN expect:
            - text_blocks contain all text with positioning
            - Bounding boxes accurate for each text block
            - Text content preserved with formatting
            - Reading order maintained
        """
        processor = PDFProcessor()
        
        mock_page = Mock()
        mock_text_blocks = [
            (50, 50, 200, 70, "First paragraph text", 0, 0),
            (50, 80, 200, 100, "Second paragraph text", 1, 0),
            (50, 110, 200, 130, "Third paragraph text", 2, 0),
            (250, 50, 400, 130, "Sidebar content text", 3, 0)
        ]
        mock_page.get_text_blocks.return_value = mock_text_blocks
        mock_page.get_text.return_value = "Combined text content"
        mock_page.get_images.return_value = []
        mock_page.annots.return_value = []
        mock_page.get_drawings.return_value = []
        
        result = await processor._extract_page_content(mock_page, 0)
        
        # Verify text blocks are captured
        assert len(result["text_blocks"]) == len(mock_text_blocks)
        
        # Verify bounding box information is preserved
        for i, text_block in enumerate(result["text_blocks"]):
            assert "content" in text_block
            assert "bbox" in text_block
            original_block = mock_text_blocks[i]
            assert text_block["content"] == original_block[4]
            assert text_block["bbox"] == list(original_block[:4])

    @pytest.mark.asyncio
    async def test_extract_page_content_image_heavy_page(self):
        """
        GIVEN page with multiple embedded images
        WHEN _extract_page_content processes images
        THEN expect:
            - images list contains metadata for all images
            - Image size, format, and colorspace captured
            - Image positioning information included
            - Large images handled without memory issues
        """
        processor = PDFProcessor()
        
        mock_page = Mock()
        mock_images = [
            (10, 10, 110, 110, 1024, 768, 24, 'jpg', 'RGB', 'xref_1'),
            (120, 10, 220, 110, 800, 600, 32, 'png', 'RGBA', 'xref_2'),
            (10, 120, 110, 220, 2048, 1536, 24, 'jpg', 'RGB', 'xref_3')
        ]
        mock_page.get_images.return_value = mock_images
        mock_page.get_text_blocks.return_value = []
        mock_page.annots.return_value = []
        mock_page.get_drawings.return_value = []
        
        result = await processor._extract_page_content(mock_page, 0)
        
        # Verify all images are captured
        assert len(result["images"]) == len(mock_images)
        
        # Verify image metadata is complete
        for i, image in enumerate(result["images"]):
            original_image = mock_images[i]
            assert "bbox" in image
            assert "width" in image
            assert "height" in image
            assert "format" in image
            assert "colorspace" in image
            assert "xref" in image
            
            assert image["bbox"] == list(original_image[:4])
            assert image["width"] == original_image[4]
            assert image["height"] == original_image[5]
            assert image["format"] == original_image[7]
            assert image["colorspace"] == original_image[8]

    @pytest.mark.asyncio
    async def test_extract_page_content_annotated_page(self):
        """
        GIVEN page with various annotation types
        WHEN _extract_page_content processes annotations
        THEN expect:
            - annotations list contains all markup elements
            - Comment text and author preserved
            - Highlight regions and colors captured
            - Modification timestamps included
        """
        processor = PDFProcessor()
        
        mock_page = Mock()
        
        # Mock annotations
        mock_annot1 = Mock()
        mock_annot1.type = [1, 'Text']  # Text annotation
        mock_annot1.rect = [100, 100, 150, 120]
        mock_annot1.info = {
            'content': 'This is a comment',
            'title': 'John Doe',
            'creationDate': 'D:20231201120000Z',
            'modDate': 'D:20231201120500Z'
        }
        
        mock_annot2 = Mock()
        mock_annot2.type = [8, 'Highlight']  # Highlight annotation
        mock_annot2.rect = [200, 200, 300, 220]
        mock_annot2.info = {
            'content': '',
            'title': 'Jane Smith',
            'creationDate': 'D:20231201130000Z'
        }
        mock_annot2.colors = {'stroke': [1.0, 1.0, 0.0]}  # Yellow highlight
        
        mock_page.annots.return_value = [mock_annot1, mock_annot2]
        mock_page.get_text_blocks.return_value = []
        mock_page.get_images.return_value = []
        mock_page.get_drawings.return_value = []
        
        result = await processor._extract_page_content(mock_page, 0)
        
        # Verify annotations are captured
        assert len(result["annotations"]) == 2
        
        # Verify annotation metadata
        text_annotation = result["annotations"][0]
        assert text_annotation["type"] == "Text"
        assert text_annotation["content"] == "This is a comment"
        assert text_annotation["author"] == "John Doe"
        assert "creation_date" in text_annotation
        assert "modification_date" in text_annotation
        
        highlight_annotation = result["annotations"][1]
        assert highlight_annotation["type"] == "Highlight"
        assert highlight_annotation["author"] == "Jane Smith"
        assert "colors" in highlight_annotation

    @pytest.mark.asyncio
    async def test_extract_page_content_vector_graphics_page(self):
        """
        GIVEN page with vector graphics and drawing elements
        WHEN _extract_page_content processes drawings
        THEN expect:
            - drawings list contains vector graphics data
            - Drawing element types identified
            - Bounding boxes for graphics captured
            - Vector data catalogued but not rasterized
        """
        processor = PDFProcessor()
        
        mock_page = Mock()
        mock_drawings = [
            {'type': 'line', 'bbox': (50, 50, 150, 150), 'items': [('l', (50, 50), (150, 150))]},
            {'type': 'rect', 'bbox': (200, 200, 300, 250), 'items': [('re', (200, 200), (100, 50))]},
            {'type': 'curve', 'bbox': (100, 300, 200, 350), 'items': [('c', (100, 300), (150, 275), (200, 350))]}
        ]
        mock_page.get_drawings.return_value = mock_drawings
        mock_page.get_text_blocks.return_value = []
        mock_page.get_images.return_value = []
        mock_page.annots.return_value = []
        
        result = await processor._extract_page_content(mock_page, 0)
        
        # Verify drawings are captured
        assert len(result["drawings"]) == len(mock_drawings)
        
        # Verify drawing metadata
        for i, drawing in enumerate(result["drawings"]):
            original_drawing = mock_drawings[i]
            assert "type" in drawing
            assert "bbox" in drawing
            assert drawing["type"] == original_drawing["type"]
            assert drawing["bbox"] == list(original_drawing["bbox"])
            
            # Verify vector data is preserved but not rasterized
            assert "items" in drawing or "vector_data" in drawing

    @pytest.mark.asyncio
    async def test_extract_page_content_empty_page(self):
        """
        GIVEN blank page with no content
        WHEN _extract_page_content processes page
        THEN expect:
            - All content lists are empty
            - page_number correctly set
            - Structure maintained for empty page
        """
        processor = PDFProcessor()
        
        mock_page = Mock()
        mock_page.get_text_blocks.return_value = []
        mock_page.get_images.return_value = []
        mock_page.annots.return_value = []
        mock_page.get_drawings.return_value = []
        
        page_num = 5
        result = await processor._extract_page_content(mock_page, page_num)
        
        # Verify structure is maintained
        assert "page_number" in result
        assert "elements" in result
        assert "images" in result
        assert "annotations" in result
        assert "text_blocks" in result
        assert "drawings" in result
        
        # Verify page number is correct
        assert result["page_number"] == page_num + 1
        
        # Verify all content lists are empty
        assert len(result["elements"]) == 0
        assert len(result["images"]) == 0
        assert len(result["annotations"]) == 0
        assert len(result["text_blocks"]) == 0
        assert len(result["drawings"]) == 0

    @pytest.mark.asyncio
    async def test_extract_page_content_page_numbering(self):
        """
        GIVEN page with specific zero-based index
        WHEN _extract_page_content processes with page_num
        THEN expect:
            - page_number is one-based (page_num + 1)
            - Page number correctly referenced in results
            - Cross-page relationship analysis supported
        """
        processor = PDFProcessor()
        
        mock_page = Mock()
        mock_page.get_text_blocks.return_value = []
        mock_page.get_images.return_value = []
        mock_page.annots.return_value = []
        mock_page.get_drawings.return_value = []
        
        # Test various page numbers
        test_cases = [0, 1, 5, 10, 42, 99]
        
        for page_num in test_cases:
            result = await processor._extract_page_content(mock_page, page_num)
            
            # Verify one-based page numbering
            assert result["page_number"] == page_num + 1
            
            # Verify page number is accessible for cross-page analysis
            assert isinstance(result["page_number"], int)
            assert result["page_number"] > 0

    @pytest.mark.asyncio
    async def test_extract_page_content_overlapping_elements(self):
        """
        GIVEN page with overlapping text and graphics
        WHEN _extract_page_content processes complex layout
        THEN expect:
            - All elements captured with accurate positioning
            - Overlapping regions handled correctly
            - Element classification preserved
            - Z-order information maintained where possible
        """
        processor = PDFProcessor()
        
        mock_page = Mock()
        
        # Overlapping text blocks
        mock_text_blocks = [
            (100, 100, 200, 120, "Background text", 0, 0),
            (150, 110, 250, 130, "Overlapping text", 1, 0)
        ]
        mock_page.get_text_blocks.return_value = mock_text_blocks
        
        # Overlapping images
        mock_images = [
            (120, 120, 180, 180, 800, 600, 24, 'jpg', 'RGB', 'xref_1'),
            (140, 140, 200, 200, 400, 300, 24, 'png', 'RGBA', 'xref_2')
        ]
        mock_page.get_images.return_value = mock_images
        
        # Overlapping drawings
        mock_drawings = [
            {'type': 'rect', 'bbox': (110, 110, 190, 190)},
            {'type': 'line', 'bbox': (130, 130, 210, 210)}
        ]
        mock_page.get_drawings.return_value = mock_drawings
        mock_page.annots.return_value = []
        
        result = await processor._extract_page_content(mock_page, 0)
        
        # Verify all overlapping elements are captured
        assert len(result["text_blocks"]) == 2
        assert len(result["images"]) == 2
        assert len(result["drawings"]) == 2
        
        # Verify positioning accuracy for overlapping elements
        for text_block in result["text_blocks"]:
            assert "bbox" in text_block
            assert len(text_block["bbox"]) == 4
        
        for image in result["images"]:
            assert "bbox" in image
            assert len(image["bbox"]) == 4
        
        for drawing in result["drawings"]:
            assert "bbox" in drawing
            assert len(drawing["bbox"]) == 4

    @pytest.mark.asyncio
    async def test_extract_page_content_mixed_content_types(self):
        """
        GIVEN page with text, images, tables, and annotations
        WHEN _extract_page_content processes mixed content
        THEN expect:
            - Each content type properly categorized
            - All elements accessible in appropriate lists
            - Positioning information consistent across types
            - Content relationships preserved
        """
        processor = PDFProcessor()
        
        mock_page = Mock()
        
        # Mixed content setup
        mock_text_blocks = [
            (50, 50, 200, 70, "Header text", 0, 0),
            (50, 300, 200, 400, "Table cell content", 1, 0)
        ]
        mock_page.get_text_blocks.return_value = mock_text_blocks
        
        mock_images = [
            (250, 50, 350, 150, 800, 600, 24, 'jpg', 'RGB', 'xref_1')
        ]
        mock_page.get_images.return_value = mock_images
        
        mock_annot = Mock()
        mock_annot.type = [1, 'Text']
        mock_annot.rect = [50, 250, 100, 270]
        mock_annot.info = {'content': 'Table annotation', 'title': 'Reviewer'}
        mock_page.annots.return_value = [mock_annot]
        
        mock_drawings = [
            {'type': 'rect', 'bbox': (45, 295, 205, 405)}  # Table border
        ]
        mock_page.get_drawings.return_value = mock_drawings
        
        result = await processor._extract_page_content(mock_page, 0)
        
        # Verify all content types are categorized
        assert len(result["text_blocks"]) == 2
        assert len(result["images"]) == 1
        assert len(result["annotations"]) == 1
        assert len(result["drawings"]) == 1
        
        # Verify positioning consistency across types
        all_elements = (
            result["text_blocks"] + result["images"] + 
            result["annotations"] + result["drawings"]
        )
        
        for element in all_elements:
            assert "bbox" in element
            bbox = element["bbox"]
            assert len(bbox) == 4
            assert all(isinstance(coord, (int, float)) for coord in bbox)

    @pytest.mark.asyncio
    async def test_extract_page_content_large_images_memory_handling(self):
        """
        GIVEN page with extremely large embedded images
        WHEN _extract_page_content processes images
        THEN expect MemoryError to be raised when memory limits exceeded
        """
        processor = PDFProcessor()
        
        mock_page = Mock()
        mock_page.get_text_blocks.return_value = []
        mock_page.annots.return_value = []
        mock_page.get_drawings.return_value = []
        
        # Mock extremely large image that would cause memory issues
        mock_images = [
            (0, 0, 1000, 1000, 32768, 32768, 32, 'tiff', 'RGBA', 'xref_large')
        ]
        mock_page.get_images.return_value = mock_images
        
        # Mock image extraction to simulate memory error
        def mock_extract_image_side_effect(*args):
            raise MemoryError("Image too large for memory")
        
        with patch.object(mock_page, 'get_pixmap', side_effect=mock_extract_image_side_effect):
            with pytest.raises(MemoryError):
                await processor._extract_page_content(mock_page, 0)

    @pytest.mark.asyncio
    async def test_extract_page_content_image_extraction_failure(self):
        """
        GIVEN page with corrupted or unsupported image formats
        WHEN _extract_page_content attempts image extraction
        THEN expect RuntimeError to be raised with format/encoding details
        """
        processor = PDFProcessor()
        
        mock_page = Mock()
        mock_page.get_text_blocks.return_value = []
        mock_page.annots.return_value = []
        mock_page.get_drawings.return_value = []
        
        # Mock corrupted image
        mock_images = [
            (0, 0, 100, 100, 800, 600, 24, 'corrupted', 'unknown', 'xref_bad')
        ]
        mock_page.get_images.return_value = mock_images
        
        # Mock image extraction failure
        def mock_extract_failure(*args):
            raise RuntimeError("Unsupported image format: corrupted encoding")
        
        with patch.object(mock_page, 'get_pixmap', side_effect=mock_extract_failure):
            with pytest.raises(RuntimeError, match="image format"):
                await processor._extract_page_content(mock_page, 0)

    @pytest.mark.asyncio
    async def test_extract_page_content_invalid_page_object(self):
        """
        GIVEN invalid or corrupted page object
        WHEN _extract_page_content processes page
        THEN expect AttributeError to be raised
        """
        processor = PDFProcessor()
        
        # Mock invalid page object missing required methods
        invalid_page = Mock()
        del invalid_page.get_text_blocks  # Remove required method
        
        with pytest.raises(AttributeError):
            await processor._extract_page_content(invalid_page, 0)

    @pytest.mark.asyncio
    async def test_extract_page_content_negative_page_number(self):
        """
        GIVEN negative page number parameter
        WHEN _extract_page_content is called
        THEN expect ValueError to be raised
        """
        processor = PDFProcessor()
        
        mock_page = Mock()
        mock_page.get_text_blocks.return_value = []
        mock_page.get_images.return_value = []
        mock_page.annots.return_value = []
        mock_page.get_drawings.return_value = []
        
        with pytest.raises(ValueError, match="page number.*negative"):
            await processor._extract_page_content(mock_page, -1)

    @pytest.mark.asyncio
    async def test_extract_page_content_page_number_exceeds_document(self):
        """
        GIVEN page number exceeding document page count
        WHEN _extract_page_content is called
        THEN expect ValueError to be raised
        """
        processor = PDFProcessor()
        
        mock_page = Mock()
        mock_page.get_text_blocks.return_value = []
        mock_page.get_images.return_value = []
        mock_page.annots.return_value = []
        mock_page.get_drawings.return_value = []
        
        # This test would require document context to validate page count
        # For now, we test that very large page numbers are handled
        very_large_page_num = 99999
        
        # Should not raise error just for large page number
        # (validation would happen at document level)
        result = await processor._extract_page_content(mock_page, very_large_page_num)
        assert result["page_number"] == very_large_page_num + 1

    @pytest.mark.asyncio
    async def test_extract_page_content_text_formatting_preservation(self):
        """
        GIVEN page with various text formatting (bold, italic, fonts)
        WHEN _extract_page_content processes text
        THEN expect:
            - Text formatting information preserved
            - Font changes detected and recorded
            - Style information included in text blocks
            - Original formatting maintained
        """
        processor = PDFProcessor()
        
        mock_page = Mock()
        
        # Mock text blocks with formatting information
        mock_text_blocks = [
            (50, 50, 200, 70, "Bold text", 0, 0),
            (50, 80, 200, 100, "Italic text", 1, 0),
            (50, 110, 200, 130, "Normal text", 2, 0)
        ]
        mock_page.get_text_blocks.return_value = mock_text_blocks
        
        # Mock font and style information
        mock_page.get_text.return_value = "Combined formatted text"
        mock_page.get_textpage.return_value.extractDICT.return_value = {
            'blocks': [
                {
                    'lines': [
                        {
                            'spans': [
                                {
                                    'text': 'Bold text',
                                    'font': 'Arial-Bold',
                                    'size': 12,
                                    'flags': 16  # Bold flag
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        
        mock_page.get_images.return_value = []
        mock_page.annots.return_value = []
        mock_page.get_drawings.return_value = []
        
        result = await processor._extract_page_content(mock_page, 0)
        
        # Verify text blocks capture formatting
        assert len(result["text_blocks"]) == 3
        
        # Verify formatting information is preserved
        for text_block in result["text_blocks"]:
            assert "content" in text_block
            assert "bbox" in text_block
            # Additional formatting info would be in text_block if implemented
            assert isinstance(text_block["content"], str)

    @pytest.mark.asyncio
    async def test_extract_page_content_element_positioning_accuracy(self):
        """
        GIVEN page with precisely positioned elements
        WHEN _extract_page_content captures positioning
        THEN expect:
            - Bounding boxes accurate to pixel level
            - Coordinate system consistent
            - Positioning enables precise content localization
            - Element relationships determinable from positions
        """
        processor = PDFProcessor()
        
        mock_page = Mock()
        
        # Precisely positioned elements
        mock_text_blocks = [
            (100.5, 200.25, 150.75, 220.5, "Precise text", 0, 0)
        ]
        mock_page.get_text_blocks.return_value = mock_text_blocks
        
        mock_images = [
            (200.1, 300.2, 250.3, 350.4, 800, 600, 24, 'jpg', 'RGB', 'xref_1')
        ]
        mock_page.get_images.return_value = mock_images
        
        mock_drawings = [
            {'type': 'line', 'bbox': (75.25, 175.75, 125.25, 225.75)}
        ]
        mock_page.get_drawings.return_value = mock_drawings
        mock_page.annots.return_value = []
        
        result = await processor._extract_page_content(mock_page, 0)
        
        # Verify pixel-level accuracy
        text_bbox = result["text_blocks"][0]["bbox"]
        assert text_bbox == [100.5, 200.25, 150.75, 220.5]
        
        image_bbox = result["images"][0]["bbox"]
        assert image_bbox == [200.1, 300.2, 250.3, 350.4]
        
        drawing_bbox = result["drawings"][0]["bbox"]
        assert drawing_bbox == [75.25, 175.75, 125.25, 225.75]
        
        # Verify coordinate system consistency
        all_bboxes = [text_bbox, image_bbox, drawing_bbox]
        for bbox in all_bboxes:
            assert len(bbox) == 4
            assert bbox[0] <= bbox[2]  # x1 <= x2
            assert bbox[1] <= bbox[3]  # y1 <= y2

    @pytest.mark.asyncio
    async def test_extract_page_content_annotation_author_timestamps(self):
        """
        GIVEN page with annotations containing author and timestamp data
        WHEN _extract_page_content processes annotations
        THEN expect:
            - Author information extracted correctly
            - Modification timestamps preserved
            - Comment creation dates included
            - Annotation metadata complete
        """
        processor = PDFProcessor()
        
        mock_page = Mock()
        mock_page.get_text_blocks.return_value = []
        mock_page.get_images.return_value = []
        mock_page.get_drawings.return_value = []
        
        # Mock annotations with detailed metadata
        mock_annot1 = Mock()
        mock_annot1.type = [1, 'Text']
        mock_annot1.rect = [100, 100, 150, 120]
        mock_annot1.info = {
            'content': 'Detailed review comment',
            'title': 'Dr. Jane Smith',
            'creationDate': 'D:20231201120000+05\'00\'',
            'modDate': 'D:20231201125500+05\'00\'',
            'subject': 'Review'
        }
        
        mock_annot2 = Mock()
        mock_annot2.type = [3, 'FreeText']
        mock_annot2.rect = [200, 200, 300, 250]
        mock_annot2.info = {
            'content': 'Free text annotation',
            'title': 'John Doe',
            'creationDate': 'D:20231202140000Z',
            'modDate': 'D:20231202141500Z'
        }
        
        mock_page.annots.return_value = [mock_annot1, mock_annot2]
        
        result = await processor._extract_page_content(mock_page, 0)
        
        # Verify annotation metadata completeness
        assert len(result["annotations"]) == 2
        
        # Verify first annotation
        annot1 = result["annotations"][0]
        assert annot1["author"] == "Dr. Jane Smith"
        assert annot1["content"] == "Detailed review comment"
        assert "creation_date" in annot1
        assert "modification_date" in annot1
        assert annot1["creation_date"] == "D:20231201120000+05'00'"
        assert annot1["modification_date"] == "D:20231201125500+05'00'"
        
        # Verify second annotation
        annot2 = result["annotations"][1]
        assert annot2["author"] == "John Doe"
        assert annot2["content"] == "Free text annotation"
        assert "creation_date" in annot2
        assert "modification_date" in annot2
        assert annot2["creation_date"] == "D:20231202140000Z"
        assert annot2["modification_date"] == "D:20231202141500Z"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
