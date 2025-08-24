#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: tests/unit_tests/pdf_processing_/pdf_processor_/process_ocr/conftest.py
# OCR Test Fixtures and Utilities

import pytest
import os
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path
from typing import Dict, Any, List
import numpy as np
from PIL import Image
import io

# Import required modules
from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor
from ipfs_datasets_py.ipld import IPLDStorage
from ipfs_datasets_py.pdf_processing.ocr_engine import MultiEngineOCR


# Shared constants for all test classes
class OCRTestConstants:
    """Constants used across OCR tests."""
    EXPECTED_PAGE_NUMBER_ONE = 1
    EXPECTED_PAGE_NUMBER_TWO = 2
    EXPECTED_MINIMUM_RESULT_LENGTH = 1
    EXPECTED_HIGH_CONFIDENCE_THRESHOLD = 0.9
    EXPECTED_LOW_CONFIDENCE_THRESHOLD = 0.7
    EXPECTED_BBOX_COORDINATE_COUNT = 4
    EXPECTED_EMPTY_LIST_LENGTH = 0
    EXPECTED_MINIMUM_LANGUAGE_CODE_LENGTH = 2
    EXPECTED_MINIMUM_LANGUAGES_COUNT = 1
    EXPECTED_MINIMUM_ENGINES_COUNT = 2
    EXPECTED_CONFIDENCE_MIN_VALUE = 0.0
    EXPECTED_CONFIDENCE_MAX_VALUE = 1.0
    EXPECTED_MINIMUM_TEXT_LENGTH = 0
    EXPECTED_MINIMUM_NON_EMPTY_RESULT = 0
    EXPECTED_SPATIAL_OVERLAP_TOLERANCE = 5


# Base class with shared utility methods
class OCRTestBase:
    """Base class for OCR tests with shared utility methods."""
    
    def create_mock_ocr_future(self, result_data):
        """Helper to create asyncio Future with OCR result."""
        future = asyncio.Future()
        future.set_result(result_data)
        return future

    def assert_basic_ocr_result_structure(self, result):
        """Common assertions for OCR result structure."""
        assert isinstance(result, dict), f"Expected dict, got {type(result)}: {result}"
        assert len(result) >= OCRTestConstants.EXPECTED_MINIMUM_RESULT_LENGTH, f"Expected result length >= {OCRTestConstants.EXPECTED_MINIMUM_RESULT_LENGTH}, got {len(result)}: {result}"

        for key, page_result in result.items():
            assert 'page' in str(key).lower(), f"Expected 'page' in key {key}, got: {str(key).lower()}"
            assert isinstance(page_result, dict), f"Expected dict for page_result, got {type(page_result)}: {page_result}"
            assert 'images' in page_result, f"'images' not found in page_result keys: {list(page_result.keys())}"

    def assert_image_result_structure(self, image_result):
        """Common assertions for individual image OCR results."""
        assert 'text' in image_result, f"'text' not found in image_result keys: {list(image_result.keys())}"
        assert 'confidence' in image_result, f"'confidence' not found in image_result keys: {list(image_result.keys())}"
        assert 'engine' in image_result, f"'engine' not found in image_result keys: {list(image_result.keys())}"
        assert 'words' in image_result, f"'words' not found in image_result keys: {list(image_result.keys())}"

    def assert_word_structure(self, word):
        """Common assertions for word-level OCR results."""
        assert 'text' in word, f"'text' not found in word keys: {list(word.keys())}"
        assert 'confidence' in word, f"'confidence' not found in word keys: {list(word.keys())}"
        assert 'bbox' in word, f"'bbox' not found in word keys: {list(word.keys())}"
        assert len(word['bbox']) == OCRTestConstants.EXPECTED_BBOX_COORDINATE_COUNT, f"Expected bbox length {OCRTestConstants.EXPECTED_BBOX_COORDINATE_COUNT}, got {len(word['bbox'])}: {word['bbox']}"

    def assert_confidence_range(self, confidence, min_val=None, max_val=None):
        """Assert confidence is within valid range."""
        min_val = min_val or OCRTestConstants.EXPECTED_CONFIDENCE_MIN_VALUE
        max_val = max_val or OCRTestConstants.EXPECTED_CONFIDENCE_MAX_VALUE
        assert min_val <= confidence <= max_val, f"Confidence {confidence} not in range [{min_val}, {max_val}]"


