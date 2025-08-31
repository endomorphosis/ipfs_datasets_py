
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py
# Auto-generated on 2025-07-07 02:28:56"

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

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor_stubs.md")

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

# Import shared fixtures and utilities from conftest.py
from .process_ocr.conftest import OCRTestConstants, OCRTestBase


class TestOCRBasicFunctionality(OCRTestBase):
    """Test basic OCR functionality and data structure validation."""

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_returns_dict(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect returned result is a dictionary
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            assert isinstance(result, dict), f"Expected dict, got {type(result)}: {result}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_has_minimum_length(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect returned result has minimum expected length
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            assert len(result) >= OCRTestConstants.EXPECTED_MINIMUM_RESULT_LENGTH, f"Expected result length >= {OCRTestConstants.EXPECTED_MINIMUM_RESULT_LENGTH}, got {len(result)}: {result}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_has_page_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect result contains page_1 key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            assert 'page_1' in result, f"'page_1' not found in result keys: {list(result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_calls_ocr_engine(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect OCR engine process_image_multi_engine method is called
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            await processor._process_ocr(sample_decomposed_content_with_images)
            
            assert mock_ocr_instance.process_image_multi_engine.called, f"OCR engine process_image_multi_engine was not called: {mock_ocr_instance.process_image_multi_engine.called}"


class TestOCRDataStructure(OCRTestBase):
    """Test OCR result data structure validation."""

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_page_result_is_dict(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first page result is a dictionary
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            assert isinstance(first_page_result, dict), f"Expected dict for page_result, got {type(first_page_result)}: {first_page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_page_has_images_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first page result contains 'images' key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            assert 'images' in first_page_result, f"'images' not found in page_result keys: {list(first_page_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_image_has_text_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first image result contains 'text' key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            first_image_result = first_page_result['images'][0]
            assert 'text' in first_image_result, f"'text' not found in image_result keys: {list(first_image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_image_has_confidence_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first image result contains 'confidence' key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            first_image_result = first_page_result['images'][0]
            assert 'confidence' in first_image_result, f"'confidence' not found in image_result keys: {list(first_image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_image_has_engine_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first image result contains 'engine' key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            first_image_result = first_page_result['images'][0]
            assert 'engine' in first_image_result, f"'engine' not found in image_result keys: {list(first_image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_image_has_words_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first image result contains 'words' key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            first_image_result = first_page_result['images'][0]
            assert 'words' in first_image_result, f"'words' not found in image_result keys: {list(first_image_result.keys())}"


class TestOCRWordStructure(OCRTestBase):
    """Test word-level OCR result structure validation."""

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_word_has_text_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first word contains 'text' key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            first_image_result = first_page_result['images'][0]
            first_word = first_image_result['words'][0]
            assert 'text' in first_word, f"'text' not found in word keys: {list(first_word.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_word_has_confidence_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first word contains 'confidence' key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            first_image_result = first_page_result['images'][0]
            first_word = first_image_result['words'][0]
            assert 'confidence' in first_word, f"'confidence' not found in word keys: {list(first_word.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_word_has_bbox_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first word contains 'bbox' key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            first_image_result = first_page_result['images'][0]
            first_word = first_image_result['words'][0]
            assert 'bbox' in first_word, f"'bbox' not found in word keys: {list(first_word.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_word_bbox_has_correct_length(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first word bbox has 4 coordinates
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            first_image_result = first_page_result['images'][0]
            first_word = first_image_result['words'][0]
            assert len(first_word['bbox']) == OCRTestConstants.EXPECTED_BBOX_COORDINATE_COUNT, f"Expected bbox length {OCRTestConstants.EXPECTED_BBOX_COORDINATE_COUNT}, got {len(first_word['bbox'])}: {first_word['bbox']}"


class TestOCRQualityHandling(OCRTestBase):

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_returns_dict(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect returned result is a dictionary
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            assert isinstance(result, dict), f"Expected dict, got {type(result)}: {result}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_has_minimum_length(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect returned result has minimum expected length
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            assert len(result) >= OCRTestConstants.EXPECTED_MINIMUM_RESULT_LENGTH, f"Expected result length >= {OCRTestConstants.EXPECTED_MINIMUM_RESULT_LENGTH}, got {len(result)}: {result}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_has_page_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect result contains page_1 key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            assert 'page_1' in result, f"'page_1' not found in result keys: {list(result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_page_result_is_dict(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first page result is a dictionary
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            assert isinstance(first_page_result, dict), f"Expected dict for page_result, got {type(first_page_result)}: {first_page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_page_has_images_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first page result contains 'images' key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            assert 'images' in first_page_result, f"'images' not found in page_result keys: {list(first_page_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_image_has_text_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first image result contains 'text' key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            first_image_result = first_page_result['images'][0]
            assert 'text' in first_image_result, f"'text' not found in image_result keys: {list(first_image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_image_has_confidence_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first image result contains 'confidence' key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            first_image_result = first_page_result['images'][0]
            assert 'confidence' in first_image_result, f"'confidence' not found in image_result keys: {list(first_image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_image_has_engine_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first image result contains 'engine' key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            first_image_result = first_page_result['images'][0]
            assert 'engine' in first_image_result, f"'engine' not found in image_result keys: {list(first_image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_image_has_words_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first image result contains 'words' key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            first_image_result = first_page_result['images'][0]
            assert 'words' in first_image_result, f"'words' not found in image_result keys: {list(first_image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_word_has_text_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first word contains 'text' key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            first_image_result = first_page_result['images'][0]
            first_word = first_image_result['words'][0]
            assert 'text' in first_word, f"'text' not found in word keys: {list(first_word.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_word_has_confidence_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first word contains 'confidence' key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            first_image_result = first_page_result['images'][0]
            first_word = first_image_result['words'][0]
            assert 'confidence' in first_word, f"'confidence' not found in word keys: {list(first_word.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_word_has_bbox_key(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first word contains 'bbox' key
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            first_image_result = first_page_result['images'][0]
            first_word = first_image_result['words'][0]
            assert 'bbox' in first_word, f"'bbox' not found in word keys: {list(first_word.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_first_word_bbox_has_correct_length(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect first word bbox has 4 coordinates
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            first_page_result = list(result.values())[0]
            first_image_result = first_page_result['images'][0]
            first_word = first_image_result['words'][0]
            assert len(first_word['bbox']) == OCRTestConstants.EXPECTED_BBOX_COORDINATE_COUNT, f"Expected bbox length {OCRTestConstants.EXPECTED_BBOX_COORDINATE_COUNT}, got {len(first_word['bbox'])}: {first_word['bbox']}"

    @pytest.mark.asyncio
    async def test_process_ocr_multi_engine_calls_ocr_engine(self, 
        processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class
        ):
        """
        GIVEN decomposed PDF content with embedded images containing text
        WHEN _process_ocr processes images with multiple OCR engines
        THEN expect OCR engine process_image_multi_engine method is called
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Setup multi-engine responses
        def mock_process_engines(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR extracted text',
                    'confidence': 0.90,
                    'words': [{'text': 'EasyOCR', 'confidence': 0.90, 'bbox': [10, 10, 70, 25]}],
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = mock_process_engines
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            await processor._process_ocr(sample_decomposed_content_with_images)
            
            assert mock_ocr_instance.process_image_multi_engine.called, f"OCR engine process_image_multi_engine was not called: {mock_ocr_instance.process_image_multi_engine.called}"

    @pytest.mark.asyncio
    async def test_process_ocr_high_quality_image_confidence_above_threshold(self, processor, sample_decomposed_content_with_images, 
                                                      mock_multi_engine_ocr_class, high_quality_ocr_result):
        """
        GIVEN images with clear, high-resolution text
        WHEN _process_ocr extracts text
        THEN expect high confidence scores (>0.9)
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def high_quality_ocr(image_data):
            return self.create_mock_ocr_future({'best_result': high_quality_ocr_result})
        
        mock_ocr_instance.process_image_multi_engine = high_quality_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            min_confidence = OCRTestConstants.EXPECTED_HIGH_CONFIDENCE_THRESHOLD
            
        # Verify high confidence scores
        found_high_confidence = False
        for page_key, page_result in result.items():
            assert isinstance(page_result, dict), f"Expected dict for page_result, got {type(page_result)}: {page_result}"
            assert 'images' in page_result, f"'images' not found in page_result keys: {list(page_result.keys())}"
            for image_result in page_result['images']:
                self.assert_confidence_range(image_result['confidence'], min_confidence)
                found_high_confidence = True
        
        assert found_high_confidence, "No high confidence results found"

    @pytest.mark.asyncio
    async def test_process_ocr_high_quality_image_word_confidence_above_threshold(self, processor, sample_decomposed_content_with_images, 
                                                  mock_multi_engine_ocr_class, high_quality_ocr_result):
        """
        GIVEN images with clear, high-resolution text
        WHEN _process_ocr extracts text
        THEN expect word-level high confidence scores (>0.9)
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def high_quality_ocr(image_data):
            return self.create_mock_ocr_future({'best_result': high_quality_ocr_result})
        
        mock_ocr_instance.process_image_multi_engine = high_quality_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            min_confidence = OCRTestConstants.EXPECTED_HIGH_CONFIDENCE_THRESHOLD            # Verify word-level confidence
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    for word in image_result['words']:
                        self.assert_confidence_range(word['confidence'], min_confidence)

    @pytest.mark.asyncio
    async def test_process_ocr_high_quality_image_proper_word_positioning(self, processor, sample_decomposed_content_with_images, 
                                                      mock_multi_engine_ocr_class, high_quality_ocr_result):
        """
        GIVEN images with clear, high-resolution text
        WHEN _process_ocr extracts text
        THEN expect proper word-level positioning with valid structure
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def high_quality_ocr(image_data):
            return self.create_mock_ocr_future({'best_result': high_quality_ocr_result})
        
        mock_ocr_instance.process_image_multi_engine = high_quality_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            # Verify proper positioning
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    for word in image_result['words']:
                        # Verify proper positioning
                        self.assert_word_structure(word)

    @pytest.mark.asyncio
    async def test_process_ocr_high_quality_image_bbox_coordinates_valid(self, processor, sample_decomposed_content_with_images, 
                                                      mock_multi_engine_ocr_class, high_quality_ocr_result):
        """
        GIVEN images with clear, high-resolution text
        WHEN _process_ocr extracts text
        THEN expect bbox coordinates to be valid numeric values
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def high_quality_ocr(image_data):
            return self.create_mock_ocr_future({'best_result': high_quality_ocr_result})
        
        mock_ocr_instance.process_image_multi_engine = high_quality_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    for word in image_result['words']:
                        assert all(isinstance(coord, (int, float)) for coord in word['bbox']), \
                            f"Expected all bbox coords to be int/float, got: {word['bbox']}"

    @pytest.mark.asyncio
    async def test_process_ocr_low_quality_image_confidence_below_threshold(self, processor, sample_decomposed_content_with_images,
                                                         mock_multi_engine_ocr_class, low_quality_ocr_result):
        """
        GIVEN images with poor quality, low resolution, or distorted text
        WHEN _process_ocr processes challenging images
        THEN expect lower confidence scores reflecting quality
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def low_quality_ocr(image_data):
            return self.create_mock_ocr_future({'best_result': low_quality_ocr_result})
        
        mock_ocr_instance.process_image_multi_engine = low_quality_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            # Verify low confidence handling
            found_low_quality = False
            for page_key, page_result in result.items():
                assert isinstance(page_result, dict), f"Expected dict for page_result, got {type(page_result)}: {page_result}"
                assert 'images' in page_result, f"'images' not found in page_result keys: {list(page_result.keys())}"
                for image_result in page_result['images']:
                    assert 'confidence' in image_result, f"'confidence' not found in image_result keys: {list(image_result.keys())}"
                    assert image_result['confidence'] < OCRTestConstants.EXPECTED_LOW_CONFIDENCE_THRESHOLD, f"Expected confidence < {OCRTestConstants.EXPECTED_LOW_CONFIDENCE_THRESHOLD}, got {image_result['confidence']}"
                    found_low_quality = True
            
            assert found_low_quality or len(result) > OCRTestConstants.EXPECTED_MINIMUM_NON_EMPTY_RESULT, f"Should handle low quality images gracefully: found_low_quality={found_low_quality}, result_length={len(result)}"

    @pytest.mark.asyncio
    async def test_process_ocr_low_quality_image_partial_text_extraction(self, processor, sample_decomposed_content_with_images,
                                                         mock_multi_engine_ocr_class, low_quality_ocr_result):
        """
        GIVEN images with poor quality, low resolution, or distorted text
        WHEN _process_ocr processes challenging images
        THEN expect partial text extraction where possible
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def low_quality_ocr(image_data):
            return self.create_mock_ocr_future({'best_result': low_quality_ocr_result})
        
        mock_ocr_instance.process_image_multi_engine = low_quality_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    # Verify partial text extraction
                    assert 'text' in image_result, f"'text' not found in image_result keys: {list(image_result.keys())}"
                    assert len(image_result['text']) > OCRTestConstants.EXPECTED_MINIMUM_TEXT_LENGTH, f"Expected text length > {OCRTestConstants.EXPECTED_MINIMUM_TEXT_LENGTH}, got {len(image_result['text'])}: {image_result['text']}"

    @pytest.mark.asyncio
    async def test_process_ocr_low_quality_image_quality_metrics_present(self, processor, sample_decomposed_content_with_images,
                                                         mock_multi_engine_ocr_class, low_quality_ocr_result):
        """
        GIVEN images with poor quality, low resolution, or distorted text
        WHEN _process_ocr processes challenging images
        THEN expect quality metrics indicating processing challenges
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def low_quality_ocr(image_data):
            return self.create_mock_ocr_future({'best_result': low_quality_ocr_result})
        
        mock_ocr_instance.process_image_multi_engine = low_quality_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    # Verify quality metrics
                    assert 'quality_metrics' in image_result, f"'quality_metrics' not found in image_result keys: {list(image_result.keys())}"
                    metrics = image_result['quality_metrics']
                    assert isinstance(metrics, dict), f"Expected dict for metrics, got {type(metrics)}: {metrics}"

    @pytest.mark.asyncio
    async def test_process_ocr_multiple_languages_text_contains_unicode(self, processor, sample_decomposed_content_with_images,
                                                         mock_multi_engine_ocr_class, multilingual_ocr_result):
        """
        GIVEN images containing text in multiple languages
        WHEN _process_ocr processes multilingual content
        THEN expect text extracted contains Unicode characters
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def multilingual_ocr(image_data):
            return self.create_mock_ocr_future({'best_result': multilingual_ocr_result})
        
        mock_ocr_instance.process_image_multi_engine = multilingual_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            # Should handle multilingual content without errors
            assert len(result) > OCRTestConstants.EXPECTED_MINIMUM_NON_EMPTY_RESULT, f"Expected result length > {OCRTestConstants.EXPECTED_MINIMUM_NON_EMPTY_RESULT}, got {len(result)}: {result}"

    @pytest.mark.asyncio
    async def test_process_ocr_multiple_languages_detection_present(self, processor, sample_decomposed_content_with_images,
                                                         mock_multi_engine_ocr_class, multilingual_ocr_result):
        """
        GIVEN images containing text in multiple languages
        WHEN _process_ocr processes multilingual content
        THEN expect language detection data present
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def multilingual_ocr(image_data):
            return self.create_mock_ocr_future({'best_result': multilingual_ocr_result})
        
        mock_ocr_instance.process_image_multi_engine = multilingual_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    # Verify language detection
                    assert 'languages_detected' in image_result, f"'languages_detected' not found in image_result keys: {list(image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multiple_languages_detection_is_list(self, processor, sample_decomposed_content_with_images,
                                                         mock_multi_engine_ocr_class, multilingual_ocr_result):
        """
        GIVEN images containing text in multiple languages
        WHEN _process_ocr processes multilingual content
        THEN expect languages_detected to be a list
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def multilingual_ocr(image_data):
            return self.create_mock_ocr_future({'best_result': multilingual_ocr_result})
        
        mock_ocr_instance.process_image_multi_engine = multilingual_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    assert isinstance(image_result['languages_detected'], list), f"Expected list for languages_detected, got {type(image_result['languages_detected'])}: {image_result['languages_detected']}"

    @pytest.mark.asyncio
    async def test_process_ocr_multiple_languages_detection_has_minimum_count(self, processor, sample_decomposed_content_with_images,
                                                         mock_multi_engine_ocr_class, multilingual_ocr_result):
        """
        GIVEN images containing text in multiple languages
        WHEN _process_ocr processes multilingual content
        THEN expect multiple languages detected
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def multilingual_ocr(image_data):
            return self.create_mock_ocr_future({'best_result': multilingual_ocr_result})
        
        mock_ocr_instance.process_image_multi_engine = multilingual_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    assert len(image_result['languages_detected']) > self.EXPECTED_MINIMUM_LANGUAGES_COUNT, f"Expected > {self.EXPECTED_MINIMUM_LANGUAGES_COUNT} languages detected, got {len(image_result['languages_detected'])}: {image_result['languages_detected']}"

    @pytest.mark.asyncio
    async def test_process_ocr_multiple_languages_word_level_language_present(self, processor, sample_decomposed_content_with_images,
                                                         mock_multi_engine_ocr_class, multilingual_ocr_result):
        """
        GIVEN images containing text in multiple languages
        WHEN _process_ocr processes multilingual content
        THEN expect word-level language info present
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def multilingual_ocr(image_data):
            return self.create_mock_ocr_future({'best_result': multilingual_ocr_result})
        
        mock_ocr_instance.process_image_multi_engine = multilingual_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    # Verify word-level language info
                    assert 'words' in image_result, f"'words' not found in image_result keys: {list(image_result.keys())}"
                    for word in image_result['words']:
                        assert 'language' in word, f"'language' not found in word keys: {list(word.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_multiple_languages_word_language_is_string(self, processor, sample_decomposed_content_with_images,
                                                         mock_multi_engine_ocr_class, multilingual_ocr_result):
        """
        GIVEN images containing text in multiple languages
        WHEN _process_ocr processes multilingual content
        THEN expect word language to be string
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def multilingual_ocr(image_data):
            return self.create_mock_ocr_future({'best_result': multilingual_ocr_result})
        
        mock_ocr_instance.process_image_multi_engine = multilingual_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    for word in image_result['words']:
                        assert isinstance(word['language'], str), f"Expected str for word language, got {type(word['language'])}: {word['language']}"

    @pytest.mark.asyncio
    async def test_process_ocr_multiple_languages_word_language_valid_length(self, processor, sample_decomposed_content_with_images,
                                                         mock_multi_engine_ocr_class, multilingual_ocr_result):
        """
        GIVEN images containing text in multiple languages
        WHEN _process_ocr processes multilingual content
        THEN expect word language codes to have valid length
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def multilingual_ocr(image_data):
            return self.create_mock_ocr_future({'best_result': multilingual_ocr_result})
        
        mock_ocr_instance.process_image_multi_engine = multilingual_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    for word in image_result['words']:
                        assert len(word['language']) >= self.EXPECTED_MINIMUM_LANGUAGE_CODE_LENGTH, f"Expected language length >= {self.EXPECTED_MINIMUM_LANGUAGE_CODE_LENGTH}, got {len(word['language'])}: {word['language']}"

    @pytest.mark.asyncio
    async def test_process_ocr_word_level_positioning_accuracy_page_result_is_dict(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN images with text requiring precise positioning
        WHEN _process_ocr extracts word boxes
        THEN expect page result to be dictionary
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def precise_positioning_ocr(image_data):
            return self.create_mock_ocr_future({
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
        
        mock_ocr_instance.process_image_multi_engine = precise_positioning_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            # Verify precise positioning
            for page_key, page_result in result.items():
                assert isinstance(page_result, dict), f"Expected page_result to be dict, got {type(page_result)}: {page_result}"

    @pytest.mark.asyncio
    async def test_process_ocr_word_level_positioning_accuracy_images_key_present(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN images with text requiring precise positioning
        WHEN _process_ocr extracts word boxes
        THEN expect images key to be present
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def precise_positioning_ocr(image_data):
            return self.create_mock_ocr_future({
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
        
        mock_ocr_instance.process_image_multi_engine = precise_positioning_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            for page_key, page_result in result.items():
                assert 'images' in page_result, f"'images' not found in page_result keys: {list(page_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_word_level_positioning_accuracy_words_key_present(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN images with text requiring precise positioning
        WHEN _process_ocr extracts word boxes
        THEN expect words key to be present in image results
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def precise_positioning_ocr(image_data):
            return self.create_mock_ocr_future({
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
        
        mock_ocr_instance.process_image_multi_engine = precise_positioning_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    assert 'words' in image_result, f"'words' not found in image_result keys: {list(image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_word_level_positioning_accuracy_word_structure_valid(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN images with text requiring precise positioning
        WHEN _process_ocr extracts word boxes
        THEN expect word structure to be valid
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def precise_positioning_ocr(image_data):
            return self.create_mock_ocr_future({
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
        
        mock_ocr_instance.process_image_multi_engine = precise_positioning_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    words = image_result['words']
                    
                    for i, word in enumerate(words):
                        self.assert_word_structure(word)

    @pytest.mark.asyncio
    async def test_process_ocr_word_level_positioning_accuracy_bbox_coordinates_numeric(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN images with text requiring precise positioning
        WHEN _process_ocr extracts word boxes
        THEN expect bbox coordinates to be numeric
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def precise_positioning_ocr(image_data):
            return self.create_mock_ocr_future({
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
        
        mock_ocr_instance.process_image_multi_engine = precise_positioning_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    words = image_result['words']
                    
                    for i, word in enumerate(words):
                        bbox = word['bbox']
                        assert all(isinstance(coord, (int, float)) for coord in bbox), f"All bbox coordinates must be int or float: {bbox}"

    @pytest.mark.asyncio
    async def test_process_ocr_word_level_positioning_accuracy_bbox_logical_order(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN images with text requiring precise positioning
        WHEN _process_ocr extracts word boxes
        THEN expect bbox coordinates to be in logical order (x1 < x2, y1 < y2)
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def precise_positioning_ocr(image_data):
            return self.create_mock_ocr_future({
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
        
        mock_ocr_instance.process_image_multi_engine = precise_positioning_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    words = image_result['words']
                    
                    for i, word in enumerate(words):
                        bbox = word['bbox']
                        # Verify logical bbox (x1 < x2, y1 < y2)
                        x1, y1, x2, y2 = bbox
                        assert x1 < x2, f"Invalid bbox x coordinates: {bbox}"
                        assert y1 < y2, f"Invalid bbox y coordinates: {bbox}"

    @pytest.mark.asyncio
    async def test_process_ocr_word_level_positioning_accuracy_spatial_relationships_preserved(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN images with text requiring precise positioning
        WHEN _process_ocr extracts word boxes
        THEN expect spatial relationships to be preserved (words ordered left-to-right)
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def precise_positioning_ocr(image_data):
            return self.create_mock_ocr_future({
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
        
        mock_ocr_instance.process_image_multi_engine = precise_positioning_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            found_positioning = False
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    words = image_result['words']
                    
                    for i, word in enumerate(words):
                        bbox = word['bbox']
                        x1, y1, x2, y2 = bbox
                        
                        # Verify spatial relationships (words should be ordered left-to-right)
                        if i > 0:  # Skip first word
                            prev_word = words[i-1]
                            prev_x2 = prev_word['bbox'][2]
                            assert x1 >= prev_x2 - self.EXPECTED_SPATIAL_OVERLAP_TOLERANCE, "Words should maintain spatial order"  # Allow small overlap
                        
                        found_positioning = True

            assert found_positioning, "Should find word-level positioning data"

    @pytest.mark.asyncio
    async def test_process_ocr_confidence_scoring_accuracy_confidence_range_valid(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN OCR processing of various image qualities
        WHEN _process_ocr generates confidence scores
        THEN expect confidence scores to be within valid range
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
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
            
            return self.create_mock_ocr_future({
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
        
        mock_ocr_instance.process_image_multi_engine = varying_confidence_ocr

        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)

            # Verify confidence scoring
            confidences = []
            for page_key, page_result in result.items():
                assert isinstance(page_result, dict), f"Expected page_result to be dict, got {type(page_result)}: {page_result}"
                assert 'images' in page_result, f"'images' not found in page_result keys: {list(page_result.keys())}"
                for image_result in page_result['images']:
                    assert 'confidence' in image_result, f"'confidence' not found in image_result keys: {list(image_result.keys())}"
                    confidence = image_result['confidence']
                    
                    # Verify confidence range
                    self.assert_confidence_range(confidence)
                    confidences.append(confidence)

    @pytest.mark.asyncio
    async def test_process_ocr_confidence_scoring_accuracy_engine_comparison_present(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN OCR processing of various image qualities
        WHEN _process_ocr generates confidence scores
        THEN expect engine comparison data to be present
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
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
            
            return self.create_mock_ocr_future({
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
        
        mock_ocr_instance.process_image_multi_engine = varying_confidence_ocr

        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)

            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    # Verify engine comparison
                    assert 'engine_comparison' in image_result, f"'engine_comparison' not found in image_result keys: {list(image_result.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_confidence_scoring_accuracy_engine_comparison_is_dict(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN OCR processing of various image qualities
        WHEN _process_ocr generates confidence scores
        THEN expect engine comparison to be dictionary
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
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
            
            return self.create_mock_ocr_future({
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
        
        mock_ocr_instance.process_image_multi_engine = varying_confidence_ocr

        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)

            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    comparison = image_result['engine_comparison']
                    assert isinstance(comparison, dict), f"Expected comparison to be dict, got {type(comparison)}: {comparison}"

    @pytest.mark.asyncio
    async def test_process_ocr_confidence_scoring_accuracy_minimum_engines_compared(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN OCR processing of various image qualities
        WHEN _process_ocr generates confidence scores
        THEN expect minimum number of engines to be compared
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
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
            
            return self.create_mock_ocr_future({
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
        
        mock_ocr_instance.process_image_multi_engine = varying_confidence_ocr

        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)

            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    comparison = image_result['engine_comparison']
                    assert len(comparison) >= self.EXPECTED_MINIMUM_ENGINES_COUNT, f"Expected at least {self.EXPECTED_MINIMUM_ENGINES_COUNT} engines in comparison, got {len(comparison)}: {list(comparison.keys())}"

    @pytest.mark.asyncio
    async def test_process_ocr_confidence_scoring_accuracy_comparison_scores_valid(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN OCR processing of various image qualities
        WHEN _process_ocr generates confidence scores
        THEN expect all comparison scores to be valid
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
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
            
            return self.create_mock_ocr_future({
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
        
        mock_ocr_instance.process_image_multi_engine = varying_confidence_ocr

        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)

            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    comparison = image_result['engine_comparison']
                    # All comparison scores should be valid
                    for engine, score in comparison.items():
                        self.assert_confidence_range(score)

    @pytest.mark.asyncio
    async def test_process_ocr_confidence_scoring_accuracy_has_confidence_scores(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN OCR processing of various image qualities
        WHEN _process_ocr generates confidence scores
        THEN expect to have confidence scores for processed images
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
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
            
            return self.create_mock_ocr_future({
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
        
        mock_ocr_instance.process_image_multi_engine = varying_confidence_ocr

        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)

            # Verify confidence scoring
            confidences = []
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    confidence = image_result['confidence']
                    confidences.append(confidence)
            
            # Should have confidence scores for processed images
            assert len(confidences) > self.EXPECTED_MINIMUM_NON_EMPTY_RESULT, f"No confidence scores found: {confidences}"

    @pytest.mark.asyncio
    async def test_process_ocr_confidence_scoring_accuracy_multiple_confidence_scores(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN OCR processing of various image qualities
        WHEN _process_ocr generates confidence scores
        THEN expect multiple confidence scores from different quality processing
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
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
            
            return self.create_mock_ocr_future({
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
        
        mock_ocr_instance.process_image_multi_engine = varying_confidence_ocr

        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)

            # Verify confidence scoring
            confidences = []
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    confidence = image_result['confidence']
                    confidences.append(confidence)
            
            # Verify range of confidences (should vary based on quality)
            assert len(confidences) > self.EXPECTED_MINIMUM_LANGUAGES_COUNT, f"Expected multiple confidence scores, got {len(confidences)}: {confidences}"

    @pytest.mark.asyncio
    async def test_process_ocr_confidence_scoring_accuracy_varying_confidence_scores(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN OCR processing of various image qualities
        WHEN _process_ocr generates confidence scores
        THEN expect varying confidence scores based on quality
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
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
            
            return self.create_mock_ocr_future({
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
        
        mock_ocr_instance.process_image_multi_engine = varying_confidence_ocr

        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)

            # Verify confidence scoring
            confidences = []
            for page_key, page_result in result.items():
                for image_result in page_result['images']:
                    confidence = image_result['confidence']
                    confidences.append(confidence)
            
            assert max(confidences) > min(confidences), "Should have varying confidence scores"

    @pytest.mark.asyncio
    async def test_process_ocr_engine_comparison_and_selection(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN multiple OCR engines with different strengths
        WHEN _process_ocr compares engine results
        THEN expect:
            - Best engine selected based on confidence scores
            - Engine-specific results available for comparison
            - Accuracy validation across engines
            - Optimal results chosen for downstream processing
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def multi_engine_comparison(image_data):
            return self.create_mock_ocr_future({
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
        
        mock_ocr_instance.process_image_multi_engine = multi_engine_comparison

        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)

            # Verify engine comparison and selection
            found_comparison = False
            for page_key, page_result in result.items():
                assert isinstance(page_result, dict), f"Expected page_result to be dict, got {type(page_result)}: {page_result}"
                assert 'images' in page_result, f"'images' not found in page_result keys: {list(page_result.keys())}"
                for image_result in page_result['images']:
                    # Verify best engine selection
                    assert 'engine' in image_result, f"'engine' not found in image_result keys: {list(image_result.keys())}"
                    assert isinstance(image_result['engine'], str), f"Expected engine to be str, got {type(image_result['engine'])}: {image_result['engine']}"
                    assert len(image_result['engine']) > self.EXPECTED_MINIMUM_NON_EMPTY_RESULT, f"Engine name should not be empty: '{image_result['engine']}'"
                    
                    # Verify engine comparison data
                    assert 'all_engines' in image_result, f"'all_engines' not found in image_result keys: {list(image_result.keys())}"
                    engines = image_result['all_engines']
                    assert isinstance(engines, dict), f"Expected engines to be dict, got {type(engines)}: {engines}"
                    assert len(engines) >= self.EXPECTED_MINIMUM_ENGINES_COUNT, f"Expected at least {self.EXPECTED_MINIMUM_ENGINES_COUNT} engines, got {len(engines)}: {list(engines.keys())}"
                    
                    # Verify best engine has highest confidence
                    assert 'confidence' in image_result, f"'confidence' not found in image_result keys: {list(image_result.keys())}"
                    assert 'engine' in image_result, f"'engine' not found in image_result keys: {list(image_result.keys())}"
                    best_engine = image_result['engine']
                    best_confidence = image_result['confidence']
                    
                    assert best_engine in engines, f"Best engine '{best_engine}' not found in engines: {list(engines.keys())}"
                    assert engines[best_engine] == best_confidence, f"Engine {best_engine} confidence mismatch: {engines[best_engine]} != {best_confidence}"
                    
                    # Verify it's actually the best
                    for engine, confidence in engines.items():
                        assert confidence <= best_confidence, f"Engine {engine} confidence {confidence} > best confidence {best_confidence}"
                    
                    found_comparison = True
                    
                    # Verify selection reasoning
                    assert 'selected_reason' in image_result, f"'selected_reason' not found in image_result keys: {list(image_result.keys())}"
                    reason = image_result['selected_reason']
                    assert isinstance(reason, str), f"Expected reason to be str, got {type(reason)}: {reason}"
                    assert reason in ['highest_confidence', 'best_accuracy', 'fastest', 'balanced'], f"Invalid reason '{reason}', expected one of: ['highest_confidence', 'best_accuracy', 'fastest', 'balanced']"
            
            assert found_comparison, "Should perform engine comparison and selection"

    @pytest.mark.asyncio
    async def test_process_ocr_no_images_in_content(self, processor, sample_decomposed_content_no_images, mock_multi_engine_ocr_class):
        """
        GIVEN decomposed content with no embedded images
        WHEN _process_ocr processes content
        THEN expect:
            - Empty OCR results returned
            - No processing errors for image-free content
            - Graceful handling of missing image data
            - Consistent result structure maintained
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_no_images)
            
            # Verify empty results
            assert isinstance(result, dict)
            
            # Verify result structure indicates no images
            for page_key, page_result in result.items():
                assert isinstance(page_result, dict), f"Expected page_result to be dict, got {type(page_result)}: {page_result}"
                assert 'images' in page_result, f"'images' not found in page_result keys: {list(page_result.keys())}"
                assert len(page_result['images']) == self.EXPECTED_EMPTY_LIST_LENGTH, f"Expected empty images list, got {len(page_result['images'])} images: {page_result['images']}"
                assert 'ocr_results' not in page_result or len(page_result['ocr_results']) == self.EXPECTED_EMPTY_LIST_LENGTH, f"Expected no ocr_results or empty ocr_results, got: {page_result.get('ocr_results', 'not present')}"
                
                # OCR engine should not be called for processing
                assert not mock_ocr_instance.process_image_multi_engine.called, f"OCR engine should not be called when no images present, but was called: {mock_ocr_instance.process_image_multi_engine.call_count} times"

    @pytest.mark.asyncio
    async def test_process_ocr_large_image_memory_management(self, processor, large_image_content, mock_multi_engine_ocr_class):
        """
        GIVEN very large embedded images requiring OCR processing
        WHEN _process_ocr handles large images
        THEN expect MemoryError to be raised when limits exceeded
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def memory_exhaustion(image_data):
            if len(image_data) > 50 * 1024 * 1024:  # > 50MB
                raise MemoryError("Image too large for OCR processing")
            return self.create_mock_ocr_future({'best_result': {'text': 'small image', 'confidence': 0.8}})
        
        mock_ocr_instance.process_image_multi_engine = memory_exhaustion
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
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
    async def test_process_ocr_corrupted_image_handling(self, processor, corrupted_image_content, mock_multi_engine_ocr_class):
        """
        GIVEN decomposed content with corrupted or unsupported image formats
        WHEN _process_ocr processes problematic images
        THEN expect RuntimeError to be raised with format/corruption details
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def corrupted_image_error(image_data):
            if image_data == b'corrupted_image_data_not_valid':
                raise RuntimeError("Corrupted or unsupported image format detected")
            return self.create_mock_ocr_future({'best_result': {'text': 'valid image', 'confidence': 0.8}})
        
        mock_ocr_instance.process_image_multi_engine = corrupted_image_error
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute and expect RuntimeError
            with pytest.raises(RuntimeError, match="Corrupted|unsupported|image format"):
                await processor._process_ocr(corrupted_image_content)

    @pytest.mark.asyncio
    async def test_process_ocr_timeout_handling(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN OCR processing that exceeds configured timeout limits
        WHEN _process_ocr runs for extended time
        THEN expect TimeoutError to be raised
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        async def timeout_simulation(image_data):
            await asyncio.sleep(10)  # Simulate long processing
            return {'best_result': {'text': 'slow result', 'confidence': 0.8}}
        
        mock_ocr_instance.process_image_multi_engine = timeout_simulation
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute with timeout
            with pytest.raises((TimeoutError, asyncio.TimeoutError)):
                await asyncio.wait_for(
                    processor._process_ocr(sample_decomposed_content_with_images),
                    timeout=1.0  # 1 second timeout
                )

    @pytest.mark.asyncio
    async def test_process_ocr_image_format_compatibility(self, processor, multi_format_image_content, mock_multi_engine_ocr_class):
        """
        GIVEN images in various formats (JPEG, PNG, TIFF, etc.)
        WHEN _process_ocr processes different formats
        THEN expect:
            - All common formats handled correctly
            - Format-specific optimizations applied
            - Consistent results across formats
            - No format-related processing errors
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
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
            
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': f'Text from {format_detected} image',
                    'confidence': 0.85,
                    'format_detected': format_detected,
                    'engine': 'easyocr'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = format_specific_ocr

        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(multi_format_image_content)

            # Verify format compatibility
            formats_processed = set()
            for page_key, page_result in result.items():
                assert isinstance(page_result, dict), f"Expected page_result to be dict, got {type(page_result)}: {page_result}"
                assert 'images' in page_result, f"'images' not found in page_result keys: {list(page_result.keys())}"
                for image_result in page_result['images']:
                    formats_processed.add(image_result.get('format_detected', 'UNKNOWN'))
                    
                    # Verify consistent result structure
                    self.assert_image_result_structure(image_result)

            # Should process multiple formats
            assert len(formats_processed) >= self.EXPECTED_MINIMUM_ENGINES_COUNT, f"Expected at least {self.EXPECTED_MINIMUM_ENGINES_COUNT} formats processed, got {len(formats_processed)}: {formats_processed}"

    @pytest.mark.asyncio
    async def test_process_ocr_selection_reason_is_string(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """Test that selection reason is a string."""
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def multi_engine_comparison(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR result',
                    'confidence': 0.91,
                    'engine': 'easyocr',
                    'selected_reason': 'highest_confidence'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = multi_engine_comparison
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            self.assert_basic_ocr_result_structure(result)
            for page_result in result.values():
                for image_result in page_result['images']:
                    assert isinstance(image_result['selected_reason'], str), f"Expected selected_reason to be str, got {type(image_result['selected_reason'])}: {image_result['selected_reason']}"

    @pytest.mark.asyncio
    async def test_process_ocr_selection_reason_valid_value(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """Test that selection reason has valid value."""
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def multi_engine_comparison(image_data):
            return self.create_mock_ocr_future({
                'best_result': {
                    'text': 'EasyOCR result',
                    'confidence': 0.91,
                    'engine': 'easyocr',
                    'selected_reason': 'highest_confidence'
                }
            })
        
        mock_ocr_instance.process_image_multi_engine = multi_engine_comparison
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            valid_reasons = ['highest_confidence', 'best_accuracy', 'fastest', 'balanced']
            for page_result in result.values():
                assert isinstance(page_result, dict), f"Expected page_result to be dict, got {type(page_result)}: {page_result}"
                assert 'images' in page_result, f"'images' not found in page_result keys: {list(page_result.keys())}"
                for image_result in page_result['images']:
                    assert 'selected_reason' in image_result, f"'selected_reason' not found in image_result keys: {list(image_result.keys())}"
                    reason = image_result['selected_reason']
                    assert reason in valid_reasons, f"Invalid reason '{reason}', expected one of: {valid_reasons}"

    @pytest.mark.asyncio
    async def test_process_ocr_no_images_returns_dict(self, processor, sample_decomposed_content_no_images, mock_multi_engine_ocr_class):
        """Test that no images content returns dictionary."""
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            result = await processor._process_ocr(sample_decomposed_content_no_images)
            assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_process_ocr_no_images_empty_results(self, processor, sample_decomposed_content_no_images, mock_multi_engine_ocr_class):
        """Test that no images content has empty image results."""
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            result = await processor._process_ocr(sample_decomposed_content_no_images)
            
            for page_result in result.values():
                assert isinstance(page_result, dict), f"Expected page_result to be dict, got {type(page_result)}: {page_result}"
                assert 'images' in page_result, f"'images' not found in page_result keys: {list(page_result.keys())}"
                assert len(page_result['images']) == self.EXPECTED_EMPTY_LIST_LENGTH, f"Expected empty images list, got {len(page_result['images'])} images: {page_result['images']}"

    @pytest.mark.asyncio
    async def test_process_ocr_no_images_engine_not_called(self, processor, sample_decomposed_content_no_images, mock_multi_engine_ocr_class):
        """Test that OCR engine is not called when no images present."""
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            await processor._process_ocr(sample_decomposed_content_no_images)
            
            assert not mock_ocr_instance.process_image_multi_engine.called, f"OCR engine should not be called when no images present, but was called: {mock_ocr_instance.process_image_multi_engine.call_count} times"

    @pytest.mark.asyncio
    async def test_process_ocr_large_image_raises_memory_error(self, processor, large_image_content, mock_multi_engine_ocr_class):
        """Test that very large images raise MemoryError."""
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def memory_exhaustion(image_data):
            if len(image_data) > 50 * 1024 * 1024:  # > 50MB
                raise MemoryError("Image too large for OCR processing")
            return self.create_mock_ocr_future({'best_result': {'text': 'small image', 'confidence': 0.8}})
        
        mock_ocr_instance.process_image_multi_engine = memory_exhaustion
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute and expect MemoryError
            with pytest.raises(MemoryError, match="Image too large|too large"):
                await processor._process_ocr(large_image_content)

    @pytest.mark.asyncio
    async def test_process_ocr_result_aggregation_and_quality_metrics(self, processor, sample_decomposed_content_with_images, mock_multi_engine_ocr_class):
        """
        GIVEN OCR results from multiple engines and images
        WHEN _process_ocr aggregates results
        THEN expect:
            - Overall confidence scores calculated
            - Text quality metrics computed
            - Engine performance comparison available
            - Aggregate statistics for quality assessment
        """
        mock_ocr_class, mock_ocr_instance = mock_multi_engine_ocr_class
        
        def detailed_metrics_ocr(image_data):
            return self.create_mock_ocr_future({
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
        
        mock_ocr_instance.process_image_multi_engine = detailed_metrics_ocr
        
        # Mock the OCR engine
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.MultiEngineOCR', mock_ocr_class):
            # Execute the method
            result = await processor._process_ocr(sample_decomposed_content_with_images)
            
            # Verify aggregated metrics
            found_aggregation = False
            for page_key, page_result in result.items():
                assert isinstance(page_result, dict), f"Expected page_result to be dict, got {type(page_result)}: {page_result}"
                assert 'images' in page_result, f"'images' not found in page_result keys: {list(page_result.keys())}"
                for image_result in page_result['images']:
                    # Check for aggregated metrics
                    assert 'aggregated_metrics' in image_result, f"'aggregated_metrics' not found in image_result keys: {list(image_result.keys())}"
                    metrics = image_result['aggregated_metrics']
                    
                    # Verify metric completeness
                    assert 'average_confidence' in metrics, f"'average_confidence' not found in metrics keys: {list(metrics.keys())}"
                    assert 'engines_used' in metrics, f"'engines_used' not found in metrics keys: {list(metrics.keys())}"
                    
                    # Verify metric validity
                    self.assert_confidence_range(metrics['average_confidence'])
                    assert isinstance(metrics['engines_used'], list), f"Expected engines_used to be list, got {type(metrics['engines_used'])}: {metrics['engines_used']}"
                    assert len(metrics['engines_used']) > self.EXPECTED_MINIMUM_NON_EMPTY_RESULT, f"Expected non-empty engines_used list, got {len(metrics['engines_used'])} engines: {metrics['engines_used']}"
                    
                    found_aggregation = True
                    
                    # Check for quality assessment
                    assert 'quality_score' in image_result or ('aggregated_metrics' in image_result and 'quality_score' in image_result['aggregated_metrics']), f"'quality_score' not found in image_result or aggregated_metrics. Image keys: {list(image_result.keys())}, Metrics keys: {list(metrics.keys())}"
                    quality_score = image_result.get('quality_score') or image_result['aggregated_metrics']['quality_score']
                    self.assert_confidence_range(quality_score)
            
            # Should provide aggregated results or at least basic metrics
            assert len(result) > self.EXPECTED_MINIMUM_NON_EMPTY_RESULT, f"Expected non-empty result, got length {len(result)}: {result}"



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
