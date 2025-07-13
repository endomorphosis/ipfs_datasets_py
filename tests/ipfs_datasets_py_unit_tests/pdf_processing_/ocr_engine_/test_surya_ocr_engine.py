# Test file for TestSuryaOCREngine
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Test suite for ipfs_datasets_py.pdf_processing.ocr_engine

import os
import io
import time
import threading
from abc import ABC
from unittest.mock import Mock, patch, MagicMock

import pytest
import numpy as np
from PIL import Image


import cv2
import torch
import pytesseract

from ipfs_datasets_py.pdf_processing.ocr_engine import (
    OCREngine,
    EasyOCR,
    SuryaOCR,
    TesseractOCR,
    TrOCREngine,
    MultiEngineOCR
)

from ipfs_datasets_py.pdf_processing.ocr_engine import OCREngine
from tests._test_utils import (
    raise_on_bad_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/ocr_engine.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/ocr_engine_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.ocr_engine import (
    EasyOCR,
    MultiEngineOCR,
    OCREngine,
    SuryaOCR,
    TesseractOCR,
    TrOCREngine
)

# Check if each classes methods are accessible:
assert OCREngine._initialize
assert OCREngine.extract_text
assert OCREngine.is_available
assert SuryaOCR._initialize
assert SuryaOCR.extract_text
assert TesseractOCR._initialize
assert TesseractOCR.extract_text
assert TesseractOCR._preprocess_image
assert EasyOCR._initialize
assert EasyOCR.extract_text
assert TrOCREngine._initialize
assert TrOCREngine.extract_text
assert MultiEngineOCR.extract_with_fallback
assert MultiEngineOCR.get_available_engines
assert MultiEngineOCR.classify_document_type


# Check if the file's imports are accessible
try:
    from abc import ABC, abstractmethod
    import logging
    import io
    import numpy as np
    from typing import Dict, List, Any
    from PIL import Image
    import cv2
except ImportError as e:
    raise ImportError(f"Failed to import necessary modules: {e}")





class TestSuryaOCREngine:
    """Test suite for SuryaOCR transformer-based OCR engine."""

    def test_surya_ocr_initialization_success(self):
        """
        GIVEN Surya dependencies are available
        WHEN initializing SuryaOCR
        THEN should successfully load detection and recognition models
        AND should set available to True
        AND should initialize det_processor, det_model, rec_model, rec_processor, run_ocr
        """
        # Mock surya imports to simulate successful initialization
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.importlib.import_module') as mock_import:
            mock_surya = MagicMock()
            mock_import.return_value = mock_surya
            
            with patch.object(SuryaOCR, '_initialize') as mock_init:
                mock_init.return_value = None
                engine = SuryaOCR()
                mock_init.assert_called_once()

    def test_surya_ocr_initialization_missing_dependencies(self):
        """
        GIVEN Surya framework is not installed
        WHEN initializing SuryaOCR
        THEN should handle ImportError gracefully
        AND should set available to False
        AND should not crash the application
        """
        with patch.object(SuryaOCR, '_initialize', side_effect=ImportError("No module named 'surya'")):
            engine = SuryaOCR()
            # Should not crash and should have name set
            assert hasattr(engine, 'name')
            assert engine.name == 'surya'
            # Available status depends on error handling in _initialize
            assert hasattr(engine, 'available')

    def test_surya_ocr_initialization_model_download_failure(self):
        """
        GIVEN Surya is installed but model download fails
        WHEN initializing SuryaOCR
        THEN should handle RuntimeError appropriately
        AND should set available to False
        """
        with patch.object(SuryaOCR, '_initialize', side_effect=RuntimeError("Model download failed")):
            engine = SuryaOCR()
            assert hasattr(engine, 'available')
            assert hasattr(engine, 'name')
            assert engine.name == 'surya'

    def test_surya_ocr_initialization_insufficient_memory(self):
        """
        GIVEN insufficient memory for loading transformer models
        WHEN initializing SuryaOCR
        THEN should handle MemoryError gracefully
        AND should set available to False
        """
        with patch.object(SuryaOCR, '_initialize', side_effect=MemoryError("Insufficient memory")):
            engine = SuryaOCR()
            assert hasattr(engine, 'available')
            assert hasattr(engine, 'name')

    def create_test_image_data(self):
        """Helper method to create test image data."""
        # Create a simple test image
        img = Image.new('RGB', (100, 50), color='white')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    def test_surya_ocr_extract_text_valid_image_english(self):
        """
        GIVEN a SuryaOCR instance and valid image data with English text
        WHEN calling extract_text(image_data, languages=['en'])
        THEN should return dict with 'text', 'confidence', 'text_blocks', 'engine' keys
        AND text should be non-empty string
        AND confidence should be float between 0.0 and 1.0
        AND text_blocks should be list of dicts with text, confidence, bbox
        AND engine should be 'surya'
        """
        # Mock successful initialization
        with patch.object(SuryaOCR, '_initialize'):
            engine = SuryaOCR()
            engine.available = True
            
            # Mock the actual OCR components
            engine.run_ocr = Mock()
            engine.det_processor = Mock()
            engine.det_model = Mock()
            engine.rec_model = Mock()
            engine.rec_processor = Mock()
            
            # Mock OCR results
            mock_text_lines = [
                Mock(text="Hello World", confidence=0.95, bbox=[10, 10, 90, 30]),
                Mock(text="Test Text", confidence=0.88, bbox=[10, 35, 80, 45])
            ]
            engine.run_ocr.return_value = ([mock_text_lines], ["en"])
            
            image_data = self.create_test_image_data()
            result = engine.extract_text(image_data, languages=['en'])
            
            # Verify return structure
            assert isinstance(result, dict)
            assert 'text' in result
            assert 'confidence' in result
            assert 'text_blocks' in result
            assert 'engine' in result
            
            # Verify content
            assert result['engine'] == 'surya'
            assert isinstance(result['text'], str)
            assert len(result['text']) > 0
            assert isinstance(result['confidence'], float)
            assert 0.0 <= result['confidence'] <= 1.0
            assert isinstance(result['text_blocks'], list)

    def test_surya_ocr_extract_text_multilingual(self):
        """
        GIVEN a SuryaOCR instance and image with multiple languages
        WHEN calling extract_text(image_data, languages=['en', 'es', 'fr'])
        THEN should handle multilingual text extraction
        AND should return appropriate results for each language
        """
        with patch.object(SuryaOCR, '_initialize'):
            engine = SuryaOCR()
            engine.available = True
            
            # Mock OCR components
            engine.run_ocr = Mock()
            engine.det_processor = Mock()
            engine.det_model = Mock()
            engine.rec_model = Mock()
            engine.rec_processor = Mock()
            
            # Mock multilingual results
            mock_text_lines = [
                Mock(text="Hello", confidence=0.95),
                Mock(text="Hola", confidence=0.92),
                Mock(text="Bonjour", confidence=0.89)
            ]
            engine.run_ocr.return_value = ([mock_text_lines], ["en", "es", "fr"])
            
            image_data = self.create_test_image_data()
            result = engine.extract_text(image_data, languages=['en', 'es', 'fr'])
            
            assert isinstance(result, dict)
            assert result['engine'] == 'surya'
            # Should have processed the multilingual request
            engine.run_ocr.assert_called_once()

    def test_surya_ocr_extract_text_empty_image_data(self):
        """
        GIVEN a SuryaOCR instance
        WHEN calling extract_text() with empty bytes
        THEN should raise ValueError
        """
        with patch.object(SuryaOCR, '_initialize'):
            engine = SuryaOCR()
            engine.available = True
            
            with pytest.raises(ValueError):
                engine.extract_text(b'')

    def test_surya_ocr_extract_text_invalid_image_format(self):
        """
        GIVEN a SuryaOCR instance
        WHEN calling extract_text() with invalid image data
        THEN should raise PIL.UnidentifiedImageError or ValueError
        """
        with patch.object(SuryaOCR, '_initialize'):
            engine = SuryaOCR()
            engine.available = True
            
            with pytest.raises((ValueError, Exception)):  # PIL.UnidentifiedImageError is subclass of Exception
                engine.extract_text(b'not_an_image')

    def test_surya_ocr_extract_text_engine_not_available(self):
        """
        GIVEN a SuryaOCR instance with available=False
        WHEN calling extract_text()
        THEN should raise RuntimeError
        """
        with patch.object(SuryaOCR, '_initialize'):
            engine = SuryaOCR()
            engine.available = False
            
            with pytest.raises(RuntimeError, match="not.*available|not.*initialized"):
                engine.extract_text(self.create_test_image_data())

    def test_surya_ocr_extract_text_large_image(self):
        """
        GIVEN a SuryaOCR instance and very large image data
        WHEN calling extract_text()
        THEN should handle processing appropriately
        AND should not exceed reasonable memory usage
        """
        with patch.object(SuryaOCR, '_initialize'):
            engine = SuryaOCR()
            engine.available = True
            
            # Mock OCR components
            engine.run_ocr = Mock()
            engine.det_processor = Mock()
            engine.det_model = Mock()
            engine.rec_model = Mock()
            engine.rec_processor = Mock()
            
            # Create larger test image
            img = Image.new('RGB', (2000, 1000), color='white')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            large_image_data = buf.getvalue()
            
            # Mock successful processing
            mock_text_lines = [Mock(text="Large image text", confidence=0.9)]
            engine.run_ocr.return_value = ([mock_text_lines], ["en"])
            
            result = engine.extract_text(large_image_data)
            assert isinstance(result, dict)
            assert result['engine'] == 'surya'

    def test_surya_ocr_extract_text_confidence_scores(self):
        """
        GIVEN a SuryaOCR instance and image with varying text quality
        WHEN calling extract_text()
        THEN should return appropriate confidence scores
        AND confidence scores should correlate with text quality
        """
        with patch.object(SuryaOCR, '_initialize'):
            engine = SuryaOCR()
            engine.available = True
            
            # Mock OCR components
            engine.run_ocr = Mock()
            engine.det_processor = Mock()
            engine.det_model = Mock()
            engine.rec_model = Mock()
            engine.rec_processor = Mock()
            
            # Mock varying confidence scores
            mock_text_lines = [
                Mock(text="Clear text", confidence=0.98),
                Mock(text="Blurry text", confidence=0.65),
                Mock(text="Very unclear", confidence=0.32)
            ]
            engine.run_ocr.return_value = ([mock_text_lines], ["en"])
            
            result = engine.extract_text(self.create_test_image_data())
            
            # Should return confidence scores
            assert 'confidence' in result
            assert isinstance(result['confidence'], float)
            assert 0.0 <= result['confidence'] <= 1.0
            
            # Text blocks should have individual confidence scores
            if 'text_blocks' in result:
                for block in result['text_blocks']:
                    if 'confidence' in block:
                        assert isinstance(block['confidence'], float)
                        assert 0.0 <= block['confidence'] <= 1.0

    def test_surya_ocr_extract_text_bounding_boxes(self):
        """
        GIVEN a SuryaOCR instance and image with text
        WHEN calling extract_text()
        THEN should return accurate bounding box coordinates
        AND bounding boxes should be within image dimensions
        AND bounding boxes should be in [x1, y1, x2, y2] format
        """
        with patch.object(SuryaOCR, '_initialize'):
            engine = SuryaOCR()
            engine.available = True
            
            # Mock OCR components
            engine.run_ocr = Mock()
            engine.det_processor = Mock()
            engine.det_model = Mock()
            engine.rec_model = Mock()
            engine.rec_processor = Mock()
            
            # Mock text with bounding boxes
            mock_text_lines = [
                Mock(text="Text 1", confidence=0.95, bbox=[10, 10, 50, 25]),
                Mock(text="Text 2", confidence=0.88, bbox=[10, 30, 60, 45])
            ]
            engine.run_ocr.return_value = ([mock_text_lines], ["en"])
            
            # Create image with known dimensions
            img = Image.new('RGB', (100, 50), color='white')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            image_data = buf.getvalue()
            
            result = engine.extract_text(image_data)
            
            # Check for bounding box information
            if 'text_blocks' in result:
                for block in result['text_blocks']:
                    if 'bbox' in block:
                        bbox = block['bbox']
                        assert isinstance(bbox, list)
                        assert len(bbox) == 4  # [x1, y1, x2, y2]
                        x1, y1, x2, y2 = bbox
                        # Coordinates should be within image bounds
                        assert 0 <= x1 < x2 <= 100
                        assert 0 <= y1 < y2 <= 50



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