# Shared fixtures for all OCR test classes
@pytest.fixture
def sample_image_data():
    """Create sample image data for testing."""
    sample_image = Image.new('RGB', (100, 50), color='white')
    img_buffer = io.BytesIO()
    sample_image.save(img_buffer, format='PNG')
    return img_buffer.getvalue()


@pytest.fixture
def sample_decomposed_content_with_images(sample_image_data):
    """Sample decomposed content with embedded images for OCR testing."""
    return {
        'pages': [
            {
                'page_number': 1,
                'elements': [
                    {'type': 'text', 'content': 'Regular text content'},
                    {'type': 'image', 'content': sample_image_data, 'bbox': [10, 10, 110, 60]}
                ],
                'images': [
                    {
                        'data': sample_image_data,
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
                    {'type': 'image', 'content': sample_image_data, 'bbox': [20, 20, 120, 70]}
                ],
                'images': [
                    {
                        'data': sample_image_data,
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
            {'page': 1, 'data': sample_image_data, 'format': 'PNG'},
            {'page': 2, 'data': sample_image_data, 'format': 'JPEG'}
        ]
    }


@pytest.fixture
def sample_decomposed_content_no_images():
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
def mock_ocr_engine():
    """Mock OCR engine with realistic responses."""
    mock_engine = MagicMock(spec=MultiEngineOCR)
    
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


@pytest.fixture
def processor():
    """Create PDFProcessor instance for testing."""
    mock_dict = {
        "ipld_storage": MagicMock(spec_set=IPLDStorage),
        "ocr_engine": MagicMock(spec=MultiEngineOCR),
    }
    return PDFProcessor(mock_dict=mock_dict)


@pytest.fixture
def mock_multi_engine_ocr_class():
    """Mock MultiEngineOCR class for patching."""
    mock_instance = Mock()
    mock_class = Mock(return_value=mock_instance)
    return mock_class, mock_instance


@pytest.fixture
def standard_ocr_result():
    """Standard OCR result format."""
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


@pytest.fixture
def high_quality_ocr_result():
    """High quality OCR result format."""
    return {
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


@pytest.fixture
def low_quality_ocr_result():
    """Low quality OCR result format."""
    return {
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


@pytest.fixture
def multilingual_ocr_result():
    """Multilingual OCR result format."""
    return {
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


@pytest.fixture
def large_image_content():
    """Content with very large image for memory testing."""
    large_image_data = b'x' * (100 * 1024 * 1024)  # 100MB image
    return {
        'pages': [
            {
                'page_number': OCRTestConstants.EXPECTED_PAGE_NUMBER_ONE,
                'images': [
                    {
                        'data': large_image_data,
                        'format': 'PNG',
                        'width': 10000,
                        'height': 10000,
                        'bbox': [OCRTestConstants.EXPECTED_MINIMUM_NON_EMPTY_RESULT, 
                                OCRTestConstants.EXPECTED_MINIMUM_NON_EMPTY_RESULT, 10000, 10000]
                    }
                ],
                'elements': [],
                'text_blocks': [],
                'annotations': []
            }
        ],
        'metadata': {'title': 'Large Image Document'},
        'images': [{'page': OCRTestConstants.EXPECTED_PAGE_NUMBER_ONE, 'data': large_image_data, 'format': 'PNG'}]
    }


@pytest.fixture
def corrupted_image_content():
    """Content with corrupted image data."""
    return {
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


@pytest.fixture
def multi_format_image_content():
    """Content with images in various formats."""
    return {
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


def _create_mock_processor_with_ocr_result(ocr_result):
    """Helper to create PDFProcessor with mocked OCR result."""
    mock_ocr = MagicMock(spec=MultiEngineOCR)
    mock_ocr.extract_with_ocr = AsyncMock(return_value=ocr_result)
    
    mock_dict = {
        "ipld_storage": MagicMock(spec_set=IPLDStorage),
        "ocr_engine": mock_ocr,
    }
    return PDFProcessor(mock_dict=mock_dict)


def _create_mock_ocr_future(result_data):
    """Helper to create asyncio Future with OCR result."""
    future = asyncio.Future()
    future.set_result(result_data)
    return future


@pytest.fixture
def mock_process_engines_best_result(image_data):
    return _create_mock_ocr_future({
        'best_result': {
            'text': 'EasyOCR extracted text',
            'confidence': 0.90,
            'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
            'engine': 'easyocr'
        }
    })

@pytest.fixture
def detailed_metrics_ocr(image_data):
    return _create_mock_ocr_future({
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

@pytest.fixture
def multi_engine_comparison(image_data):
    return _create_mock_ocr_future({
        'best_result': {
            'text': 'EasyOCR result',
            'confidence': 0.91,
            'engine': 'easyocr',
            'selected_reason': 'highest_confidence'
        }
    })

@pytest.fixture
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
    
    return _create_mock_ocr_future({
        'best_result': {
            'text': f'Text from {format_detected} image',
            'confidence': 0.85,
            'format_detected': format_detected,
            'engine': 'easyocr'
        }
    })


@pytest.fixture
def high_quality_ocr(image_data):
    """Mock high quality OCR result."""
    return _create_mock_ocr_future(
        {'best_result': high_quality_ocr_result}
    )

@pytest.fixture
def low_quality_ocr(image_data):
    """Mock low quality OCR result."""
    return _create_mock_ocr_future(
        {'best_result': low_quality_ocr_result}
    )


# Additional OCR mock fixtures for different scenarios
@pytest.fixture
def mock_process_engines():
    """Basic mock process engines function."""
    def process_engines(image_data):
        return _create_mock_ocr_future({
            'tesseract': {
                'text': 'Basic OCR text',
                'confidence': 0.85,
                'words': [
                    {'text': 'Basic', 'confidence': 0.9, 'bbox': [10, 10, 50, 25]},
                    {'text': 'OCR', 'confidence': 0.8, 'bbox': [55, 10, 75, 25]},
                    {'text': 'text', 'confidence': 0.85, 'bbox': [80, 10, 110, 25]}
                ],
                'engine': 'tesseract'
            },
            'easyocr': {
                'text': 'Basic OCR text',
                'confidence': 0.88,
                'words': [
                    {'text': 'Basic', 'confidence': 0.92, 'bbox': [10, 10, 50, 25]},
                    {'text': 'OCR', 'confidence': 0.85, 'bbox': [55, 10, 75, 25]},
                    {'text': 'text', 'confidence': 0.87, 'bbox': [80, 10, 110, 25]}
                ],
                'engine': 'easyocr'
            },
            'best_result': {
                'text': 'Basic OCR text',
                'confidence': 0.88,
                'words': [
                    {'text': 'Basic', 'confidence': 0.92, 'bbox': [10, 10, 50, 25]},
                    {'text': 'OCR', 'confidence': 0.85, 'bbox': [55, 10, 75, 25]},
                    {'text': 'text', 'confidence': 0.87, 'bbox': [80, 10, 110, 25]}
                ],
                'engine': 'easyocr'
            }
        })
    return process_engines


@pytest.fixture
def mock_process_engines_best_result():
    """Mock process engines that returns best result data."""
    def process_engines(image_data):
        return _create_mock_ocr_future({
            'best_result': {
                'text': 'EasyOCR extracted text',
                'confidence': 0.90,
                'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                'engine': 'easyocr'
            }
        })
    return process_engines


@pytest.fixture 
def varying_confidence_ocr():
    """Mock OCR with varying confidence levels for quality testing."""
    call_count = 0
    def process_engines(image_data):
        nonlocal call_count
        call_count += 1
        
        # Simulate different quality images
        if call_count == 1:  # High quality
            confidence = 0.92
            text = "Clear high quality text"
        else:  # Lower quality  
            confidence = 0.65
            text = "blu77y l0w qu4l1ty t3xt"
        
        return _create_mock_ocr_future({
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
    return process_engines


@pytest.fixture
def multi_engine_comparison_ocr():
    """Mock OCR with comprehensive multi-engine comparison data."""
    def process_engines(image_data):
        return _create_mock_ocr_future({
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
    return process_engines


@pytest.fixture
def processor_with_mock_ocr(mock_process_engines):
    """PDFProcessor with mocked OCR engine using dependency injection."""
    mock_ocr = MagicMock(spec=MultiEngineOCR)
    # The actual method calls extract_with_ocr, not process_image_multi_engine
    mock_ocr.extract_with_ocr = AsyncMock(return_value={
        'text': 'Sample OCR extracted text',
        'confidence': 0.85,
        'engine': 'tesseract',
        'word_boxes': [
            {'text': 'Sample', 'confidence': 0.9, 'bbox': [10, 10, 50, 25]},
            {'text': 'OCR', 'confidence': 0.8, 'bbox': [55, 10, 75, 25]},
            {'text': 'extracted', 'confidence': 0.85, 'bbox': [80, 10, 140, 25]},
            {'text': 'text', 'confidence': 0.85, 'bbox': [145, 10, 170, 25]}
        ]
    })
    
    mock_dict = {
        "ipld_storage": MagicMock(spec_set=IPLDStorage),
        "ocr_engine": mock_ocr,
    }
    return PDFProcessor(mock_dict=mock_dict)


@pytest.fixture
def processor_with_varying_confidence_ocr(varying_confidence_ocr):
    """PDFProcessor with varying confidence OCR mock."""
    mock_ocr = MagicMock(spec=MultiEngineOCR)
    # Mock the actual method called by _process_ocr
    mock_ocr.extract_with_ocr = AsyncMock(return_value={
        'text': 'Clear high quality text',
        'confidence': 0.92,
        'engine': 'easyocr',
        'word_boxes': [
            {'text': 'Clear', 'confidence': 0.95, 'bbox': [10, 10, 50, 25]},
            {'text': 'high', 'confidence': 0.93, 'bbox': [55, 10, 85, 25]},
            {'text': 'quality', 'confidence': 0.90, 'bbox': [90, 10, 140, 25]},
            {'text': 'text', 'confidence': 0.92, 'bbox': [145, 10, 170, 25]}
        ]
    })
    
    mock_dict = {
        "ipld_storage": MagicMock(spec_set=IPLDStorage),
        "ocr_engine": mock_ocr,
    }
    return PDFProcessor(mock_dict=mock_dict)


@pytest.fixture
def processor_with_multi_engine_comparison(multi_engine_comparison_ocr):
    """PDFProcessor with multi-engine comparison OCR mock."""
    mock_ocr = MagicMock(spec=MultiEngineOCR)
    mock_ocr.process_image_multi_engine = multi_engine_comparison_ocr
    
    mock_dict = {
        "ipld_storage": MagicMock(spec_set=IPLDStorage),
        "ocr_engine": mock_ocr,
    }
    return PDFProcessor(mock_dict=mock_dict)


@pytest.fixture
def memory_exhaustion_ocr():
    """OCR mock that raises MemoryError for large images."""
    def process_engines(image_data):
        if len(image_data) > 50 * 1024 * 1024:  # > 50MB
            raise MemoryError("Image too large for OCR processing")
        return _create_mock_ocr_future({'best_result': {'text': 'small image', 'confidence': 0.8}})
    return process_engines


@pytest.fixture
def corrupted_image_ocr():
    """OCR mock that raises RuntimeError for corrupted images."""
    def process_engines(image_data):
        if image_data == b'corrupted_image_data_not_valid':
            raise RuntimeError("Corrupted or unsupported image format detected")
        return _create_mock_ocr_future({'best_result': {'text': 'valid image', 'confidence': 0.8}})
    return process_engines


@pytest.fixture
def timeout_ocr():
    """OCR mock that simulates timeout."""
    async def process_engines(image_data):
        await asyncio.sleep(10)  # Simulate long processing
        return {'best_result': {'text': 'slow result', 'confidence': 0.8}}
    return process_engines


@pytest.fixture
def processor_with_memory_exhaustion_ocr(memory_exhaustion_ocr):
    """PDFProcessor with memory exhaustion OCR mock."""
    mock_ocr = MagicMock(spec=MultiEngineOCR)
    mock_ocr.process_image_multi_engine = memory_exhaustion_ocr
    
    mock_dict = {
        "ipld_storage": MagicMock(spec_set=IPLDStorage),
        "ocr_engine": mock_ocr,
    }
    return PDFProcessor(mock_dict=mock_dict)


@pytest.fixture
def processor_with_corrupted_image_ocr(corrupted_image_ocr):
    """PDFProcessor with corrupted image OCR mock."""
    mock_ocr = MagicMock(spec=MultiEngineOCR)
    mock_ocr.process_image_multi_engine = corrupted_image_ocr
    
    mock_dict = {
        "ipld_storage": MagicMock(spec_set=IPLDStorage),
        "ocr_engine": mock_ocr,
    }
    return PDFProcessor(mock_dict=mock_dict)


@pytest.fixture
def processor_with_timeout_ocr(timeout_ocr):
    """PDFProcessor with timeout OCR mock."""
    mock_ocr = MagicMock(spec=MultiEngineOCR)
    mock_ocr.process_image_multi_engine = timeout_ocr
    
    mock_dict = {
        "ipld_storage": MagicMock(spec_set=IPLDStorage),
        "ocr_engine": mock_ocr,
    }
    return PDFProcessor(mock_dict=mock_dict)


# Shared OCR result fixtures
@pytest.fixture
def high_quality_ocr_result_data():
    """High quality OCR result data."""
    return {
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


@pytest.fixture
def low_quality_ocr_result_data():
    """Low quality OCR result data."""
    return {
        'text': 'p4rt14l t3xt 3xtr4ct3d',  # Simulated OCR errors
        'confidence': 0.45,
        'word_boxes': [
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


@pytest.fixture
def processor_with_high_quality_ocr(high_quality_ocr_result_data):
    """PDFProcessor with high quality OCR mock."""
    return _create_mock_processor_with_ocr_result(high_quality_ocr_result_data)


@pytest.fixture
def processor_with_low_quality_ocr(low_quality_ocr_result_data):
    """PDFProcessor with low quality OCR mock."""
    return _create_mock_processor_with_ocr_result(low_quality_ocr_result_data)


@pytest.fixture
def processor_with_positioning_ocr():
    """PDFProcessor with positioning OCR capabilities."""
    positioning_result = {
        'text': 'Positioned text content',
        'confidence': 0.90,
        'engine': 'easyocr',
        'word_boxes': [
            {'text': 'Positioned', 'confidence': 0.92, 'bbox': [10, 10, 80, 25]},
            {'text': 'text', 'confidence': 0.90, 'bbox': [85, 10, 115, 25]},
            {'text': 'content', 'confidence': 0.88, 'bbox': [120, 10, 180, 25]}
        ]
    }
    return _create_mock_processor_with_ocr_result(positioning_result)


@pytest.fixture
def multilingual_ocr_result_data():
    """Mock OCR result data for multilingual text scenarios."""
    return {
        "text": "Hello World 你好世界 مرحبا بالعالم",
        "confidence": 0.85,
        "engine": "tesseract",
        "word_boxes": [
            {"text": "Hello", "confidence": 0.92, "bbox": [0, 0, 50, 20], "language": "en"},
            {"text": "World", "confidence": 0.90, "bbox": [55, 0, 100, 20], "language": "en"},
            {"text": "你好", "confidence": 0.88, "bbox": [105, 0, 140, 20], "language": "zh-CN"},
            {"text": "世界", "confidence": 0.86, "bbox": [145, 0, 180, 20], "language": "zh-CN"},
            {"text": "مرحبا", "confidence": 0.84, "bbox": [185, 0, 230, 20], "language": "ar"},
            {"text": "بالعالم", "confidence": 0.82, "bbox": [235, 0, 280, 20], "language": "ar"},
        ],
        "languages_detected": ["en", "zh-CN", "ar"],
        "quality_metrics": {
            "clarity": 0.75,
            "text_density": 0.80,
            "unicode_coverage": 0.95
        }
    }


@pytest.fixture
def processor_with_multilingual_ocr(multilingual_ocr_result_data):
    """PDFProcessor with multilingual OCR capabilities."""
    # Remove languages_detected from the base result since the actual implementation doesn't return it
    actual_result = multilingual_ocr_result_data.copy()
    # Keep languages_detected for tests that expect it from the raw OCR engine data
    return _create_mock_processor_with_ocr_result(actual_result)


@pytest.fixture
def processor_with_engine_comparison_ocr():
    """PDFProcessor with engine comparison OCR mock that has engine_comparison data."""
    comparison_result = {
        'text': 'Clear high quality text',
        'confidence': 0.92,
        'engine': 'easyocr',
        'word_boxes': [
            {'text': 'Clear', 'confidence': 0.95, 'bbox': [10, 10, 50, 25]},
            {'text': 'high', 'confidence': 0.93, 'bbox': [55, 10, 85, 25]},
            {'text': 'quality', 'confidence': 0.90, 'bbox': [90, 10, 140, 25]},
            {'text': 'text', 'confidence': 0.92, 'bbox': [145, 10, 170, 25]}
        ],
        'engine_comparison': {
            'tesseract': 0.87,
            'easyocr': 0.92
        }
    }
    return _create_mock_processor_with_ocr_result(comparison_result)


@pytest.fixture
def processor_with_varying_confidence_ocr():
    """PDFProcessor with varying confidence OCR mock simulating different quality images."""
    varying_result = {
        'text': 'Clear high quality text',
        'confidence': 0.92,
        'engine': 'easyocr',
        'word_boxes': [
            {'text': 'Clear', 'confidence': 0.95, 'bbox': [10, 10, 50, 25]},
            {'text': 'high', 'confidence': 0.93, 'bbox': [55, 10, 85, 25]},
            {'text': 'quality', 'confidence': 0.90, 'bbox': [90, 10, 140, 25]},
            {'text': 'text', 'confidence': 0.92, 'bbox': [145, 10, 170, 25]}
        ],
        'engine_comparison': {
            'tesseract': 0.87,
            'easyocr': 0.92
        }
    }
    return _create_mock_processor_with_ocr_result(varying_result)


@pytest.fixture
def processor_with_multi_engine_comparison_ocr():
    """PDFProcessor with multi-engine comparison OCR mock."""
    multi_engine_result = {
        'text': 'EasyOCR result with better accuracy',
        'confidence': 0.91,
        'engine': 'easyocr',
        'word_boxes': [
            {'text': 'EasyOCR', 'confidence': 0.91, 'bbox': [10, 10, 60, 25]},
            {'text': 'result', 'confidence': 0.91, 'bbox': [65, 10, 105, 25]},
            {'text': 'with', 'confidence': 0.91, 'bbox': [110, 10, 135, 25]},
            {'text': 'better', 'confidence': 0.91, 'bbox': [140, 10, 180, 25]},
            {'text': 'accuracy', 'confidence': 0.91, 'bbox': [185, 10, 235, 25]}
        ]
    }
    # Add additional metadata that tests expect
    multi_engine_result.update({
        'selected_reason': 'highest_confidence',
        'all_engines': {
            'tesseract': 0.82,
            'easyocr': 0.91,
            'paddleocr': 0.75
        }
    })
    return _create_mock_processor_with_ocr_result(multi_engine_result)


@pytest.fixture
def processor_with_varying_confidence_ocr():
    """PDFProcessor with varying confidence OCR mock simulating different quality images."""
    mock_ocr = MagicMock(spec=MultiEngineOCR)
    
    # Create a call counter to simulate different results
    call_count = [0]  # Use list to make it mutable in nested function
    
    async def varying_ocr_side_effect(image_data, **kwargs):
        call_count[0] += 1
        
        # Simulate different quality images
        if call_count[0] == 1:  # High quality
            confidence = 0.92
            text = "Clear high quality text"
        else:  # Lower quality
            confidence = 0.65
            text = "blu77y l0w qu4l1ty t3xt"
        
        return {
            'text': text,
            'confidence': confidence,
            'engine': 'easyocr' if confidence > 0.8 else 'tesseract',
            'word_boxes': [
                {'text': 'Clear', 'confidence': confidence, 'bbox': [10, 10, 50, 25]},
                {'text': 'high', 'confidence': confidence - 0.02, 'bbox': [55, 10, 85, 25]},
                {'text': 'quality', 'confidence': confidence - 0.01, 'bbox': [90, 10, 140, 25]},
                {'text': 'text', 'confidence': confidence, 'bbox': [145, 10, 170, 25]}
            ]
        }
    
    mock_ocr.extract_with_ocr = varying_ocr_side_effect
    
    mock_dict = {
        "ipld_storage": MagicMock(spec_set=IPLDStorage),
        "ocr_engine": mock_ocr,
    }
    return PDFProcessor(mock_dict=mock_dict)


@pytest.fixture
def processor_with_memory_error_ocr():
    """PDFProcessor with OCR mock that raises MemoryError for large images."""
    mock_ocr = MagicMock(spec=MultiEngineOCR)
    
    def memory_error_side_effect(image_data, **kwargs):
        if len(image_data) > 50 * 1024 * 1024:  # > 50MB
            raise MemoryError("Image too large for OCR processing")
        return {
            'text': 'small image', 
            'confidence': 0.8,
            'engine': 'tesseract',
            'word_boxes': []
        }
    
    mock_ocr.extract_with_ocr = AsyncMock(side_effect=memory_error_side_effect)
    
    mock_dict = {
        "ipld_storage": MagicMock(spec_set=IPLDStorage),
        "ocr_engine": mock_ocr,
    }
    return PDFProcessor(mock_dict=mock_dict)


@pytest.fixture
def processor_with_missing_dependencies_ocr():
    """PDFProcessor with OCR mock that raises ImportError for missing dependencies."""
    mock_ocr = MagicMock(spec=MultiEngineOCR)
    mock_ocr.extract_with_ocr = AsyncMock(side_effect=ImportError("OCR engine dependencies not found: tesseract, easyocr"))
    
    mock_dict = {
        "ipld_storage": MagicMock(spec_set=IPLDStorage),
        "ocr_engine": mock_ocr,
    }
    return PDFProcessor(mock_dict=mock_dict)


@pytest.fixture
def processor_with_corrupted_image_ocr():
    """PDFProcessor with OCR mock that handles corrupted image errors."""
    mock_ocr = MagicMock(spec=MultiEngineOCR)
    
    def corrupted_image_side_effect(image_data, **kwargs):
        if image_data == b'corrupted_image_data_not_valid':
            raise RuntimeError("Unable to process corrupted image format")
        return {
            'text': 'valid image processed', 
            'confidence': 0.75,
            'engine': 'tesseract',
            'word_boxes': []
        }
    
    mock_ocr.extract_with_ocr = AsyncMock(side_effect=corrupted_image_side_effect)
    
    mock_dict = {
        "ipld_storage": MagicMock(spec_set=IPLDStorage),
        "ocr_engine": mock_ocr,
    }
    return PDFProcessor(mock_dict=mock_dict)


@pytest.fixture
def processor_with_timeout_ocr():
    """PDFProcessor with OCR mock that simulates timeout."""
    mock_ocr = MagicMock(spec=MultiEngineOCR)
    
    async def timeout_side_effect(image_data, **kwargs):
        await asyncio.sleep(10)  # Simulate long processing
        return {
            'text': 'slow result', 
            'confidence': 0.8,
            'engine': 'tesseract',
            'word_boxes': []
        }
    
    mock_ocr.extract_with_ocr = timeout_side_effect
    
    mock_dict = {
        "ipld_storage": MagicMock(spec_set=IPLDStorage),
        "ocr_engine": mock_ocr,
    }
    return PDFProcessor(mock_dict=mock_dict)


@pytest.fixture
def processor_with_format_specific_ocr():
    """PDFProcessor with format-specific OCR capabilities."""
    format_specific_result = {
        'text': 'Text from PNG image',
        'confidence': 0.85,
        'engine': 'easyocr',
        'format_detected': 'PNG',
        'word_boxes': [
            {'text': 'Text', 'confidence': 0.85, 'bbox': [10, 10, 35, 25]},
            {'text': 'from', 'confidence': 0.85, 'bbox': [40, 10, 70, 25]},
            {'text': 'PNG', 'confidence': 0.85, 'bbox': [75, 10, 105, 25]},
            {'text': 'image', 'confidence': 0.85, 'bbox': [110, 10, 150, 25]}
        ]
    }
    return _create_mock_processor_with_ocr_result(format_specific_result)


@pytest.fixture
def processor_with_detailed_metrics_ocr():
    """PDFProcessor with detailed metrics OCR capabilities."""
    detailed_metrics_result = {
        'text': 'EasyOCR result text',
        'confidence': 0.88,
        'engine': 'easyocr',
        'word_boxes': [
            {'text': 'EasyOCR', 'confidence': 0.88, 'bbox': [10, 10, 60, 25]},
            {'text': 'result', 'confidence': 0.88, 'bbox': [65, 10, 105, 25]},
            {'text': 'text', 'confidence': 0.88, 'bbox': [110, 10, 140, 25]}
        ],
        'aggregated_metrics': {
            'average_confidence': 0.85,
            'confidence_variance': 0.0018,
            'total_word_count': 3,
            'engines_used': ['tesseract', 'easyocr'],
            'processing_times': {'tesseract': 1.2, 'easyocr': 2.1},
            'quality_score': 0.87
        }
    }
    return _create_mock_processor_with_ocr_result(detailed_metrics_result)
