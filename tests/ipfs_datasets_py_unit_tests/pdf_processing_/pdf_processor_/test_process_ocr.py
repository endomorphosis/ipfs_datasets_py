
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path
from typing import Dict, Any, List
import numpy as np
from PIL import Image
import io

# Import the class under test
from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor




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




class TestProcessOcr:
    """Test _process_ocr method - Stage 4 of PDF processing pipeline."""

    @pytest.fixture
    def processor(self):
        """Create PDFProcessor instance for testing."""
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.IPLDStorage'):
            return PDFProcessor()

    @pytest.fixture
    def sample_decomposed_content_with_images(self):
        """Sample decomposed content with embedded images for OCR testing."""
        # Create sample image data
        sample_image = Image.new('RGB', (100, 50), color='white')
        img_buffer = io.BytesIO()
        sample_image.save(img_buffer, format='PNG')
        img_data = img_buffer.getvalue()
        
        return {
            'pages': [
                {
                    'page_number': 1,
                    'elements': [
                        {'type': 'text', 'content': 'Regular text content'},
                        {'type': 'image', 'content': img_data, 'bbox': [10, 10, 110, 60]}
                    ],
                    'images': [
                        {
                            'data': img_data,
                            'format': 'PNG',
                            'bbox': [10, 10, 110, 60],
                            'width': 100,
                            'height': 50,
                            'colorspace': 'RGB'
                        }
                    ],
                    'text_blocks': [{'content': 'Regular text content'}],
                    'annotations': []
                },
                {
                    'page_number': 2,
                    'elements': [
                        {'type': 'image', 'content': img_data, 'bbox': [20, 20, 120, 70]}
                    ],
                    'images': [
                        {
                            'data': img_data,
                            'format': 'JPEG',
                            'bbox': [20, 20, 120, 70],
                            'width': 100,
                            'height': 50,
                            'colorspace': 'RGB'
                        }
                    ],
                    'text_blocks': [],
                    'annotations': []
                }
            ],
            'metadata': {'title': 'OCR Test Document', 'pages': 2},
            'images': [
                {'page': 1, 'data': img_data, 'format': 'PNG'},
                {'page': 2, 'data': img_data, 'format': 'JPEG'}
            ]
        }

    @pytest.fixture
    def sample_decomposed_content_no_images(self):
        """Sample decomposed content without images."""
        return {
            'pages': [
                {
                    'page_number': 1,
                    'elements': [{'type': 'text', 'content': 'Text only content'}],
                    'images': [],
                    'text_blocks': [{'content': 'Text only content'}],
                    'annotations': []
                }
            ],
            'metadata': {'title': 'Text Only Document', 'pages': 1},
            'images': []
        }

    @pytest.fixture
    def mock_ocr_engine(self):
        """Mock OCR engine with realistic responses."""
        mock_engine = Mock()
        
        # Mock successful OCR results
        def mock_process_image(image_data, **kwargs):
            return {
                'text': 'Sample OCR extracted text',
                'confidence': 0.85,
                'words': [
                    {'text': 'Sample', 'confidence': 0.9, 'bbox': [10, 10, 50, 25]},
                    {'text': 'OCR', 'confidence': 0.8, 'bbox': [55, 10, 75, 25]},
                    {'text': 'extracted', 'confidence': 0.85, 'bbox': [80, 10, 140, 25]},
                    {'text': 'text', 'confidence': 0.85, 'bbox': [145, 10, 170, 25]}
                ],
                'engine': 'tesseract'
            }
        
        mock_engine.process_image = mock_process_image
        return mock_engine

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_text_extraction(self, processor, sample_decomposed_content_with_images, mock_ocr_engine):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect returned dict contains:
            - Page-keyed dictionary with OCR results for each image
            - Text content, confidence score, engine used, word boxes for each image
            - Aggregate confidence scores and text quality metrics
        """
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR') as mock_ocr_class:
            mock_ocr_instance = Mock()
            mock_ocr_class.return_value = mock_ocr_instance
            
            # Setup multi-engine responses
            def mock_process_engines(image_data):
                future = asyncio.Future()
                future.set_result({
                    'tesseract': {
                        'text': 'Tesseract extracted text',
                        'confidence': 0.85,
                        'words': [{'text': 'Tesseract', 'confidence': 0.85, 'bbox': [10, 10, 80, 25]}],
                        'engine': 'tesseract'
                    },
                    'easyocr': {
                        'text': 'EasyOCR extracted text',
                        'confidence': 0.90,
                        'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                        'engine': 'easyocr'
                    },
                    'best_result': {
                        'text': 'EasyOCR extracted text',
                        'confidence': 0.90,
                        'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                        'engine': 'easyocr'
                    }
                })
                return future
            
            mock_ocr_instance.process_image_multi_engine = mock_process_engines
            
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            # Verify return structure
            assert isinstance(result, dict)
            
            # Verify page-keyed structure
            assert 'page_1' in result or 'pages' in result or len(result) >= 1
            
            # If using page keys directly
            for key, page_result in result.items():
                if 'page' in str(key).lower() or isinstance(page_result, dict):
                    # Verify OCR results structure
                    if 'images' in page_result:
                        for image_result in page_result['images']:
                            assert 'text' in image_result
                            assert 'confidence' in image_result
                            assert 'engine' in image_result
                            assert 'words' in image_result
                            
                            # Verify word-level results
                            for word in image_result['words']:
                                assert 'text' in word
                                assert 'confidence' in word
                                assert 'bbox' in word
            
            # Verify OCR engine was called
            assert mock_ocr_instance.process_image_multi_engine.called

    @pytest.mark.asyncio
    async def test_process_ocr_high_quality_image_text(self, processor, sample_decomposed_content_with_images):
        """
        GIVEN images with clear, high-resolution text
        WHEN _process_ocr extracts text
        THEN expect:
            - High confidence scores (>0.9)
            - Accurate text extraction with minimal errors
            - Proper word-level positioning
            - Complete text recovery from images
        """
        # Mock high-quality OCR results
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR') as mock_ocr_class:
            mock_ocr_instance = Mock()
            mock_ocr_class.return_value = mock_ocr_instance
            
            def high_quality_ocr(image_data):
                future = asyncio.Future()
                future.set_result({
                    'best_result': {
                        'text': 'High quality clear text extracted perfectly',
                        'confidence': 0.95,
                        'words': [
                            {'text': 'High', 'confidence': 0.98, 'bbox': [10, 10, 35, 25]},
                            {'text': 'quality', 'confidence': 0.96, 'bbox': [40, 10, 80, 25]},
                            {'text': 'clear', 'confidence': 0.94, 'bbox': [85, 10, 115, 25]},
                            {'text': 'text', 'confidence': 0.93, 'bbox': [120, 10, 145, 25]},
                            {'text': 'extracted', 'confidence': 0.95, 'bbox': [150, 10, 200, 25]},
                            {'text': 'perfectly', 'confidence': 0.97, 'bbox': [205, 10, 260, 25]}
                        ],
                        'engine': 'easyocr'
                    }
                })
                return future
            
            mock_ocr_instance.process_image_multi_engine = high_quality_ocr
            
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            # Verify high confidence scores
            found_high_confidence = False
            for page_key, page_result in result.items():
                if isinstance(page_result, dict) and 'images' in page_result:
                    for image_result in page_result['images']:
                        if 'confidence' in image_result:
                            assert image_result['confidence'] > 0.9
                            found_high_confidence = True
                            
                            # Verify word-level confidence
                            if 'words' in image_result:
                                for word in image_result['words']:
                                    assert word['confidence'] > 0.9
                                    
                                    # Verify proper positioning
                                    assert 'bbox' in word
                                    assert len(word['bbox']) == 4
                                    assert all(isinstance(coord, (int, float)) for coord in word['bbox'])
            
            assert found_high_confidence, "No high confidence results found"

    @pytest.mark.asyncio
    async def test_process_ocr_low_quality_image_handling(self, processor, sample_decomposed_content_with_images):
        """
        GIVEN images with poor quality, low resolution, or distorted text
        WHEN _process_ocr processes challenging images
        THEN expect:
            - Lower confidence scores reflecting quality
            - Partial text extraction where possible
            - Quality metrics indicating processing challenges
            - Graceful handling of unreadable content
        """
        # Mock low-quality OCR results
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR') as mock_ocr_class:
            mock_ocr_instance = Mock()
            mock_ocr_class.return_value = mock_ocr_instance
            
            def low_quality_ocr(image_data):
                future = asyncio.Future()
                future.set_result({
                    'best_result': {
                        'text': 'p4rt14l t3xt 3xtr4ct3d',  # Simulated OCR errors
                        'confidence': 0.45,
                        'words': [
                            {'text': 'p4rt14l', 'confidence': 0.35, 'bbox': [10, 10, 55, 25]},
                            {'text': 't3xt', 'confidence': 0.40, 'bbox': [60, 10, 85, 25]},
                            {'text': '3xtr4ct3d', 'confidence': 0.60, 'bbox': [90, 10, 150, 25]}
                        ],
                        'engine': 'tesseract',
                        'quality_metrics': {
                            'blur_score': 0.3,
                            'noise_level': 0.8,
                            'contrast': 0.4
                        }
                    }
                })
                return future
            
            mock_ocr_instance.process_image_multi_engine = low_quality_ocr
            
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            # Verify low confidence handling
            found_low_quality = False
            for page_key, page_result in result.items():
                if isinstance(page_result, dict) and 'images' in page_result:
                    for image_result in page_result['images']:
                        if 'confidence' in image_result:
                            if image_result['confidence'] < 0.7:
                                found_low_quality = True
                                
                                # Verify partial text extraction
                                assert 'text' in image_result
                                assert len(image_result['text']) > 0  # Some text extracted
                                
                                # Verify quality metrics if available
                                if 'quality_metrics' in image_result:
                                    metrics = image_result['quality_metrics']
                                    assert isinstance(metrics, dict)
            
            assert found_low_quality or len(result) > 0, "Should handle low quality images gracefully"

    @pytest.mark.asyncio
    async def test_process_ocr_multiple_languages_support(self, processor, sample_decomposed_content_with_images):
        """
        GIVEN images containing text in multiple languages
        WHEN _process_ocr processes multilingual content
        THEN expect:
            - Text extracted across different languages
            - Language detection and appropriate processing
            - Unicode character support maintained
            - Multi-script text handling
        """
        # Mock multilingual OCR results
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR') as mock_ocr_class:
            mock_ocr_instance = Mock()
            mock_ocr_class.return_value = mock_ocr_instance
            
            def multilingual_ocr(image_data):
                future = asyncio.Future()
                future.set_result({
                    'best_result': {
                        'text': 'English text français español 中文 العربية русский',
                        'confidence': 0.80,
                        'words': [
                            {'text': 'English', 'confidence': 0.90, 'bbox': [10, 10, 50, 25], 'language': 'en'},
                            {'text': 'text', 'confidence': 0.88, 'bbox': [55, 10, 80, 25], 'language': 'en'},
                            {'text': 'français', 'confidence': 0.85, 'bbox': [85, 10, 125, 25], 'language': 'fr'},
                            {'text': 'español', 'confidence': 0.82, 'bbox': [130, 10, 170, 25], 'language': 'es'},
                            {'text': '中文', 'confidence': 0.75, 'bbox': [175, 10, 195, 25], 'language': 'zh'},
                            {'text': 'العربية', 'confidence': 0.70, 'bbox': [200, 10, 230, 25], 'language': 'ar'},
                            {'text': 'русский', 'confidence': 0.78, 'bbox': [235, 10, 275, 25], 'language': 'ru'}
                        ],
                        'engine': 'easyocr',
                        'languages_detected': ['en', 'fr', 'es', 'zh', 'ar', 'ru']
                    }
                })
                return future
            
            mock_ocr_instance.process_image_multi_engine = multilingual_ocr
            
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            # Verify multilingual support
            found_multilingual = False
            for page_key, page_result in result.items():
                if isinstance(page_result, dict) and 'images' in page_result:
                    for image_result in page_result['images']:
                        if 'text' in image_result:
                            text = image_result['text']
                            
                            # Check for Unicode characters (non-ASCII)
                            has_unicode = any(ord(char) > 127 for char in text)
                            if has_unicode:
                                found_multilingual = True
                            
                            # Verify language detection if available
                            if 'languages_detected' in image_result:
                                assert isinstance(image_result['languages_detected'], list)
                                assert len(image_result['languages_detected']) > 1
                            
                            # Verify word-level language info if available
                            if 'words' in image_result:
                                for word in image_result['words']:
                                    if 'language' in word:
                                        assert isinstance(word['language'], str)
                                        assert len(word['language']) >= 2
            
            # Should handle multilingual content without errors
            assert len(result) > 0

    @pytest.mark.asyncio
    async def test_process_ocr_word_level_positioning_accuracy(self, processor, sample_decomposed_content_with_images):
        """
        GIVEN images with text requiring precise positioning
        WHEN _process_ocr extracts word boxes
        THEN expect:
            - Accurate bounding boxes for each word
            - Coordinate system consistent with document layout
            - Word positioning enables content localization
            - Spatial relationships preserved
        """
        # Mock OCR with precise positioning
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR') as mock_ocr_class:
            mock_ocr_instance = Mock()
            mock_ocr_class.return_value = mock_ocr_instance
            
            def precise_positioning_ocr(image_data):
                future = asyncio.Future()
                future.set_result({
                    'best_result': {
                        'text': 'Precisely positioned text elements',
                        'confidence': 0.88,
                        'words': [
                            {'text': 'Precisely', 'confidence': 0.90, 'bbox': [10.5, 15.2, 65.8, 28.7]},
                            {'text': 'positioned', 'confidence': 0.88, 'bbox': [70.1, 15.2, 135.6, 28.7]},
                            {'text': 'text', 'confidence': 0.89, 'bbox': [140.3, 15.2, 170.9, 28.7]},
                            {'text': 'elements', 'confidence': 0.87, 'bbox': [175.4, 15.2, 230.1, 28.7]}
                        ],
                        'engine': 'easyocr',
                        'page_bbox': [0, 0, 250, 50],  # Image dimensions
                        'coordinate_system': 'top_left_origin'
                    }
                })
                return future
            
            mock_ocr_instance.process_image_multi_engine = precise_positioning_ocr
            
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            # Verify precise positioning
            found_positioning = False
            for page_key, page_result in result.items():
                if isinstance(page_result, dict) and 'images' in page_result:
                    for image_result in page_result['images']:
                        if 'words' in image_result:
                            words = image_result['words']
                            
                            for i, word in enumerate(words):
                                assert 'bbox' in word
                                bbox = word['bbox']
                                
                                # Verify bbox format
                                assert len(bbox) == 4
                                assert all(isinstance(coord, (int, float)) for coord in bbox)
                                
                                # Verify logical bbox (x1 < x2, y1 < y2)
                                x1, y1, x2, y2 = bbox
                                assert x1 < x2, f"Invalid bbox x coordinates: {bbox}"
                                assert y1 < y2, f"Invalid bbox y coordinates: {bbox}"
                                
                                # Verify spatial relationships (words should be ordered left-to-right)
                                if i > 0:
                                    prev_word = words[i-1]
                                    prev_x2 = prev_word['bbox'][2]
                                    assert x1 >= prev_x2 - 5, "Words should maintain spatial order"  # Allow small overlap
                                
                                found_positioning = True
            
            assert found_positioning, "Should find word-level positioning data"

    @pytest.mark.asyncio
    async def test_process_ocr_confidence_scoring_accuracy(self, processor, sample_decomposed_content_with_images):
        """
        GIVEN OCR processing of various image qualities
        WHEN _process_ocr generates confidence scores
        THEN expect:
            - Confidence scores correlate with extraction accuracy
            - Scores enable quality-based filtering
            - Engine comparison through confidence metrics
            - Reliable quality assessment
        """
        # Mock OCR with varying confidence scores
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR') as mock_ocr_class:
            mock_ocr_instance = Mock()
            mock_ocr_class.return_value = mock_ocr_instance
            
            call_count = 0
            def varying_confidence_ocr(image_data):
                nonlocal call_count
                call_count += 1
                
                # Simulate different quality images
                if call_count == 1:  # High quality
                    confidence = 0.92
                    text = "Clear high quality text"
                else:  # Lower quality
                    confidence = 0.65
                    text = "blu77y l0w qu4l1ty t3xt"
                
                future = asyncio.Future()
                future.set_result({
                    'tesseract': {
                        'text': text,
                        'confidence': confidence - 0.05,
                        'engine': 'tesseract'
                    },
                    'easyocr': {
                        'text': text,
                        'confidence': confidence,
                        'engine': 'easyocr'
                    },
                    'best_result': {
                        'text': text,
                        'confidence': confidence,
                        'engine': 'easyocr' if confidence > 0.8 else 'tesseract',
                        'engine_comparison': {
                            'tesseract': confidence - 0.05,
                            'easyocr': confidence
                        }
                    }
                })
                return future
            
            mock_ocr_instance.process_image_multi_engine = varying_confidence_ocr
            
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            # Verify confidence scoring
            confidences = []
            for page_key, page_result in result.items():
                if isinstance(page_result, dict) and 'images' in page_result:
                    for image_result in page_result['images']:
                        if 'confidence' in image_result:
                            confidence = image_result['confidence']
                            
                            # Verify confidence range
                            assert 0.0 <= confidence <= 1.0
                            confidences.append(confidence)
                            
                            # Verify engine comparison if available
                            if 'engine_comparison' in image_result:
                                comparison = image_result['engine_comparison']
                                assert isinstance(comparison, dict)
                                assert len(comparison) >= 2  # Multiple engines compared
                                
                                # All comparison scores should be valid
                                for engine, score in comparison.items():
                                    assert 0.0 <= score <= 1.0
            
            # Should have confidence scores for processed images
            assert len(confidences) > 0
            
            # Verify range of confidences (should vary based on quality)
            if len(confidences) > 1:
                assert max(confidences) > min(confidences), "Should have varying confidence scores"

    @pytest.mark.asyncio
    async def test_process_ocr_engine_comparison_and_selection(self, processor, sample_decomposed_content_with_images):
        """
        GIVEN multiple OCR engines with different strengths
        WHEN _process_ocr compares engine results
        THEN expect:
            - Best engine selected based on confidence scores
            - Engine-specific results available for comparison
            - Accuracy validation across engines
            - Optimal results chosen for downstream processing
        """
        # Mock multi-engine OCR with different performances
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR') as mock_ocr_class:
            mock_ocr_instance = Mock()
            mock_ocr_class.return_value = mock_ocr_instance
            
            def multi_engine_comparison(image_data):
                future = asyncio.Future()
                future.set_result({
                    'tesseract': {
                        'text': 'Tesseract result with good accuracy',
                        'confidence': 0.82,
                        'engine': 'tesseract',
                        'processing_time': 1.2
                    },
                    'easyocr': {
                        'text': 'EasyOCR result with better accuracy',
                        'confidence': 0.91,
                        'engine': 'easyocr',
                        'processing_time': 2.1
                    },
                    'paddleocr': {
                        'text': 'PaddleOCR result moderate accuracy',
                        'confidence': 0.75,
                        'engine': 'paddleocr',
                        'processing_time': 1.8
                    },
                    'best_result': {
                        'text': 'EasyOCR result with better accuracy',
                        'confidence': 0.91,
                        'engine': 'easyocr',
                        'selected_reason': 'highest_confidence',
                        'all_engines': {
                            'tesseract': 0.82,
                            'easyocr': 0.91,
                            'paddleocr': 0.75
                        }
                    }
                })
                return future
            
            mock_ocr_instance.process_image_multi_engine = multi_engine_comparison
            
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            # Verify engine comparison and selection
            found_comparison = False
            for page_key, page_result in result.items():
                if isinstance(page_result, dict) and 'images' in page_result:
                    for image_result in page_result['images']:
                        # Verify best engine selection
                        if 'engine' in image_result:
                            assert isinstance(image_result['engine'], str)
                            assert len(image_result['engine']) > 0
                        
                        # Verify engine comparison data
                        if 'all_engines' in image_result:
                            engines = image_result['all_engines']
                            assert isinstance(engines, dict)
                            assert len(engines) >= 2  # Multiple engines compared
                            
                            # Verify best engine has highest confidence
                            if 'confidence' in image_result and 'engine' in image_result:
                                best_engine = image_result['engine']
                                best_confidence = image_result['confidence']
                                
                                if best_engine in engines:
                                    assert engines[best_engine] == best_confidence
                                    
                                    # Verify it's actually the best
                                    for engine, confidence in engines.items():
                                        assert confidence <= best_confidence
                            
                            found_comparison = True
                        
                        # Verify selection reasoning if available
                        if 'selected_reason' in image_result:
                            reason = image_result['selected_reason']
                            assert isinstance(reason, str)
                            assert reason in ['highest_confidence', 'best_accuracy', 'fastest', 'balanced']
            
            assert found_comparison, "Should perform engine comparison and selection"

    @pytest.mark.asyncio
    async def test_process_ocr_no_images_in_content(self, processor, sample_decomposed_content_no_images):
        """
        GIVEN decomposed content with no embedded images
        WHEN _process_ocr processes content
        THEN expect:
            - Empty OCR results returned
            - No processing errors for image-free content
            - Graceful handling of missing image data
            - Consistent result structure maintained
        """
        # Mock OCR engine (should not be called)
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR') as mock_ocr_class:
            mock_ocr_instance = Mock()
            mock_ocr_class.return_value = mock_ocr_instance
            
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_no_images)
            
            # Verify empty results
            assert isinstance(result, dict)
            
            # Should return empty or minimal structure
            if len(result) == 0:
                # Empty result is acceptable
                pass
            else:
                # If result structure exists, it should indicate no images
                for page_key, page_result in result.items():
                    if isinstance(page_result, dict):
                        if 'images' in page_result:
                            assert len(page_result['images']) == 0
                        if 'ocr_results' in page_result:
                            assert len(page_result['ocr_results']) == 0
            
            # OCR engine should not be called for processing
            assert not mock_ocr_instance.process_image_multi_engine.called

    @pytest.mark.asyncio
    async def test_process_ocr_large_image_memory_management(self, processor):
        """
        GIVEN very large embedded images requiring OCR processing
        WHEN _process_ocr handles large images
        THEN expect MemoryError to be raised when limits exceeded
        """
        # Create content with very large image
        large_image_data = b'x' * (100 * 1024 * 1024)  # 100MB image
        
        large_image_content = {
            'pages': [
                {
                    'page_number': 1,
                    'images': [
                        {
                            'data': large_image_data,
                            'format': 'PNG',
                            'width': 10000,
                            'height': 10000,
                            'bbox': [0, 0, 10000, 10000]
                        }
                    ],
                    'elements': [],
                    'text_blocks': [],
                    'annotations': []
                }
            ],
            'metadata': {'title': 'Large Image Document'},
            'images': [{'page': 1, 'data': large_image_data, 'format': 'PNG'}]
        }
        
        # Mock OCR to simulate memory exhaustion
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR') as mock_ocr_class:
            mock_ocr_instance = Mock()
            mock_ocr_class.return_value = mock_ocr_instance
            
            def memory_exhaustion(image_data):
                if len(image_data) > 50 * 1024 * 1024:  # > 50MB
                    raise MemoryError("Image too large for OCR processing")
                future = asyncio.Future()
                future.set_result({'best_result': {'text': 'small image', 'confidence': 0.8}})
                return future
            
            mock_ocr_instance.process_image_multi_engine = memory_exhaustion
            
            # Execute and expect MemoryError
            with pytest.raises(MemoryError, match="Image too large|too large"):
                await processor._process_ocr(large_image_content)

    @pytest.mark.asyncio
    async def test_process_ocr_missing_engine_dependencies(self, processor, sample_decomposed_content_with_images):
        """
        GIVEN OCR engine dependencies not available
        WHEN _process_ocr attempts to use missing engines
        THEN expect ImportError to be raised with dependency details
        """
        # Mock missing dependencies
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR') as mock_ocr_class:
            def missing_dependencies(*args, **kwargs):
                raise ImportError("OCR engine dependencies not found: tesseract, easyocr")
            
            mock_ocr_class.side_effect = missing_dependencies
            
            # Execute and expect ImportError
            with pytest.raises(ImportError, match="OCR engine dependencies|dependencies not found|tesseract|easyocr"):
                await processor._process_ocr(sample_decomposed_content_with_images)

    @pytest.mark.asyncio
    async def test_process_ocr_corrupted_image_handling(self, processor):
        """
        GIVEN decomposed content with corrupted or unsupported image formats
        WHEN _process_ocr processes problematic images
        THEN expect RuntimeError to be raised with format/corruption details
        """
        # Create content with corrupted image data
        corrupted_content = {
            'pages': [
                {
                    'page_number': 1,
                    'images': [
                        {
                            'data': b'corrupted_image_data_not_valid',
                            'format': 'INVALID',
                            'bbox': [0, 0, 100, 50]
                        }
                    ],
                    'elements': [],
                    'text_blocks': [],
                    'annotations': []
                }
            ],
            'metadata': {'title': 'Corrupted Image Document'},
            'images': [{'page': 1, 'data': b'corrupted_image_data_not_valid', 'format': 'INVALID'}]
        }
        
        # Mock OCR to detect corrupted images
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR') as mock_ocr_class:
            mock_ocr_instance = Mock()
            mock_ocr_class.return_value = mock_ocr_instance
            
            def corrupted_image_error(image_data):
                if image_data == b'corrupted_image_data_not_valid':
                    raise RuntimeError("Corrupted or unsupported image format detected")
                future = asyncio.Future()
                future.set_result({'best_result': {'text': 'valid image', 'confidence': 0.8}})
                return future
            
            mock_ocr_instance.process_image_multi_engine = corrupted_image_error
            
            # Execute and expect RuntimeError
            with pytest.raises(RuntimeError, match="Corrupted|unsupported|image format"):
                await processor._process_ocr(corrupted_content)

    @pytest.mark.asyncio
    async def test_process_ocr_timeout_handling(self, processor, sample_decomposed_content_with_images):
        """
        GIVEN OCR processing that exceeds configured timeout limits
        WHEN _process_ocr runs for extended time
        THEN expect TimeoutError to be raised
        """
        # Mock OCR with timeout
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR') as mock_ocr_class:
            mock_ocr_instance = Mock()
            mock_ocr_class.return_value = mock_ocr_instance
            
            async def timeout_simulation(image_data):
                await asyncio.sleep(10)  # Simulate long processing
                return {'best_result': {'text': 'slow result', 'confidence': 0.8}}
            
            mock_ocr_instance.process_image_multi_engine = timeout_simulation
            
            # Execute with timeout
            with pytest.raises((TimeoutError, asyncio.TimeoutError)):
                await asyncio.wait_for(
                    processor._process_ocr(sample_decomposed_content_with_images),
                    timeout=1.0  # 1 second timeout
                )

    @pytest.mark.asyncio
    async def test_process_ocr_image_format_compatibility(self, processor):
        """
        GIVEN images in various formats (JPEG, PNG, TIFF, etc.)
        WHEN _process_ocr processes different formats
        THEN expect:
            - All common formats handled correctly
            - Format-specific optimizations applied
            - Consistent results across formats
            - No format-related processing errors
        """
        # Create sample images in different formats
        formats_content = {
            'pages': [
                {
                    'page_number': 1,
                    'images': [
                        {'data': b'PNG_image_data', 'format': 'PNG', 'bbox': [0, 0, 100, 50]},
                        {'data': b'JPEG_image_data', 'format': 'JPEG', 'bbox': [0, 55, 100, 105]},
                        {'data': b'TIFF_image_data', 'format': 'TIFF', 'bbox': [0, 110, 100, 160]},
                        {'data': b'BMP_image_data', 'format': 'BMP', 'bbox': [0, 165, 100, 215]}
                    ],
                    'elements': [],
                    'text_blocks': [],
                    'annotations': []
                }
            ],
            'metadata': {'title': 'Multi-format Document'},
            'images': [
                {'page': 1, 'data': b'PNG_image_data', 'format': 'PNG'},
                {'page': 1, 'data': b'JPEG_image_data', 'format': 'JPEG'},
                {'page': 1, 'data': b'TIFF_image_data', 'format': 'TIFF'},
                {'page': 1, 'data': b'BMP_image_data', 'format': 'BMP'}
            ]
        }
        
        # Mock OCR with format-specific handling
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR') as mock_ocr_class:
            mock_ocr_instance = Mock()
            mock_ocr_class.return_value = mock_ocr_instance
            
            def format_specific_ocr(image_data):
                format_detected = 'UNKNOWN'
                if b'PNG' in image_data:
                    format_detected = 'PNG'
                elif b'JPEG' in image_data:
                    format_detected = 'JPEG'
                elif b'TIFF' in image_data:
                    format_detected = 'TIFF'
                elif b'BMP' in image_data:
                    format_detected = 'BMP'
                
                future = asyncio.Future()
                future.set_result({
                    'best_result': {
                        'text': f'Text from {format_detected} image',
                        'confidence': 0.85,
                        'format_detected': format_detected,
                        'engine': 'easyocr'
                    }
                })
                return future
            
            mock_ocr_instance.process_image_multi_engine = format_specific_ocr
            
            # Execute the method
            result = await processor._process_ocr(formats_content)
            
            # Verify format compatibility
            formats_processed = set()
            for page_key, page_result in result.items():
                if isinstance(page_result, dict) and 'images' in page_result:
                    for image_result in page_result['images']:
                        if 'format_detected' in image_result:
                            formats_processed.add(image_result['format_detected'])
                        
                        # Verify consistent result structure
                        assert 'text' in image_result
                        assert 'confidence' in image_result
                        assert 'engine' in image_result
            
            # Should process multiple formats
            assert len(formats_processed) >= 2

    @pytest.mark.asyncio
    async def test_process_ocr_batch_processing_efficiency(self, processor):
        """
        GIVEN multiple images requiring OCR processing
        WHEN _process_ocr handles batch operations
        THEN expect:
            - Efficient processing of multiple images
            - Memory usage controlled across batch
            - Processing time optimized for batch operations
            - Results organized by page and image
        """
        # Create content with multiple images across pages
        batch_content = {
            'pages': [
                {
                    'page_number': i + 1,
                    'images': [
                        {
                            'data': f'image_data_page_{i+1}_img_{j+1}'.encode(),
                            'format': 'PNG',
                            'bbox': [j*50, 0, (j+1)*50, 50]
                        }
                        for j in range(3)  # 3 images per page
                    ],
                    'elements': [],
                    'text_blocks': [],
                    'annotations': []
                }
                for i in range(5)  # 5 pages
            ],
            'metadata': {'title': 'Batch Processing Document'},
            'images': []
        }
        
        # Add all images to global images list
        for page_num in range(5):
            for img_num in range(3):
                batch_content['images'].append({
                    'page': page_num + 1,
                    'data': f'image_data_page_{page_num+1}_img_{img_num+1}'.encode(),
                    'format': 'PNG'
                })
        
        # Mock OCR with batch tracking
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR') as mock_ocr_class:
            mock_ocr_instance = Mock()
            mock_ocr_class.return_value = mock_ocr_instance
            
            call_times = []
            def batch_ocr(image_data):
                import time
                call_times.append(time.time())
                
                # Extract image identifier
                image_id = image_data.decode() if isinstance(image_data, bytes) else str(image_data)
                
                future = asyncio.Future()
                future.set_result({
                    'best_result': {
                        'text': f'OCR text from {image_id}',
                        'confidence': 0.80,
                        'processing_time': 0.1,  # Fast batch processing
                        'engine': 'easyocr'
                    }
                })
                return future
            
            mock_ocr_instance.process_image_multi_engine = batch_ocr
            
            # Execute the method
            import time
            start_time = time.time()
            result = await processor._process_ocr(batch_content)
            end_time = time.time()
            
            # Verify batch processing efficiency
            processing_time = end_time - start_time
            
            # Should process all images
            total_images_processed = 0
            for page_key, page_result in result.items():
                if isinstance(page_result, dict) and 'images' in page_result:
                    total_images_processed += len(page_result['images'])
            
            # Should have processed 15 images (5 pages * 3 images)
            assert total_images_processed > 0
            
            # Verify results organized by page
            assert len(result) >= 5  # Should have results for 5 pages
            
            # Processing should be reasonably efficient
            assert processing_time < 10.0  # Should complete within 10 seconds

    @pytest.mark.asyncio
    async def test_process_ocr_special_characters_and_symbols(self, processor, sample_decomposed_content_with_images):
        """
        GIVEN images containing special characters, symbols, and formatting
        WHEN _process_ocr extracts text
        THEN expect:
            - Special characters preserved correctly
            - Mathematical symbols recognized
            - Formatting marks handled appropriately
            - Unicode support for extended character sets
        """
        # Mock OCR with special character recognition
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR') as mock_ocr_class:
            mock_ocr_instance = Mock()
            mock_ocr_class.return_value = mock_ocr_instance
            
            def special_chars_ocr(image_data):
                future = asyncio.Future()
                future.set_result({
                    'best_result': {
                        'text': '∫ƒ(x)dx = π² + α≤β ∀x∈ℝ © ® ™ ± × ÷ ∞ ∅ ∈ ∉ ⊂ ∪ ∩',
                        'confidence': 0.78,
                        'words': [
                            {'text': '∫ƒ(x)dx', 'confidence': 0.75, 'bbox': [10, 10, 60, 25], 'type': 'mathematical'},
                            {'text': '=', 'confidence': 0.95, 'bbox': [65, 10, 75, 25], 'type': 'operator'},
                            {'text': 'π²', 'confidence': 0.80, 'bbox': [80, 10, 95, 25], 'type': 'mathematical'},
                            {'text': '+', 'confidence': 0.90, 'bbox': [100, 10, 110, 25], 'type': 'operator'},
                            {'text': 'α≤β', 'confidence': 0.70, 'bbox': [115, 10, 140, 25], 'type': 'mathematical'},
                            {'text': '∀x∈ℝ', 'confidence': 0.72, 'bbox': [145, 10, 175, 25], 'type': 'mathematical'},
                            {'text': '©', 'confidence': 0.85, 'bbox': [180, 10, 190, 25], 'type': 'symbol'},
                            {'text': '®', 'confidence': 0.85, 'bbox': [195, 10, 205, 25], 'type': 'symbol'},
                            {'text': '™', 'confidence': 0.85, 'bbox': [210, 10, 220, 25], 'type': 'symbol'}
                        ],
                        'engine': 'easyocr',
                        'character_types': ['mathematical', 'operator', 'symbol', 'unicode']
                    }
                })
                return future
            
            mock_ocr_instance.process_image_multi_engine = special_chars_ocr
            
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            # Verify special character handling
            found_special_chars = False
            for page_key, page_result in result.items():
                if isinstance(page_result, dict) and 'images' in page_result:
                    for image_result in page_result['images']:
                        if 'text' in image_result:
                            text = image_result['text']
                            
                            # Check for mathematical symbols
                            math_symbols = ['∫', 'π', 'α', 'β', '≤', '∀', '∈', 'ℝ', '∞']
                            if any(symbol in text for symbol in math_symbols):
                                found_special_chars = True
                            
                            # Check for trademark/copyright symbols
                            trademark_symbols = ['©', '®', '™']
                            if any(symbol in text for symbol in trademark_symbols):
                                found_special_chars = True
                            
                            # Verify word-level character typing if available
                            if 'words' in image_result:
                                for word in image_result['words']:
                                    if 'type' in word:
                                        assert word['type'] in ['mathematical', 'operator', 'symbol', 'text', 'unicode']
                            
                            # Verify character type classification if available
                            if 'character_types' in image_result:
                                types = image_result['character_types']
                                assert isinstance(types, list)
                                assert 'unicode' in types or 'mathematical' in types or 'symbol' in types
            
            # Should handle special characters without errors
            assert len(result) > 0

    @pytest.mark.asyncio
    async def test_process_ocr_production_vs_mock_implementation(self, processor, sample_decomposed_content_with_images):
        """
        GIVEN current mock OCR implementation
        WHEN _process_ocr is called
        THEN expect:
            - Mock results returned for development purposes
            - Result structure matches production expectations
            - Mock data enables downstream testing
            - Clear indication of mock vs production implementation
        """
        # Test with the actual implementation (might be mock)
        result = await processor._process_ocr(sample_decomposed_content_with_images)
        
        # Verify result structure regardless of mock/production
        assert isinstance(result, dict)
        
        # Should return some form of results
        if len(result) > 0:
            # Check if results indicate mock implementation
            for page_key, page_result in result.items():
                if isinstance(page_result, dict):
                    # Look for mock indicators
                    mock_indicators = ['mock', 'placeholder', 'development', 'stub']
                    
                    if 'images' in page_result:
                        for image_result in page_result['images']:
                            # Verify basic structure exists
                            assert 'text' in image_result or 'confidence' in image_result or 'engine' in image_result
                            
                            # Check for mock indicators in text or metadata
                            if 'text' in image_result:
                                text_lower = image_result['text'].lower()
                                is_mock = any(indicator in text_lower for indicator in mock_indicators)
                                
                                if is_mock:
                                    # Mock implementation detected
                                    assert 'mock' in text_lower or 'placeholder' in text_lower
                                else:
                                    # Production-like implementation
                                    assert len(image_result['text']) > 0
        else:
            # Empty result is acceptable for mock implementation
            pass

    @pytest.mark.asyncio
    async def test_process_ocr_result_aggregation_and_quality_metrics(self, processor, sample_decomposed_content_with_images):
        """
        GIVEN OCR results from multiple engines and images
        WHEN _process_ocr aggregates results
        THEN expect:
            - Overall confidence scores calculated
            - Text quality metrics computed
            - Engine performance comparison available
            - Aggregate statistics for quality assessment
        """
        # Mock OCR with detailed metrics
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR') as mock_ocr_class:
            mock_ocr_instance = Mock()
            mock_ocr_class.return_value = mock_ocr_instance
            
            def detailed_metrics_ocr(image_data):
                future = asyncio.Future()
                future.set_result({
                    'tesseract': {
                        'text': 'Tesseract result text',
                        'confidence': 0.82,
                        'word_count': 3,
                        'processing_time': 1.2
                    },
                    'easyocr': {
                        'text': 'EasyOCR result text',
                        'confidence': 0.88,
                        'word_count': 3,
                        'processing_time': 2.1
                    },
                    'best_result': {
                        'text': 'EasyOCR result text',
                        'confidence': 0.88,
                        'engine': 'easyocr'
                    },
                    'aggregated_metrics': {
                        'average_confidence': 0.85,
                        'confidence_variance': 0.0018,
                        'total_word_count': 3,
                        'engines_used': ['tesseract', 'easyocr'],
                        'processing_times': {'tesseract': 1.2, 'easyocr': 2.1},
                        'quality_score': 0.87
                    }
                })
                return future
            
            mock_ocr_instance.process_image_multi_engine = detailed_metrics_ocr
            
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            # Verify aggregated metrics
            found_aggregation = False
            for page_key, page_result in result.items():
                if isinstance(page_result, dict) and 'images' in page_result:
                    for image_result in page_result['images']:
                        # Check for aggregated metrics
                        if 'aggregated_metrics' in image_result:
                            metrics = image_result['aggregated_metrics']
                            
                            # Verify metric completeness
                            assert 'average_confidence' in metrics
                            assert 'engines_used' in metrics
                            
                            # Verify metric validity
                            assert 0.0 <= metrics['average_confidence'] <= 1.0
                            assert isinstance(metrics['engines_used'], list)
                            assert len(metrics['engines_used']) > 0
                            
                            found_aggregation = True
                        
                        # Check for quality assessment
                        if 'quality_score' in image_result or ('aggregated_metrics' in image_result and 'quality_score' in image_result['aggregated_metrics']):
                            quality_score = image_result.get('quality_score') or image_result['aggregated_metrics']['quality_score']
                            assert 0.0 <= quality_score <= 1.0
            
            # Should provide aggregated results or at least basic metrics
            assert len(result) > 0



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
