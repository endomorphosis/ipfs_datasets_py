
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: tests/unit_tests/pdf_processing_/pdf_processor_/process_ocr/test_process_ocr.py
# Refactored OCR tests with single assertions and dependency injection

import pytest
import os
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
assert PDFProcessor.process_pdf, f"PDFProcessor.process_pdf method not accessible: {PDFProcessor.process_pdf}"
assert PDFProcessor._validate_and_analyze_pdf, f"PDFProcessor._validate_and_analyze_pdf method not accessible: {PDFProcessor._validate_and_analyze_pdf}"
assert PDFProcessor._decompose_pdf, f"PDFProcessor._decompose_pdf method not accessible: {PDFProcessor._decompose_pdf}"
assert PDFProcessor._extract_page_content, f"PDFProcessor._extract_page_content method not accessible: {PDFProcessor._extract_page_content}"
assert PDFProcessor._create_ipld_structure, f"PDFProcessor._create_ipld_structure method not accessible: {PDFProcessor._create_ipld_structure}"
assert PDFProcessor._process_ocr, f"PDFProcessor._process_ocr method not accessible: {PDFProcessor._process_ocr}"
assert PDFProcessor._optimize_for_llm, f"PDFProcessor._optimize_for_llm method not accessible: {PDFProcessor._optimize_for_llm}"
assert PDFProcessor._extract_entities, f"PDFProcessor._extract_entities method not accessible: {PDFProcessor._extract_entities}"
assert PDFProcessor._create_embeddings, f"PDFProcessor._create_embeddings method not accessible: {PDFProcessor._create_embeddings}"
assert PDFProcessor._integrate_with_graphrag, f"PDFProcessor._integrate_with_graphrag method not accessible: {PDFProcessor._integrate_with_graphrag}"
assert PDFProcessor._analyze_cross_document_relationships, f"PDFProcessor._analyze_cross_document_relationships method not accessible: {PDFProcessor._analyze_cross_document_relationships}"
assert PDFProcessor._setup_query_interface, f"PDFProcessor._setup_query_interface method not accessible: {PDFProcessor._setup_query_interface}"
assert PDFProcessor._calculate_file_hash, f"PDFProcessor._calculate_file_hash method not accessible: {PDFProcessor._calculate_file_hash}"
assert PDFProcessor._extract_native_text, f"PDFProcessor._extract_native_text method not accessible: {PDFProcessor._extract_native_text}"
assert PDFProcessor._get_processing_time, f"PDFProcessor._get_processing_time method not accessible: {PDFProcessor._get_processing_time}"
assert PDFProcessor._get_quality_scores, f"PDFProcessor._get_quality_scores method not accessible: {PDFProcessor._get_quality_scores}"

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

from tests.unit_tests.pdf_processing_.pdf_processor_.process_ocr.conftest import (
    OCRTestConstants, OCRTestBase
)

