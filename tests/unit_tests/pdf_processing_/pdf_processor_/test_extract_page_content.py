#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os
from unittest.mock import Mock, patch, MagicMock

from tests._test_utils import (
import asyncio
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

work_dir = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py"
file_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/pdf_processor.py")
md_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/pdf_processor_stubs.md")

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


@pytest.fixture
def mock_page():
    mock_page = MagicMock(spec=pymupdf.Page)
    # Mock the get_text('dict') call used by the actual implementation
    mock_page.get_text.return_value = {
        "blocks": [
            {
                "lines": [
                    {
                        "spans": [
                            {"text": "Sample text content"}
                        ]
                    }
                ],
                "bbox": [100, 100, 200, 120]
            }
        ]
    }
    mock_page.get_text_blocks.return_value = []
    mock_page.get_images.return_value = []
    mock_page.get_image_rects.return_value = []  # Return empty list for fallback behavior
    mock_page.annots.return_value = []
    mock_page.get_drawings.return_value = []
    mock_page.parent = MagicMock()
    mock_page.parent.page_count = 10
    mock_page.type = MagicMock(return_value="text")
    return mock_page

def _make_mock_dict():
    return {
        'storage': MagicMock(spec=IPLDStorage),
        'audit_logger': MagicMock(spec=AuditLogger),
        'monitoring': MagicMock(spec=MonitoringSystem),
        'query_engine': MagicMock(spec=QueryEngine),
        'logger': MagicMock(spec=logging.Logger),
        'integrator': MagicMock(spec=GraphRAGIntegrator),
        'ocr_engine': MagicMock(spec=MultiEngineOCR),
        'optimizer': MagicMock(spec=LLMOptimizer)
    }

class TestExtractPageContent:
    """Test _extract_page_content method - individual page processing."""

    def setup_method(self):
        """
        Setup method to initialize the PDFProcessor instance.
        """
        self.processor = PDFProcessor(mock_dict=_make_mock_dict())

    @pytest.mark.asyncio
    async def test_extract_page_content_complete_page_structure(self, mock_page):
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
        # Mock PyMuPDF page object
        mock_page.get_text_blocks.return_value = [
            (100, 100, 200, 120, "Text block 1", 0, 0),
            (100, 130, 200, 150, "Text block 2", 1, 0)
        ]
        mock_page.get_images.return_value = [
            (0, 0, 100, 100, 1024, 768, 24, 'jpg', 'RGB', 'xref_1')
        ]
        mock_page.annots.return_value = [MagicMock()]
        mock_page.get_drawings.return_value = [
            {'type': 'line', 'bbox': (50, 50, 150, 150)}
        ]
        
        page_num = 0
        result = await self.processor._extract_page_content(mock_page, page_num)
        
        # Verify complete structure
        for element in ["page_number", "elements", "images", "annotations", "text_blocks", "drawings"]:
            assert element in result, f"Missing expected key: {element}"

        # Verify page number is one-based
        assert result["page_number"] == page_num + 1
        
        # Verify content types
        for element in ["elements", "images", "annotations", "text_blocks", "drawings"]:
            assert isinstance(result[element], list), f"{element} should be a list, got {type(result[element])}"

    @pytest.mark.asyncio
    async def test_extract_page_content_text_rich_page(self, mock_page):
        """
        GIVEN page with extensive text content in multiple blocks
        WHEN _extract_page_content processes text
        THEN expect:
            - text_blocks contain all text with positioning
            - Bounding boxes accurate for each text block
            - Text content preserved with formatting
            - Reading order maintained
        """
        # Mock the get_text('dict') call used by the actual implementation
        mock_text_blocks = [
                {
                    "lines": [
                        {"spans": [{"text": "First paragraph text"}]}
                    ],
                    "bbox": [50, 50, 200, 70]
                },
                {
                    "lines": [
                        {"spans": [{"text": "Second paragraph text"}]}
                    ],
                    "bbox": [50, 80, 200, 100]
                },
                {
                    "lines": [
                        {"spans": [{"text": "Third paragraph text"}]}
                    ],
                    "bbox": [50, 110, 200, 130]
                },
                {
                    "lines": [
                        {"spans": [{"text": "Sidebar content text"}]}
                    ],
                    "bbox": [250, 50, 400, 130]
                }
            ]

        mock_page.get_text.return_value = {"blocks": mock_text_blocks}
    
        result = await self.processor._extract_page_content(mock_page, 0)
        
        # Verify text blocks are captured
        assert len(result["text_blocks"]) == len(mock_text_blocks)
        
        # Verify bounding box information is preserved
        for i, text_block in enumerate(result["text_blocks"]):
            assert "content" in text_block
            assert "bbox" in text_block
            expected_block = mock_text_blocks[i]
            expected_text = expected_block["lines"][0]["spans"][0]["text"]
            assert text_block["content"] == expected_text
            assert text_block["bbox"] == expected_block["bbox"]

    @pytest.mark.asyncio
    async def test_extract_page_content_image_heavy_page(self, mock_page):
        """
        GIVEN page with multiple embedded images
        WHEN _extract_page_content processes images
        THEN expect:
            - images list contains metadata for all images
            - Image size, format, and colorspace captured
            - Image positioning information included
            - Large images handled without memory issues
        """
        mock_images = [
            ('xref_1', 0, 1024, 768, 24, 'jpg', '', 'RGB', 0),
            ('xref_2', 0, 800, 600, 32, 'png', '', 'RGBA', 0),
            ('xref_3', 0, 2048, 1536, 24, 'jpg', '', 'RGB', 0)
        ]
        mock_page.get_images.return_value = mock_images

        # Mock Pixmap creation
        with patch('pymupdf.Pixmap') as mock_pixmap_class:
            mock_pixmap_instances = []
            for img in mock_images:
                mock_pix = MagicMock()
                mock_pix.width = img[2]
                mock_pix.height = img[3]
                mock_pix.n = 4 if 'RGBA' in str(img) else 3
                mock_pix.alpha = 1 if 'RGBA' in str(img) else 0
                mock_pix.colorspace.name = img[7] if len(img) > 7 else 'RGB'
                mock_pix.tobytes.return_value = b'fake_image_data'
                mock_pixmap_instances.append(mock_pix)
            
            mock_pixmap_class.side_effect = mock_pixmap_instances

            result = await self.processor._extract_page_content(mock_page, 0)
        
        # Verify all images are captured
        assert len(result["images"]) == len(mock_images)
        
        # Verify image metadata is complete
        for i, image in enumerate(result["images"]):
            mock_pix = mock_pixmap_instances[i]
            assert "image_index" in image
            assert "width" in image
            assert "height" in image
            assert "colorspace" in image
            assert "xref" in image
            
            assert image["width"] == mock_pix.width
            assert image["height"] == mock_pix.height
            assert image["colorspace"] == mock_pix.colorspace.name

    @pytest.mark.asyncio
    async def test_extract_page_content_annotated_page(self, mock_page):
        """
        GIVEN page with various annotation types
        WHEN _extract_page_content processes annotations
        THEN expect:
            - annotations list contains all markup elements
            - Comment text and author preserved
            - Highlight regions and colors captured
            - Modification timestamps included
        """
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
        

        
        
        result = await self.processor._extract_page_content(mock_page, 0)
        
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
    async def test_extract_page_content_vector_graphics_page(self, mock_page):
        """
        GIVEN page with vector graphics and drawing elements
        WHEN _extract_page_content processes drawings
        THEN expect:
            - drawings list contains vector graphics data
            - Drawing element types identified
            - Bounding boxes for graphics captured
            - Vector data catalogued but not rasterized
        """

        mock_drawings = [
            {'type': 'line', 'bbox': (50, 50, 150, 150), 'items': [('l', (50, 50), (150, 150))]},
            {'type': 'rect', 'bbox': (200, 200, 300, 250), 'items': [('re', (200, 200), (100, 50))]},
            {'type': 'curve', 'bbox': (100, 300, 200, 350), 'items': [('c', (100, 300), (150, 275), (200, 350))]}
        ]
        mock_page.get_drawings.return_value = mock_drawings

        result = await self.processor._extract_page_content(mock_page, 0)

        # Verify drawings are captured
        assert len(result["drawings"]) == len(mock_drawings)
        
        # Verify drawing metadata
        for i, drawing in enumerate(result["drawings"]):
            original_drawing = mock_drawings[i]
            assert "type" in drawing
            assert "bbox" in drawing
            assert drawing["type"] == original_drawing["type"]
            assert drawing["bbox"] == original_drawing["bbox"]
            
            # Verify vector data is preserved but not rasterized
            assert "items" in drawing or "vector_data" in drawing

    @pytest.mark.asyncio
    async def test_extract_page_content_empty_page(self, mock_page):
        """
        GIVEN blank page with no content
        WHEN _extract_page_content processes page
        THEN expect:
            - All content lists are empty
            - page_number correctly set
            - Structure maintained for empty page
        """
        # Override the fixture to ensure truly empty page
        mock_page.get_text.return_value = {"blocks": []}
        mock_page.get_images.return_value = []
        mock_page.annots.return_value = []
        mock_page.get_drawings.return_value = []
        
        page_num = 5
        result = await self.processor._extract_page_content(mock_page, page_num)
        
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
    async def test_extract_page_content_page_numbering(self, mock_page):
        """
        GIVEN page with specific zero-based index
        WHEN _extract_page_content processes with page_num
        THEN expect:
            - page_number is one-based (page_num + 1)
            - Page number correctly referenced in results
            - Cross-page relationship analysis supported
        """
        # Increase page count to accommodate test values
        mock_page.parent.page_count = 100
        
        # Test various page numbers
        test_cases = [0, 1, 5, 10, 42, 99]
        
        for page_num in test_cases:
            result = await self.processor._extract_page_content(mock_page, page_num)
            
            # Verify one-based page numbering
            assert result["page_number"] == page_num + 1
            
            # Verify page number is accessible for cross-page analysis
            assert isinstance(result["page_number"], int)
            assert result["page_number"] > 0

    @pytest.mark.asyncio
    async def test_extract_page_content_overlapping_text_blocks_captured(self, mock_page):
        """
        GIVEN page with overlapping text blocks
        WHEN _extract_page_content processes text
        THEN expect all text blocks to be captured
        """
        # Mock the get_text('dict') call for overlapping text blocks
        mock_page.get_text.return_value = {
            "blocks": [
                {
                    "lines": [
                        {"spans": [{"text": "Background text"}]}
                    ],
                    "bbox": [100, 100, 200, 120]
                },
                {
                    "lines": [
                        {"spans": [{"text": "Overlapping text"}]}
                    ],
                    "bbox": [150, 110, 250, 130]
                }
            ]
        }
        
        result = await self.processor._extract_page_content(mock_page, 0)
        
        assert len(result["text_blocks"]) == 2

    @pytest.mark.asyncio
    async def test_extract_page_content_overlapping_images_captured(self, mock_page):
        """
        GIVEN page with overlapping images
        WHEN _extract_page_content processes images
        THEN expect all images to be captured
        """
        # Overlapping images
        mock_images = [
            ('xref_1', 0, 800, 600, 24, 'jpg', '', 'RGB', 0),
            ('xref_2', 0, 400, 300, 24, 'png', '', 'RGBA', 0)
        ]
        mock_page.get_images.return_value = mock_images
        
        # Mock Pixmap creation for images
        with patch('pymupdf.Pixmap') as mock_pixmap_class:
            mock_pixmap_instances = []
            for img in mock_images:
                mock_pix = MagicMock()
                mock_pix.width = img[2]
                mock_pix.height = img[3]
                mock_pix.n = 4 if 'RGBA' in str(img) else 3
                mock_pix.alpha = 1 if 'RGBA' in str(img) else 0
                mock_pix.colorspace.name = img[7] if len(img) > 7 else 'RGB'
                mock_pix.tobytes.return_value = b'fake_image_data'
                mock_pixmap_instances.append(mock_pix)
            
            mock_pixmap_class.side_effect = mock_pixmap_instances

            result = await self.processor._extract_page_content(mock_page, 0)
        
        assert len(result["images"]) == 2

    @pytest.mark.asyncio
    async def test_extract_page_content_overlapping_drawings_captured(self, mock_page):
        """
        GIVEN page with overlapping drawings
        WHEN _extract_page_content processes drawings
        THEN expect all drawings to be captured
        """
        # Overlapping drawings
        mock_drawings = [
            {'type': 'rect', 'bbox': (110, 110, 190, 190)},
            {'type': 'line', 'bbox': (130, 130, 210, 210)}
        ]
        mock_page.get_drawings.return_value = mock_drawings
        
        result = await self.processor._extract_page_content(mock_page, 0)
        
        assert len(result["drawings"]) == 2

    @pytest.mark.asyncio
    async def test_extract_page_content_text_block_bbox_preserved(self, mock_page):
        """
        GIVEN page with text blocks
        WHEN _extract_page_content processes text
        THEN expect bbox information to be preserved
        """
        mock_page.get_text.return_value = {
            "blocks": [
                {
                    "lines": [
                        {"spans": [{"text": "Background text"}]}
                    ],
                    "bbox": [100, 100, 200, 120]
                }
            ]
        }
        
        result = await self.processor._extract_page_content(mock_page, 0)
        
        for text_block in result["text_blocks"]:
            assert "bbox" in text_block

    @pytest.mark.asyncio
    async def test_extract_page_content_text_block_bbox_format(self, mock_page):
        """
        GIVEN page with text blocks
        WHEN _extract_page_content processes text
        THEN expect bbox to have correct format
        """
        bbox = [100, 100, 200, 120]
        mock_page.get_text.return_value = {
            "blocks": [
                {
                    "lines": [
                        {"spans": [{"text": "Background text"}]}
                    ],
                    "bbox": bbox
                }
            ]
        }
        
        result = await self.processor._extract_page_content(mock_page, 0)
        
        for text_block in result["text_blocks"]:
            assert len(text_block["bbox"]) == len(bbox)

    @pytest.mark.asyncio
    async def test_extract_page_content_image_bbox_preserved(self, mock_page):
        """
        GIVEN page with images
        WHEN _extract_page_content processes images
        THEN expect bbox information to be preserved
        """
        mock_images = [
            ('xref_1', 0, 800, 600, 24, 'jpg', '', 'RGB', 0)
        ]
        mock_page.get_images.return_value = mock_images
        
        # Mock Pixmap creation for images
        with patch('pymupdf.Pixmap') as mock_pixmap_class:
            mock_pix = MagicMock()
            mock_pix.width = 800
            mock_pix.height = 600
            mock_pix.n = 3
            mock_pix.alpha = 0
            mock_pix.colorspace.name = 'RGB'
            mock_pix.tobytes.return_value = b'fake_image_data'
            mock_pixmap_class.return_value = mock_pix

            result = await self.processor._extract_page_content(mock_page, 0)
        
        for image in result["images"]:
            assert "bbox" in image

    @pytest.mark.asyncio
    async def test_extract_page_content_image_bbox_format(self, mock_page):
        """
        GIVEN page with images
        WHEN _extract_page_content processes images
        THEN expect bbox to have correct format
        """
        mock_images = [
            ('xref_1', 0, 800, 600, 24, 'jpg', '', 'RGB', 0)
        ]
        mock_page.get_images.return_value = mock_images
        
        # Mock Pixmap creation for images
        with patch('pymupdf.Pixmap') as mock_pixmap_class:
            mock_pix = MagicMock()
            mock_pix.width = 800
            mock_pix.height = 600
            mock_pix.n = 3
            mock_pix.alpha = 0
            mock_pix.colorspace.name = 'RGB'
            mock_pix.tobytes.return_value = b'fake_image_data'
            mock_pixmap_class.return_value = mock_pix

            result = await self.processor._extract_page_content(mock_page, 0)
        
        for image in result["images"]:
            assert len(image["bbox"]) == 4

    @pytest.mark.asyncio
    async def test_extract_page_content_drawing_bbox_preserved(self, mock_page):
        """
        GIVEN page with drawings
        WHEN _extract_page_content processes drawings
        THEN expect bbox information to be preserved
        """
        mock_drawings = [
            {'type': 'rect', 'bbox': (110, 110, 190, 190)}
        ]
        mock_page.get_drawings.return_value = mock_drawings
        
        result = await self.processor._extract_page_content(mock_page, 0)
        
        for drawing in result["drawings"]:
            assert "bbox" in drawing

    @pytest.mark.asyncio
    async def test_extract_page_content_drawing_bbox_format(self, mock_page):
        """
        GIVEN page with drawings
        WHEN _extract_page_content processes drawings
        THEN expect bbox to have correct format
        """
        bbox = (110, 110, 190, 190)
        mock_drawings = [
            {'type': 'rect', 'bbox': bbox}
        ]
        mock_page.get_drawings.return_value = mock_drawings
        
        result = await self.processor._extract_page_content(mock_page, 0)
        
        for drawing in result["drawings"]:
            assert len(drawing["bbox"]) == len(bbox)

    @pytest.mark.asyncio
    async def test_extract_page_content_mixed_content_text_blocks_categorized(self, mock_page):
        """
        GIVEN page with text, images, tables, and annotations
        WHEN _extract_page_content processes mixed content
        THEN expect text blocks to be properly categorized
        """
        # Mixed content setup
        mock_page.get_text.return_value = {
            "blocks": [
                {
                    "lines": [
                        {"spans": [{"text": "Header text"}]}
                    ],
                    "bbox": [50, 50, 200, 70]
                },
                {
                    "lines": [
                        {"spans": [{"text": "Table cell content"}]}
                    ],
                    "bbox": [50, 300, 200, 400]
                }
            ]
        }
        
        mock_images = [
            ('xref_1', 0, 800, 600, 24, 'jpg', '', 'RGB', 0)
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
        
        # Mock Pixmap creation for images
        with patch('pymupdf.Pixmap') as mock_pixmap_class:
            mock_pix = MagicMock()
            mock_pix.width = 800
            mock_pix.height = 600
            mock_pix.n = 3
            mock_pix.alpha = 0
            mock_pix.colorspace.name = 'RGB'
            mock_pix.tobytes.return_value = b'fake_image_data'
            mock_pixmap_class.return_value = mock_pix

            result = await self.processor._extract_page_content(mock_page, 0)
        
        assert len(result["text_blocks"]) == 2

    @pytest.mark.asyncio
    async def test_extract_page_content_mixed_content_images_categorized(self, mock_page):
        """
        GIVEN page with text, images, tables, and annotations
        WHEN _extract_page_content processes mixed content
        THEN expect images to be properly categorized
        """
        # Mixed content setup
        mock_page.get_text.return_value = {
            "blocks": [
                {
                    "lines": [
                        {"spans": [{"text": "Header text"}]}
                    ],
                    "bbox": [50, 50, 200, 70]
                },
                {
                    "lines": [
                        {"spans": [{"text": "Table cell content"}]}
                    ],
                    "bbox": [50, 300, 200, 400]
                }
            ]
        }
        
        mock_images = [
            ('xref_1', 0, 800, 600, 24, 'jpg', '', 'RGB', 0)
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
        
        # Mock Pixmap creation for images
        with patch('pymupdf.Pixmap') as mock_pixmap_class:
            mock_pix = MagicMock()
            mock_pix.width = 800
            mock_pix.height = 600
            mock_pix.n = 3
            mock_pix.alpha = 0
            mock_pix.colorspace.name = 'RGB'
            mock_pix.tobytes.return_value = b'fake_image_data'
            mock_pixmap_class.return_value = mock_pix

            result = await self.processor._extract_page_content(mock_page, 0)
        
        assert len(result["images"]) == 1

    @pytest.mark.asyncio
    async def test_extract_page_content_mixed_content_annotations_categorized(self, mock_page):
        """
        GIVEN page with text, images, tables, and annotations
        WHEN _extract_page_content processes mixed content
        THEN expect annotations to be properly categorized
        """
        # Mixed content setup
        mock_page.get_text.return_value = {
            "blocks": [
                {
                    "lines": [
                        {"spans": [{"text": "Header text"}]}
                    ],
                    "bbox": [50, 50, 200, 70]
                },
                {
                    "lines": [
                        {"spans": [{"text": "Table cell content"}]}
                    ],
                    "bbox": [50, 300, 200, 400]
                }
            ]
        }
        
        mock_images = [
            ('xref_1', 0, 800, 600, 24, 'jpg', '', 'RGB', 0)
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
        
        # Mock Pixmap creation for images
        with patch('pymupdf.Pixmap') as mock_pixmap_class:
            mock_pix = MagicMock()
            mock_pix.width = 800
            mock_pix.height = 600
            mock_pix.n = 3
            mock_pix.alpha = 0
            mock_pix.colorspace.name = 'RGB'
            mock_pix.tobytes.return_value = b'fake_image_data'
            mock_pixmap_class.return_value = mock_pix

            result = await self.processor._extract_page_content(mock_page, 0)
        
        assert len(result["annotations"]) == 1

    @pytest.mark.asyncio
    async def test_extract_page_content_mixed_content_drawings_categorized(self, mock_page):
        """
        GIVEN page with text, images, tables, and annotations
        WHEN _extract_page_content processes mixed content
        THEN expect drawings to be properly categorized
        """
        # Mixed content setup
        mock_page.get_text.return_value = {
            "blocks": [
                {
                    "lines": [
                        {"spans": [{"text": "Header text"}]}
                    ],
                    "bbox": [50, 50, 200, 70]
                },
                {
                    "lines": [
                        {"spans": [{"text": "Table cell content"}]}
                    ],
                    "bbox": [50, 300, 200, 400]
                }
            ]
        }
        
        mock_images = [
            ('xref_1', 0, 800, 600, 24, 'jpg', '', 'RGB', 0)
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
        
        # Mock Pixmap creation for images
        with patch('pymupdf.Pixmap') as mock_pixmap_class:
            mock_pix = MagicMock()
            mock_pix.width = 800
            mock_pix.height = 600
            mock_pix.n = 3
            mock_pix.alpha = 0
            mock_pix.colorspace.name = 'RGB'
            mock_pix.tobytes.return_value = b'fake_image_data'
            mock_pixmap_class.return_value = mock_pix

            result = await self.processor._extract_page_content(mock_page, 0)
        
        assert len(result["drawings"]) == 1

    @pytest.mark.asyncio
    async def test_extract_page_content_mixed_content_has_bbox(self, mock_page):
        """
        GIVEN page with text, images, tables, and annotations
        WHEN _extract_page_content processes mixed content
        THEN expect all elements to have bbox information
        """
        # Mixed content setup
        mock_page.get_text.return_value = {
            "blocks": [
                {
                    "lines": [
                        {"spans": [{"text": "Header text"}]}
                    ],
                    "bbox": [50, 50, 200, 70]
                },
                {
                    "lines": [
                        {"spans": [{"text": "Table cell content"}]}
                    ],
                    "bbox": [50, 300, 200, 400]
                }
            ]
        }
        
        mock_images = [
            ('xref_1', 0, 800, 600, 24, 'jpg', '', 'RGB', 0)
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
        
        # Mock Pixmap creation for images
        with patch('pymupdf.Pixmap') as mock_pixmap_class:
            mock_pix = MagicMock()
            mock_pix.width = 800
            mock_pix.height = 600
            mock_pix.n = 3
            mock_pix.alpha = 0
            mock_pix.colorspace.name = 'RGB'
            mock_pix.tobytes.return_value = b'fake_image_data'
            mock_pixmap_class.return_value = mock_pix

            result = await self.processor._extract_page_content(mock_page, 0)
        
        # Verify all elements have bbox
        all_elements = (
            result["text_blocks"] + result["images"] + 
            result["annotations"] + result["drawings"]
        )
        
        for element in all_elements:
            assert "bbox" in element

    @pytest.mark.asyncio
    async def test_extract_page_content_mixed_content_bbox_has_four_coordinates(self, mock_page):
        """
        GIVEN page with text, images, tables, and annotations
        WHEN _extract_page_content processes mixed content
        THEN expect all bbox values to have exactly 4 coordinates
        """
        # Mixed content setup
        mock_page.get_text.return_value = {
            "blocks": [
                {
                    "lines": [
                        {"spans": [{"text": "Header text"}]}
                    ],
                    "bbox": [50, 50, 200, 70]
                },
                {
                    "lines": [
                        {"spans": [{"text": "Table cell content"}]}
                    ],
                    "bbox": [50, 300, 200, 400]
                }
            ]
        }
        
        mock_images = [
            ('xref_1', 0, 800, 600, 24, 'jpg', '', 'RGB', 0)
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
        
        # Mock Pixmap creation for images
        with patch('pymupdf.Pixmap') as mock_pixmap_class:
            mock_pix = MagicMock()
            mock_pix.width = 800
            mock_pix.height = 600
            mock_pix.n = 3
            mock_pix.alpha = 0
            mock_pix.colorspace.name = 'RGB'
            mock_pix.tobytes.return_value = b'fake_image_data'
            mock_pixmap_class.return_value = mock_pix

            result = await self.processor._extract_page_content(mock_page, 0)
        
        # Verify bbox format consistency
        all_elements = (
            result["text_blocks"] + result["images"] + 
            result["annotations"] + result["drawings"]
        )
        
        for element in all_elements:
            bbox = element["bbox"]
            assert len(bbox) == 4

    @pytest.mark.asyncio
    async def test_extract_page_content_mixed_content_bbox_coordinates_are_numeric(self, mock_page):
        """
        GIVEN page with text, images, tables, and annotations
        WHEN _extract_page_content processes mixed content
        THEN expect all bbox coordinates to be numeric values
        """
        # Mixed content setup
        mock_page.get_text.return_value = {
            "blocks": [
                {
                    "lines": [
                        {"spans": [{"text": "Header text"}]}
                    ],
                    "bbox": [50, 50, 200, 70]
                },
                {
                    "lines": [
                        {"spans": [{"text": "Table cell content"}]}
                    ],
                    "bbox": [50, 300, 200, 400]
                }
            ]
        }
        
        mock_images = [
            ('xref_1', 0, 800, 600, 24, 'jpg', '', 'RGB', 0)
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
        
        # Mock Pixmap creation for images
        with patch('pymupdf.Pixmap') as mock_pixmap_class:
            mock_pix = MagicMock()
            mock_pix.width = 800
            mock_pix.height = 600
            mock_pix.n = 3
            mock_pix.alpha = 0
            mock_pix.colorspace.name = 'RGB'
            mock_pix.tobytes.return_value = b'fake_image_data'
            mock_pixmap_class.return_value = mock_pix

            result = await self.processor._extract_page_content(mock_page, 0)
        
        # Verify coordinate types
        all_elements = (
            result["text_blocks"] + result["images"] + 
            result["annotations"] + result["drawings"]
        )
        
        for element in all_elements:
            bbox = element["bbox"]
            assert all(isinstance(coord, (int, float)) for coord in bbox)

    @pytest.mark.asyncio
    async def test_extract_page_content_large_images_memory_handling(self, mock_page):
        """
        GIVEN page with extremely large embedded images
        WHEN _extract_page_content processes images
        THEN expect MemoryError to be raised when memory limits exceeded
        """
        # Mock extremely large image that would cause memory issues
        mock_images = [
            ('xref_large', 0, 32768, 32768, 32, 'tiff', '', 'RGBA', 0)
        ]
        mock_page.get_images.return_value = mock_images

        # Mock image extraction to simulate memory error
        def mock_pixmap_side_effect(*args):
            raise MemoryError("Image too large for memory")
        
        with patch('pymupdf.Pixmap', side_effect=mock_pixmap_side_effect):
            with pytest.raises(MemoryError):
                await self.processor._extract_page_content(mock_page, 0)

    @pytest.mark.asyncio
    async def test_extract_page_content_image_extraction_failure(self, mock_page):
        """
        GIVEN page with corrupted or unsupported image formats
        WHEN _extract_page_content attempts image extraction
        THEN expect RuntimeError to be raised with format/encoding details
        """
        
        
        
        
        # Mock corrupted image
        mock_images = [
            ('xref_bad', 0, 800, 600, 24, 'corrupted', '', 'unknown', 0)
        ]
        mock_page.get_images.return_value = mock_images
        
        # Mock image extraction failure
        def mock_extract_failure(*args):
            raise RuntimeError("Unsupported image format: corrupted encoding")
        
        with patch('pymupdf.Pixmap', side_effect=mock_extract_failure):
            with pytest.raises(RuntimeError, match="image format"):
                await self.processor._extract_page_content(mock_page, 0)

    @pytest.mark.asyncio
    async def test_extract_page_content_invalid_page_object(self):
        """
        GIVEN invalid or corrupted page object
        WHEN _extract_page_content processes page
        THEN expect AttributeError to be raised
        """
        # Mock invalid page object missing required methods
        invalid_page = Mock(spec=pymupdf.Page)
        del invalid_page.get_text_blocks  # Remove required method
        
        with pytest.raises(AttributeError):
            await self.processor._extract_page_content(invalid_page, 0)

    @pytest.mark.asyncio
    async def test_extract_page_content_negative_page_number(self, mock_page):
        """
        GIVEN negative page number parameter
        WHEN _extract_page_content is called
        THEN expect ValueError to be raised
        """
        with pytest.raises(ValueError, match="Page number cannot be negative"):
            await self.processor._extract_page_content(mock_page, -1)

    @pytest.mark.asyncio
    async def test_extract_page_content_page_number_exceeds_document(self, mock_page):
        """
        GIVEN page number exceeding document page count
        WHEN _extract_page_content is called
        THEN expect ValueError to be raised
        """
        very_large_page_num = 99999

        # Should raise error for page number exceeding document page count
        with pytest.raises(ValueError, match="exceeds document page count"):
            await self.processor._extract_page_content(mock_page, very_large_page_num)

    @pytest.mark.asyncio
    async def test_extract_page_content_text_formatting_preservation(self, mock_page):
        """
        GIVEN page with various text formatting (bold, italic, fonts)
        WHEN _extract_page_content processes text
        THEN expect:
            - Text formatting information preserved
            - Font changes detected and recorded
            - Style information included in text blocks
            - Original formatting maintained
        """
        # Mock text blocks with formatting information
        mock_page.get_text.return_value = {
            "blocks": [
                {
                    "lines": [
                        {"spans": [{"text": "Bold text"}]}
                    ],
                    "bbox": [50, 50, 200, 70]
                },
                {
                    "lines": [
                        {"spans": [{"text": "Italic text"}]}
                    ],
                    "bbox": [50, 80, 200, 100]
                },
                {
                    "lines": [
                        {"spans": [{"text": "Normal text"}]}
                    ],
                    "bbox": [50, 110, 200, 130]
                }
            ]
        }
        

        
        
        
        result = await self.processor._extract_page_content(mock_page, 0)
        
        # Verify text blocks capture formatting
        assert len(result["text_blocks"]) == 3
        
        # Verify formatting information is preserved
        for text_block in result["text_blocks"]:
            assert "content" in text_block
            assert "bbox" in text_block
            # Additional formatting info would be in text_block if implemented
            assert isinstance(text_block["content"], str)

    @pytest.mark.asyncio
    async def test_extract_page_content_element_positioning_accuracy(self, mock_page):
        """
        GIVEN page with precisely positioned elements
        WHEN _extract_page_content captures positioning
        THEN expect:
            - Bounding boxes accurate to pixel level
            - Coordinate system consistent
            - Positioning enables precise content localization
            - Element relationships determinable from positions
        """
        # Precisely positioned elements
        mock_page.get_text.return_value = {
            "blocks": [
                {
                    "lines": [
                        {"spans": [{"text": "Precise text"}]}
                    ],
                    "bbox": [100.5, 200.25, 150.75, 220.5]
                }
            ]
        }
        
        mock_images = [
            ('xref_1', 0, 800, 600, 24, 'jpg', '', 'RGB', 0)
        ]
        mock_page.get_images.return_value = mock_images
        
        mock_drawings = [
            {'type': 'line', 'bbox': (75.25, 175.75, 125.25, 225.75)}
        ]
        mock_page.get_drawings.return_value = mock_drawings
        
        # Mock the image rect extraction to return precise positioning
        mock_page.get_image_rects.return_value = [[200.1, 300.2, 250.3, 350.4]]
        
        # Mock Pixmap creation for images
        with patch('pymupdf.Pixmap') as mock_pixmap_class:
            mock_pix = MagicMock()
            mock_pix.width = 800
            mock_pix.height = 600
            mock_pix.n = 3
            mock_pix.alpha = 0
            mock_pix.colorspace.name = 'RGB'
            mock_pix.tobytes.return_value = b'fake_image_data'
            mock_pixmap_class.return_value = mock_pix

            result = await self.processor._extract_page_content(mock_page, 0)
        
        # Verify pixel-level accuracy
        text_bbox = result["text_blocks"][0]["bbox"]
        assert text_bbox == [100.5, 200.25, 150.75, 220.5]
        
        image_bbox = result["images"][0]["bbox"]
        assert image_bbox == [200.1, 300.2, 250.3, 350.4]
        
        drawing_bbox = result["drawings"][0]["bbox"]
        assert drawing_bbox == (75.25, 175.75, 125.25, 225.75)
        
        # Verify coordinate system consistency
        all_bboxes = [text_bbox, image_bbox, drawing_bbox]
        for bbox in all_bboxes:
            assert len(bbox) == 4
            assert bbox[0] <= bbox[2]  # x1 <= x2
            assert bbox[1] <= bbox[3]  # y1 <= y2

    @pytest.mark.asyncio
    async def test_extract_page_content_annotation_author_timestamps(self, mock_page):
        """
        GIVEN page with annotations containing author and timestamp data
        WHEN _extract_page_content processes annotations
        THEN expect:
            - Author information extracted correctly
            - Modification timestamps preserved
            - Comment creation dates included
            - Annotation metadata complete
        """
        

        
        
        # Mock annotations with detailed metadata
        mock_annot1 = MagicMock()
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
        
        result = await self.processor._extract_page_content(mock_page, 0)
        
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