class TestOCRBasicFunctionality(OCRTestBase):
    """Test basic OCR functionality and data structure validation."""

    @pytest.mark.asyncio
    async def test_process_ocr_returns_dict(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect returned result is a dictionary
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        assert isinstance(result, dict), f"Expected dict, got {type(result)}: {result}"

    @pytest.mark.asyncio
    async def test_process_ocr_has_minimum_length(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect returned result has minimum expected length
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        assert len(result) >= OCRTestConstants.EXPECTED_MINIMUM_RESULT_LENGTH, \
            f"Expected result length >= {OCRTestConstants.EXPECTED_MINIMUM_RESULT_LENGTH}, got {len(result)}: {result}"

    @pytest.mark.asyncio
    async def test_process_ocr_has_page_key(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect result contains page 1 key
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        assert 1 in result, f"Page 1 not found in result keys: {list(result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_calls_ocr_engine(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect OCR engine extract_with_ocr method is called
        """
        await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        assert processor_with_mock_ocr.ocr_engine.extract_with_ocr.called, \
            f"OCR engine extract_with_ocr was not called: {processor_with_mock_ocr.ocr_engine.extract_with_ocr.called}"


class TestOCRDataStructure(OCRTestBase):
    """Test OCR result data structure validation."""

    @pytest.mark.asyncio
    async def test_process_ocr_first_page_result_is_dict(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first page result is a list
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        first_page_result = list(result.values())[0]
        assert isinstance(first_page_result, list), f"Expected list for page_result, got {type(first_page_result)}: {first_page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_first_page_has_images_key(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first page result contains image results
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        first_page_result = list(result.values())[0]
        assert len(first_page_result) > 0, f"Expected non-empty image results list, got: {first_page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_first_image_has_text_key(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first image result contains 'text' key
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        first_page_result = list(result.values())[0]
        first_image_result = first_page_result[0]
        assert 'text' in first_image_result, f"'text' not found in image_result keys: {list(first_image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_first_image_has_confidence_key(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first image result contains 'confidence' key
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        first_page_result = list(result.values())[0]
        first_image_result = first_page_result[0]
        assert 'confidence' in first_image_result, f"'confidence' not found in image_result keys: {list(first_image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_first_image_has_engine_key(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first image result contains 'engine_used' key
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        first_page_result = list(result.values())[0]
        first_image_result = first_page_result[0]
        assert 'engine_used' in first_image_result, f"'engine_used' not found in image_result keys: {list(first_image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_first_image_has_words_key(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first image result contains 'word_boxes' key
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        first_page_result = list(result.values())[0]
        first_image_result = first_page_result[0]
        assert 'word_boxes' in first_image_result, f"'word_boxes' not found in image_result keys: {list(first_image_result.keys())}"


class TestOCRWordStructure(OCRTestBase):
    """Test word-level OCR result structure validation."""

    @pytest.mark.asyncio
    async def test_process_ocr_first_word_has_text_key(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first word contains 'text' key
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        first_page_result = list(result.values())[0]
        first_image_result = first_page_result[0]
        first_word = first_image_result['word_boxes'][0]
        assert 'text' in first_word, f"'text' not found in word keys: {list(first_word.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_first_word_has_confidence_key(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first word contains 'confidence' key
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        first_page_result = list(result.values())[0]
        first_image_result = first_page_result[0]
        first_word = first_image_result['word_boxes'][0]
        assert 'confidence' in first_word, f"'confidence' not found in word keys: {list(first_word.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_first_word_has_bbox_key(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first word contains 'bbox' key
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        first_page_result = list(result.values())[0]
        first_image_result = first_page_result[0]
        first_word = first_image_result['word_boxes'][0]
        assert 'bbox' in first_word, f"'bbox' not found in word keys: {list(first_word.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_first_word_bbox_has_correct_length(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first word bbox has 4 coordinates
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        first_page_result = list(result.values())[0]
        first_image_result = first_page_result[0]
        first_word = first_image_result['word_boxes'][0]
        assert len(first_word['bbox']) == OCRTestConstants.EXPECTED_BBOX_COORDINATE_COUNT, \
            f"Expected bbox length {OCRTestConstants.EXPECTED_BBOX_COORDINATE_COUNT}, got {len(first_word['bbox'])}: {first_word['bbox']}"


class TestOCRQualityHandling(OCRTestBase):
    """Test OCR quality handling with high and low quality scenarios."""

    @pytest.mark.asyncio
    async def test_process_ocr_high_quality_confidence_above_threshold(self, processor_with_high_quality_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images with clear, high-resolution text
        WHEN _process_ocr extracts text
        THEN expect high confidence scores (>0.9)
        """
        result = await processor_with_high_quality_ocr._process_ocr(sample_decomposed_content_with_images)
        
        found_high_confidence = False
        for page_key, page_result in result.items():
            for image_result in page_result:
                if image_result['confidence'] >= OCRTestConstants.EXPECTED_HIGH_CONFIDENCE_THRESHOLD:
                    found_high_confidence = True
                    break
        assert found_high_confidence, "No high confidence results found"

    @pytest.mark.asyncio
    async def test_process_ocr_high_quality_word_confidence_above_threshold(self, processor_with_high_quality_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images with clear, high-resolution text
        WHEN _process_ocr extracts text
        THEN expect word-level high confidence scores (>0.9)
        """
        result = await processor_with_high_quality_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_key, page_result in result.items():
            for image_result in page_result:
                for word in image_result['word_boxes']:
                    assert word['confidence'] >= OCRTestConstants.EXPECTED_HIGH_CONFIDENCE_THRESHOLD, \
                        f"Word confidence {word['confidence']} below threshold {OCRTestConstants.EXPECTED_HIGH_CONFIDENCE_THRESHOLD}"

    @pytest.mark.asyncio
    async def test_process_ocr_low_quality_confidence_below_threshold(self, processor_with_low_quality_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images with poor quality, low resolution, or distorted text
        WHEN _process_ocr processes challenging images
        THEN expect lower confidence scores reflecting quality
        """
        result = await processor_with_low_quality_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_key, page_result in result.items():
            for image_result in page_result:
                assert image_result['confidence'] < OCRTestConstants.EXPECTED_LOW_CONFIDENCE_THRESHOLD, \
                    f"Expected confidence < {OCRTestConstants.EXPECTED_LOW_CONFIDENCE_THRESHOLD}, got {image_result['confidence']}"

    @pytest.mark.asyncio
    async def test_process_ocr_low_quality_partial_text_extraction(self, processor_with_low_quality_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images with poor quality, low resolution, or distorted text
        WHEN _process_ocr processes challenging images
        THEN expect partial text extraction where possible
        """
        result = await processor_with_low_quality_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_key, page_result in result.items():
            for image_result in page_result:
                assert len(image_result['text']) > OCRTestConstants.EXPECTED_MINIMUM_TEXT_LENGTH, \
                    f"Expected text length > {OCRTestConstants.EXPECTED_MINIMUM_TEXT_LENGTH}, got {len(image_result['text'])}: {image_result['text']}"

    @pytest.mark.asyncio 
    async def test_process_ocr_low_quality_has_quality_metrics(self, processor_with_low_quality_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images with poor quality, low resolution, or distorted text
        WHEN _process_ocr processes challenging images
        THEN expect OCR results with basic structure for quality assessment
        """
        result = await processor_with_low_quality_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_key, page_result in result.items():
            for image_result in page_result:
                # Check that we have confidence score for quality assessment
                assert 'confidence' in image_result, \
                    f"'confidence' not found in image_result keys: {list(image_result.keys())}"
                # Check that we have engine information for quality assessment  
                assert 'engine_used' in image_result, \
                    f"'engine_used' not found in image_result keys: {list(image_result.keys())}"


class TestOCRMultilingualHandling(OCRTestBase):
    """Test OCR multilingual text processing capabilities."""

    @pytest.mark.asyncio
    async def test_process_ocr_multilingual_text_contains_unicode(self, processor_with_multilingual_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images containing text in multiple languages
        WHEN _process_ocr processes multilingual content
        THEN expect text extracted contains Unicode characters
        """
        result = await processor_with_multilingual_ocr._process_ocr(sample_decomposed_content_with_images)
        
        found_unicode = False
        for page_key, page_result in result.items():
            for image_result in page_result:
                # Check if text contains Unicode characters (non-ASCII)
                if any(ord(char) > 127 for char in image_result['text']):
                    found_unicode = True
                    break
        assert found_unicode, "No Unicode characters found in multilingual text"

    @pytest.mark.asyncio
    async def test_process_ocr_multilingual_text_not_empty(self, processor_with_multilingual_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images containing text in multiple languages
        WHEN _process_ocr processes multilingual content
        THEN expect text field to not be empty
        """
        result = await processor_with_multilingual_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_key, page_result in result.items():
            for image_result in page_result:
                text = image_result['text']
                assert len(text) > 0, f"Expected non-empty text for multilingual content, got: '{text}'"

    @pytest.mark.asyncio
    async def test_process_ocr_multilingual_text_contains_unicode(self, processor_with_multilingual_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images containing text in multiple languages
        WHEN _process_ocr processes multilingual content
        THEN expect text to contain Unicode characters indicating multilingual content
        """
        result = await processor_with_multilingual_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_key, page_result in result.items():
            for image_result in page_result:
                text = image_result['text']
                assert any(ord(char) > 127 for char in text), \
                    f"Expected Unicode characters in multilingual text: '{text}'"

    @pytest.mark.asyncio
    async def test_process_ocr_multilingual_words_key_present(self, processor_with_multilingual_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images containing text in multiple languages
        WHEN _process_ocr processes multilingual content
        THEN expect words key to be present in image results
        """
        result = await processor_with_multilingual_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            for image_result in page_result:
                assert 'word_boxes' in image_result, \
                    f"'words' not found in image_result keys: {list(image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multilingual_word_language_key_present(self, processor_with_multilingual_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images containing text in multiple languages
        WHEN _process_ocr processes multilingual content
        THEN expect language key to be present in word results
        """
        result = await processor_with_multilingual_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            for image_result in page_result:
                for word in image_result['word_boxes']:
                    assert 'language' in word, f"'language' not found in word keys: {list(word.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multilingual_word_language_is_string(self, processor_with_multilingual_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images containing text in multiple languages
        WHEN _process_ocr processes multilingual content
        THEN expect word language to be string
        """
        result = await processor_with_multilingual_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            for image_result in page_result:
                for word in image_result['word_boxes']:
                    assert isinstance(word['language'], str), f"Expected str for word language, got {type(word['language'])}: {word['language']}"

    @pytest.mark.asyncio
    async def test_process_ocr_multilingual_word_language_valid_length(self, processor_with_multilingual_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images containing text in multiple languages
        WHEN _process_ocr processes multilingual content
        THEN expect word language codes to have valid length
        """
        result = await processor_with_multilingual_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            for image_result in page_result:
                for word in image_result['word_boxes']:
                    assert len(word['language']) >= OCRTestConstants.EXPECTED_MINIMUM_LANGUAGE_CODE_LENGTH, \
                        f"Expected language length >= {OCRTestConstants.EXPECTED_MINIMUM_LANGUAGE_CODE_LENGTH}, got {len(word['language'])}: {word['language']}"

    @pytest.mark.asyncio
    async def test_process_ocr_positioning_page_result_is_dict(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images with text requiring precise positioning
        WHEN _process_ocr extracts word boxes
        THEN expect page result to be dictionary
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            assert isinstance(page_result, list), \
                f"Expected page_result to be dict, got {type(page_result)}: {page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_positioning_images_key_present(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images with text requiring precise positioning
        WHEN _process_ocr extracts word boxes
        THEN expect images key to be present
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            assert len(page_result) > 0, \
                f"Expected non-empty list of image results, got: {page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_positioning_words_key_present(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images with text requiring precise positioning
        WHEN _process_ocr extracts word boxes
        THEN expect words key to be present in image results
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            for image_result in page_result:
                assert 'word_boxes' in image_result, \
                f"'word_boxes' not found in image_result keys: {list(image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_positioning_word_structure_valid(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images with text requiring precise positioning
        WHEN _process_ocr extracts word boxes
        THEN expect word structure to be valid
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            for image_result in page_result:
                for word in image_result['word_boxes']:
                    self.assert_word_structure(word)

    @pytest.mark.asyncio
    async def test_process_ocr_positioning_bbox_coordinates_numeric(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images with text requiring precise positioning
        WHEN _process_ocr extracts word boxes
        THEN expect bbox coordinates to be numeric
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            for image_result in page_result:
                for word in image_result['word_boxes']:
                    bbox = word['bbox']
                    assert all(isinstance(coord, (int, float)) for coord in bbox), \
                        f"All bbox coordinates must be int or float: {bbox}"

    @pytest.mark.asyncio
    async def test_process_ocr_positioning_bbox_x_coordinates_logical(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images with text requiring precise positioning
        WHEN _process_ocr extracts word boxes
        THEN expect bbox x coordinates to be in logical order (x1 < x2)
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            for image_result in page_result:
                for word in image_result['word_boxes']:
                    bbox = word['bbox']
                    x1, y1, x2, y2 = bbox
                    assert x1 < x2, f"Invalid bbox x coordinates: {bbox}"

    @pytest.mark.asyncio
    async def test_process_ocr_positioning_bbox_y_coordinates_logical(self, processor_with_mock_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images with text requiring precise positioning
        WHEN _process_ocr extracts word boxes
        THEN expect bbox y coordinates to be in logical order (y1 < y2)
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            for image_result in page_result:
                for word in image_result['word_boxes']:
                    bbox = word['bbox']
                    x1, y1, x2, y2 = bbox
                    assert y1 < y2, f"Invalid bbox y coordinates: {bbox}"

    @pytest.mark.asyncio
    async def test_process_ocr_word_level_positioning_spatial_relationships_preserved(self, processor_with_positioning_ocr, sample_decomposed_content_with_images):
        """
        GIVEN images with text requiring precise positioning
        WHEN _process_ocr extracts word boxes
        THEN expect spatial relationships to be preserved (words ordered left-to-right)
        """
        result = await processor_with_positioning_ocr._process_ocr(sample_decomposed_content_with_images)
        
        found_positioning = False
        for page_key, page_result in result.items():
            for image_result in page_result:
                words = image_result['word_boxes']
                
                for i, word in enumerate(words):
                    bbox = word['bbox']
                    x1, y1, x2, y2 = bbox
                    
                    # Verify spatial relationships (words should be ordered left-to-right)
                    if i > 0:  # Skip first word
                        prev_word = words[i-1]
                        prev_x2 = prev_word['bbox'][2]
                        assert x1 >= prev_x2 - OCRTestConstants.EXPECTED_SPATIAL_OVERLAP_TOLERANCE, "Words should maintain spatial order"
                    
                    found_positioning = True

        assert found_positioning, "Should find word-level positioning data"

    @pytest.mark.asyncio
    async def test_process_ocr_confidence_scoring_page_result_is_dict(self, processor_with_varying_confidence_ocr, sample_decomposed_content_with_images):
        """
        GIVEN OCR processing of various image qualities
        WHEN _process_ocr generates confidence scores
        THEN expect page result to be dictionary
        """
        result = await processor_with_varying_confidence_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            assert isinstance(page_result, list), f"Expected page_result to be dict, got {type(page_result)}: {page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_confidence_scoring_images_key_present(self, processor_with_varying_confidence_ocr, sample_decomposed_content_with_images):
        """
        GIVEN OCR processing of various image qualities
        WHEN _process_ocr generates confidence scores
        THEN expect images key to be present in page results
        """
        result = await processor_with_varying_confidence_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            assert len(page_result) > 0, f"Expected non-empty list of image results, got: {page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_confidence_scoring_confidence_key_present(self, processor_with_varying_confidence_ocr, sample_decomposed_content_with_images):
        """
        GIVEN OCR processing of various image qualities
        WHEN _process_ocr generates confidence scores
        THEN expect confidence key to be present in image results
        """
        result = await processor_with_varying_confidence_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            for image_result in page_result:
                assert 'confidence' in image_result, f"'confidence' not found in image_result keys: {list(image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_confidence_scoring_range_valid(self, processor_with_varying_confidence_ocr, sample_decomposed_content_with_images):
        """
        GIVEN OCR processing of various image qualities
        WHEN _process_ocr generates confidence scores
        THEN expect confidence scores to be within valid range
        """
        result = await processor_with_varying_confidence_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            for image_result in page_result:
                confidence = image_result['confidence']
                self.assert_confidence_range(confidence)


    @pytest.mark.asyncio
    async def test_process_ocr_confidence_scoring_has_confidence_scores(self, processor_with_varying_confidence_ocr, sample_decomposed_content_with_images):
        """
        GIVEN OCR processing of various image qualities
        WHEN _process_ocr generates confidence scores
        THEN expect to have confidence scores for processed images
        """
        result = await processor_with_varying_confidence_ocr._process_ocr(sample_decomposed_content_with_images)

        # Verify confidence scoring
        confidences = []
        for page_key, page_result in result.items():
            for image_result in page_result:
                confidence = image_result['confidence']
                confidences.append(confidence)

        # Should have confidence scores for processed images
        assert len(confidences) > OCRTestConstants.EXPECTED_MINIMUM_NON_EMPTY_RESULT, f"No confidence scores found: {confidences}"

    @pytest.mark.asyncio
    async def test_process_ocr_confidence_scoring_multiple_confidence_scores(self, processor_with_varying_confidence_ocr, sample_decomposed_content_with_images):
        """
        GIVEN OCR processing of various image qualities
        WHEN _process_ocr generates confidence scores
        THEN expect multiple confidence scores from different quality processing
        """
        result = await processor_with_varying_confidence_ocr._process_ocr(sample_decomposed_content_with_images)

        # Verify confidence scoring
        confidences = []
        for page_key, page_result in result.items():
            for image_result in page_result:
                confidence = image_result['confidence']
                confidences.append(confidence)
        
        # Verify range of confidences (should vary based on quality)
        assert len(confidences) > OCRTestConstants.EXPECTED_MINIMUM_LANGUAGES_COUNT, \
            f"Expected multiple confidence scores, got {len(confidences)}: {confidences}"

    @pytest.mark.asyncio
    async def test_process_ocr_confidence_scoring_accuracy_varying_confidence_scores(self, processor_with_varying_confidence_ocr, sample_decomposed_content_with_images):
        """
        GIVEN OCR processing of various image qualities
        WHEN _process_ocr generates confidence scores
        THEN expect varying confidence scores based on quality
        """
        result = await processor_with_varying_confidence_ocr._process_ocr(sample_decomposed_content_with_images)

        # Verify confidence scoring
        confidences = []
        for page_key, page_result in result.items():
            for image_result in page_result:
                confidence = image_result['confidence']
                confidences.append(confidence)

        # Since we have two pages with images, we should get varying confidences
        assert max(confidences) > min(confidences), f"Should have varying confidence scores, got: {confidences}"

    @pytest.mark.asyncio
    async def test_process_ocr_engine_comparison_page_result_is_dict(self, processor_with_multi_engine_comparison_ocr, sample_decomposed_content_with_images):
        """
        GIVEN multiple OCR engines with different strengths
        WHEN _process_ocr compares engine results
        THEN expect page result to be dictionary
        """
        result = await processor_with_multi_engine_comparison_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            assert isinstance(page_result, list), f"Expected page_result to be dict, got {type(page_result)}: {page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_engine_comparison_images_key_present(self, processor_with_multi_engine_comparison_ocr, sample_decomposed_content_with_images):
        """
        GIVEN multiple OCR engines with different strengths
        WHEN _process_ocr compares engine results
        THEN expect images key to be present in page results
        """
        result = await processor_with_multi_engine_comparison_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            assert len(page_result) > 0, f"Expected non-empty list of image results, got: {page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_engine_comparison_engine_key_present(self, processor_with_multi_engine_comparison_ocr, sample_decomposed_content_with_images):
        """
        GIVEN multiple OCR engines with different strengths
        WHEN _process_ocr compares engine results
        THEN expect engine key to be present in image results
        """
        result = await processor_with_multi_engine_comparison_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            for image_result in page_result:
                assert 'engine_used' in image_result, \
                    f"'engine_used' not found in image_result keys: {list(image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_engine_comparison_engine_is_string(self, processor_with_multi_engine_comparison_ocr, sample_decomposed_content_with_images):
        """
        GIVEN multiple OCR engines with different strengths
        WHEN _process_ocr compares engine results
        THEN expect engine to be string
        """
        result = await processor_with_multi_engine_comparison_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            for image_result in page_result:
                assert isinstance(image_result['engine_used'], str), \
                    f"Expected engine to be str, got {type(image_result['engine_used'])}: {image_result['engine_used']}"

    @pytest.mark.asyncio
    async def test_process_ocr_engine_comparison_engine_not_empty(self, processor_with_multi_engine_comparison_ocr, sample_decomposed_content_with_images):
        """
        GIVEN multiple OCR engines with different strengths
        WHEN _process_ocr compares engine results
        THEN expect engine name to not be empty
        """
        result = await processor_with_multi_engine_comparison_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            for image_result in page_result:
                len_engine_used = len(image_result['engine_used'])
                assert len_engine_used > OCRTestConstants.EXPECTED_MINIMUM_NON_EMPTY_RESULT, \
                    f"Engine name should not be empty: '{image_result['engine_used']}'"

    @pytest.mark.asyncio
    async def test_process_ocr_engine_comparison_confidence_key_present(self, processor_with_multi_engine_comparison_ocr, sample_decomposed_content_with_images):
        """
        GIVEN multiple OCR engines with different strengths
        WHEN _process_ocr compares engine results
        THEN expect confidence key to be present in image results
        """
        result = await processor_with_multi_engine_comparison_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            for image_result in page_result:
                assert 'confidence' in image_result, \
                    f"'confidence' not found in image_result keys: {list(image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_no_images_returns_dict(self, processor_with_mock_ocr, sample_decomposed_content_no_images):
        """
        GIVEN decomposed content with no embedded images
        WHEN _process_ocr processes content
        THEN expect result to be dictionary
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_no_images)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_process_ocr_no_images_page_result_is_dict(self, processor_with_mock_ocr, sample_decomposed_content_no_images):
        """
        GIVEN decomposed content with no embedded images
        WHEN _process_ocr processes content
        THEN expect page result to be dictionary
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_no_images)
        
        for page_result in result.values():
            assert isinstance(page_result, list), f"Expected page_result to be dict, got {type(page_result)}: {page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_no_images_has_images_key(self, processor_with_mock_ocr, sample_decomposed_content_no_images):
        """
        GIVEN decomposed content with no embedded images
        WHEN _process_ocr processes content
        THEN expect page result to be empty list (no images to process)
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_no_images)
        
        for page_result in result.values():
            # When there are no images, the result should be an empty list
            assert isinstance(page_result, list), f"Expected list for page_result, got {type(page_result)}: {page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_no_images_empty_images_list(self, processor_with_mock_ocr, sample_decomposed_content_no_images):
        """
        GIVEN decomposed content with no embedded images
        WHEN _process_ocr processes content
        THEN expect empty images list
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_no_images)
        
        for page_result in result.values():
            assert len(page_result) == OCRTestConstants.EXPECTED_EMPTY_LIST_LENGTH, f"Expected empty images list, got {len(page_result)} images: {page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_no_images_no_ocr_results(self, processor_with_mock_ocr, sample_decomposed_content_no_images):
        """
        GIVEN decomposed content with no embedded images
        WHEN _process_ocr processes content
        THEN expect no OCR results or empty OCR results
        """
        result = await processor_with_mock_ocr._process_ocr(sample_decomposed_content_no_images)
        
        for page_result in result.values():
            assert 'ocr_results' not in page_result or len(page_result['ocr_results']) == OCRTestConstants.EXPECTED_EMPTY_LIST_LENGTH, f"Expected no ocr_results or empty ocr_results, got: {page_result.get('ocr_results', 'not present')}"

    @pytest.mark.asyncio
    async def test_process_ocr_no_images_engine_not_called(self, 
        processor_with_mock_ocr, sample_decomposed_content_no_images):
        """
        GIVEN decomposed content with no embedded images
        WHEN _process_ocr processes content
        THEN expect OCR engine to not be called
        """
        await processor_with_mock_ocr._process_ocr(sample_decomposed_content_no_images)
        
        assert not processor_with_mock_ocr.ocr_engine.process_image_multi_engine.called, \
            f"OCR engine should not be called when no images present, but was called: {processor_with_mock_ocr.ocr_engine.process_image_multi_engine.call_count} times"

    @pytest.mark.asyncio
    async def test_process_ocr_missing_engine_dependencies(self, processor_with_missing_dependencies_ocr, sample_decomposed_content_with_images):
        """
        GIVEN OCR engine dependencies not available
        WHEN _process_ocr attempts to use missing engines
        THEN expect ImportError to be raised with dependency details
        """
        # Execute and expect ImportError
        with pytest.raises(ImportError, match="OCR engine dependencies|dependencies not found|tesseract|easyocr"):
            await processor_with_missing_dependencies_ocr._process_ocr(sample_decomposed_content_with_images)

    @pytest.mark.asyncio
    async def test_process_ocr_corrupted_image_handling(self, processor_with_corrupted_image_ocr, corrupted_image_content):
        """
        GIVEN decomposed content with corrupted or unsupported image formats
        WHEN _process_ocr processes problematic images
        THEN expect failure result to be present
        """
        await processor_with_corrupted_image_ocr._process_ocr(corrupted_image_content)

    @pytest.mark.asyncio
    async def test_process_ocr_timeout_handling(self, processor_with_timeout_ocr, sample_decomposed_content_with_images):
        """
        GIVEN OCR processing that exceeds configured timeout limits
        WHEN _process_ocr runs for extended time
        THEN expect TimeoutError to be raised
        """
        # Execute with timeout
        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            await asyncio.wait_for(
                processor_with_timeout_ocr._process_ocr(sample_decomposed_content_with_images),
                timeout=1.0  # 1 second timeout
            )
    @pytest.mark.asyncio
    async def test_process_ocr_image_format_compatibility_returns_dict(self, 
        processor_with_format_specific_ocr, multi_format_image_content):
        """
        GIVEN images in various formats (JPEG, PNG, TIFF, etc.)
        WHEN _process_ocr processes different formats
        THEN expect page result to be dictionary
        """
        result = await processor_with_format_specific_ocr._process_ocr(multi_format_image_content)

        for page_key, page_result in result.items():
            assert isinstance(page_result, dict), f"Expected page_result to be dict, got {type(page_result)}: {page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_image_format_compatibility_has_images_key(self, 
        processor_with_format_specific_ocr, multi_format_image_content):
        """
        GIVEN images in various formats (JPEG, PNG, TIFF, etc.)
        WHEN _process_ocr processes different formats
        THEN expect images key to be present in page result
        """
        result = await processor_with_format_specific_ocr._process_ocr(multi_format_image_content)

        for page_key, page_result in result.items():
            assert len(page_result) > 0, f"Expected non-empty list of image results, got: {page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_image_format_compatibility_image_structure_valid(self, 
        processor_with_format_specific_ocr, multi_format_image_content):
        """
        GIVEN images in various formats (JPEG, PNG, TIFF, etc.)
        WHEN _process_ocr processes different formats
        THEN expect image result structure to be valid
        """
        result = await processor_with_format_specific_ocr._process_ocr(multi_format_image_content)

        for page_key, page_result in result.items():
            for image_result in page_result:
                self.assert_image_result_structure(image_result)

    @pytest.mark.asyncio
    async def test_process_ocr_image_format_compatibility_processes_multiple_formats(self, 
        processor_with_format_specific_ocr, multi_format_image_content):
        """Test _process_ocr processes multiple image formats.
        
        GIVEN images in various formats (JPEG, PNG, TIFF, etc.)
        WHEN _process_ocr processes different formats
        THEN expect multiple formats to be processed
        """
        result = await processor_with_format_specific_ocr._process_ocr(multi_format_image_content)

        formats_processed = set()
        for page_key, page_result in result.items():
            for image_result in page_result:
                formats_processed.add(image_result.get('format_detected', 'UNKNOWN'))
        
        assert len(formats_processed) >= OCRTestConstants.EXPECTED_MINIMUM_ENGINES_COUNT, f"Expected at least {OCRTestConstants.EXPECTED_MINIMUM_ENGINES_COUNT} formats processed, got {len(formats_processed)}: {formats_processed}"

    @pytest.mark.asyncio
    async def test_process_ocr_selection_reason_is_string(self, processor_with_multi_engine_comparison_ocr, sample_decomposed_content_with_images):
        """
        GIVEN multiple OCR engines with different strengths
        WHEN _process_ocr compares engine results
        THEN expect selection reason to be string
        """
        result = await processor_with_multi_engine_comparison_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            for image_result in page_result:
                assert isinstance(image_result['selected_reason'], str), f"Expected selected_reason to be str, got {type(image_result['selected_reason'])}: {image_result['selected_reason']}"

    @pytest.mark.asyncio
    async def test_process_ocr_selection_reason_page_result_is_dict(self, processor_with_multi_engine_comparison_ocr, sample_decomposed_content_with_images):
        """
        GIVEN multiple OCR engines with different strengths
        WHEN _process_ocr compares engine results
        THEN expect page result to be dictionary
        """
        result = await processor_with_multi_engine_comparison_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            assert isinstance(page_result, list), f"Expected page_result to be dict, got {type(page_result)}: {page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_selection_reason_images_key_present(self, processor_with_multi_engine_comparison_ocr, sample_decomposed_content_with_images):
        """
        GIVEN multiple OCR engines with different strengths
        WHEN _process_ocr compares engine results
        THEN expect images key to be present in page result
        """
        result = await processor_with_multi_engine_comparison_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_result in result.values():
            assert len(page_result) > 0, f"Expected non-empty list of image results, got: {page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_result_aggregation_page_result_is_dict(self, processor_with_detailed_metrics_ocr, sample_decomposed_content_with_images):
        """
        GIVEN OCR results from multiple engines and images
        WHEN _process_ocr aggregates results
        THEN expect page result to be dictionary
        """
        result = await processor_with_detailed_metrics_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_key, page_result in result.items():
            assert isinstance(page_result, dict), f"Expected page_result to be dict, got {type(page_result)}: {page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_result_aggregation_images_key_present(self, processor_with_detailed_metrics_ocr, sample_decomposed_content_with_images):
        """
        GIVEN OCR results from multiple engines and images
        WHEN _process_ocr aggregates results
        THEN expect images key to be present in page result
        """
        result = await processor_with_detailed_metrics_ocr._process_ocr(sample_decomposed_content_with_images)
        
        for page_key, page_result in result.items():
            assert len(page_result) > 0, f"Expected non-empty list of image results, got: {page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_result_aggregation_quality_score_valid_range(self, processor_with_detailed_metrics_ocr, sample_decomposed_content_with_images):
        """
        GIVEN OCR results from multiple engines and images
        WHEN _process_ocr aggregates results
        THEN expect quality_score to be within valid range
        """
        result = await processor_with_detailed_metrics_ocr._process_ocr(sample_decomposed_content_with_images)

        for page_key, page_result in result.items():
            for image_result in page_result:
                quality_score = image_result.get('quality_score') or image_result['aggregated_metrics']['quality_score']
                self.assert_confidence_range(quality_score)

    @pytest.mark.asyncio
    async def test_process_ocr_result_aggregation_non_empty_result(self, processor_with_detailed_metrics_ocr, sample_decomposed_content_with_images):
        """
        GIVEN OCR results from multiple engines and images
        WHEN _process_ocr aggregates results
        THEN expect non-empty result
        """
        result = await processor_with_detailed_metrics_ocr._process_ocr(sample_decomposed_content_with_images)
        
        assert len(result) > OCRTestConstants.EXPECTED_MINIMUM_NON_EMPTY_RESULT, f"Expected non-empty result, got length {len(result)}: {result}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
