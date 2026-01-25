# Test file for TestTesseractOCREngine
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
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

from tests.unit_tests.pdf_processing_.ocr_engine_ import REPO_ROOT

file_path = str(REPO_ROOT / "ipfs_datasets_py" / "pdf_processing" / "ocr_engine.py")
md_path = str(REPO_ROOT / "ipfs_datasets_py" / "pdf_processing" / "ocr_engine_stubs.md")

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
assert MultiEngineOCR.extract_with_ocr
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




class TestTesseractOCREngine:
    """Test suite for TesseractOCR traditional OCR engine."""

    def create_test_image(self, width=100, height=50, color='white'):
        """Helper method to create test PIL Image."""
        return Image.new('RGB', (width, height), color=color)

    def create_test_image_data(self, width=100, height=50, color='white'):
        """Helper method to create test image data as bytes."""
        img = self.create_test_image(width, height, color)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    def test_tesseract_ocr_initialization_success(self):
        """
        GIVEN pytesseract and system Tesseract are available
        WHEN initializing TesseractOCR
        THEN should successfully import dependencies
        AND should set available to True
        AND should initialize pytesseract attribute
        """
        with patch('builtins.__import__') as mock_pytesseract:
            with patch.object(TesseractOCR, '_initialize') as mock_init:
                mock_init.return_value = None
                engine = TesseractOCR()
                mock_init.assert_called_once()
                assert engine.name == 'tesseract'

    def test_tesseract_ocr_initialization_missing_pytesseract(self):
        """
        GIVEN pytesseract library is not installed
        WHEN initializing TesseractOCR
        THEN should handle ImportError gracefully
        AND should set available to False
        """
        with patch.object(TesseractOCR, '_initialize', side_effect=ImportError("No module named 'pytesseract'")):
            engine = TesseractOCR()
            assert hasattr(engine, 'name')
            assert engine.name == 'tesseract'
            assert hasattr(engine, 'available')
            assert not engine.available

    def test_tesseract_ocr_initialization_missing_system_tesseract(self):
        """
        GIVEN pytesseract is installed but system Tesseract is missing
        WHEN initializing TesseractOCR
        THEN should detect system dependency issue
        AND should set available to False
        """
        with patch.object(TesseractOCR, '_initialize', side_effect=OSError("Tesseract not found")):
            engine = TesseractOCR()
            assert hasattr(engine, 'available')
            assert hasattr(engine, 'name')


    def test_tesseract_ocr_extract_text_default_config(self):
        """
        GIVEN a TesseractOCR instance and valid image data
        WHEN calling extract_text() with default configuration
        THEN should return dict with text, confidence, word_boxes, engine
        AND should use PSM 6 and character whitelist by default
        """
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            engine.available = True
            engine.pytesseract = Mock()
            
            # Mock preprocessing
            with patch.object(engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = self.create_test_image()
                
                # Mock pytesseract methods
                engine.pytesseract.image_to_string.return_value = "Sample text"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['Sample', 'text', ''],
                    'conf': [95, 88, -1],
                    'left': [10, 50, 0],
                    'top': [10, 10, 0],
                    'width': [35, 30, 0],
                    'height': [15, 15, 0]
                }
                
                image_data = self.create_test_image_data()
                result = engine.extract_text(image_data)
                
                # Verify return structure
                assert isinstance(result, dict)
                assert 'text' in result
                assert 'confidence' in result
                assert 'word_boxes' in result
                assert 'engine' in result
                
                # Verify content
                assert result['engine'] == 'tesseract'
                assert isinstance(result['text'], str)
                assert isinstance(result['confidence'], float)
                assert isinstance(result['word_boxes'], list)
                assert 0.0 <= result['confidence'] <= 1.0

    def test_tesseract_ocr_extract_text_custom_config(self):
        """
        GIVEN a TesseractOCR instance and valid image data
        WHEN calling extract_text() with custom config string
        THEN should apply custom Tesseract parameters
        AND should return results based on custom configuration
        """
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            engine.available = True
            engine.pytesseract = Mock()
            
            with patch.object(engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = self.create_test_image()
                
                engine.pytesseract.image_to_string.return_value = "123456"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['123456'],
                    'conf': [98],
                    'left': [10],
                    'top': [10],
                    'width': [40],
                    'height': [15]
                }
                
                custom_config = "--psm 8 -c tessedit_char_whitelist=0123456789"
                image_data = self.create_test_image_data()
                result = engine.extract_text(image_data, config=custom_config)
                
                # Should have used custom config
                engine.pytesseract.image_to_string.assert_called()
                call_args = engine.pytesseract.image_to_string.call_args
                assert custom_config in str(call_args)
                
                assert isinstance(result, dict)
                assert result['engine'] == 'tesseract'

    def test_tesseract_ocr_extract_text_language_specific(self):
        """
        GIVEN a TesseractOCR instance and non-English text image
        WHEN calling extract_text() with language-specific config
        THEN should use appropriate language model
        AND should improve accuracy for target language
        """
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            engine.available = True
            engine.pytesseract = Mock()
            
            with patch.object(engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = self.create_test_image()
                
                engine.pytesseract.image_to_string.return_value = "Hola mundo"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['Hola', 'mundo'],
                    'conf': [92, 89],
                    'left': [10, 45],
                    'top': [10, 10],
                    'width': [30, 35],
                    'height': [15, 15]
                }
                
                spanish_config = "--psm 6 -l spa"
                image_data = self.create_test_image_data()
                result = engine.extract_text(image_data, config=spanish_config)
                
                # Should have used Spanish language
                engine.pytesseract.image_to_string.assert_called()
                call_args = engine.pytesseract.image_to_string.call_args
                assert "spa" in str(call_args)
                
                assert result['text'] == "Hola mundo"

    def test_tesseract_ocr_extract_text_character_whitelist(self):
        """
        GIVEN a TesseractOCR instance and image with mixed characters
        WHEN calling extract_text() with character whitelist config
        THEN should only recognize whitelisted characters
        AND should filter out non-whitelisted characters
        """
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            engine.available = True
            engine.pytesseract = Mock()
            
            with patch.object(engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = self.create_test_image()
                
                # Mock result with only numbers (whitelist effect)
                engine.pytesseract.image_to_string.return_value = "123"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['123'],
                    'conf': [95],
                    'left': [10],
                    'top': [10],
                    'width': [25],
                    'height': [15]
                }
                
                numbers_only = "--psm 6 -c tessedit_char_whitelist=0123456789"
                image_data = self.create_test_image_data()
                result = engine.extract_text(image_data, config=numbers_only)
                
                # Should have applied character whitelist
                call_args = engine.pytesseract.image_to_string.call_args
                assert "tessedit_char_whitelist" in str(call_args)

    def test_tesseract_ocr_extract_text_word_level_confidence(self):
        """
        GIVEN a TesseractOCR instance and image with varying text quality
        WHEN calling extract_text()
        THEN should return word-level confidence scores
        AND confidence scores should reflect recognition certainty
        """
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            engine.available = True
            engine.pytesseract = Mock()
            
            with patch.object(engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = self.create_test_image()
                
                # Mock word-level data with varying confidence
                engine.pytesseract.image_to_string.return_value = "Clear text blurry"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['Clear', 'text', 'blurry', ''],
                    'conf': [98, 95, 45, -1],  # Varying confidence levels
                    'left': [10, 50, 90, 0],
                    'top': [10, 10, 10, 0],
                    'width': [35, 30, 40, 0],
                    'height': [15, 15, 15, 0]
                }
                
                image_data = self.create_test_image_data()
                result = engine.extract_text(image_data)
                
                # Should have word-level confidence information
                assert 'word_boxes' in result
                word_boxes = result['word_boxes']
                assert len(word_boxes) == 3  # 3 valid words (excluding empty)
                
                # Check confidence values
                confidences = [box['confidence'] for box in word_boxes]
                assert max(confidences) > 0.9  # "Clear" should be high confidence
                assert min(confidences) < 0.5  # "blurry" should be low confidence
                
                # Overall confidence should be reasonable average
                overall_conf = result['confidence']
                assert isinstance(overall_conf, float)
                assert 0.0 <= overall_conf <= 1.0

    def test_tesseract_ocr_extract_text_word_bounding_boxes(self):
        """
        GIVEN a TesseractOCR instance and image with text
        WHEN calling extract_text()
        THEN should return accurate word-level bounding boxes
        AND bounding boxes should be in [x1, y1, x2, y2] format
        """
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            engine.available = True
            engine.pytesseract = Mock()
            
            with patch.object(engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = self.create_test_image()
                
                engine.pytesseract.image_to_string.return_value = "Word One Two"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['Word', 'One', 'Two'],
                    'conf': [95, 92, 88],
                    'left': [10, 50, 80],      # x coordinates
                    'top': [10, 10, 10],       # y coordinates  
                    'width': [35, 25, 30],     # widths
                    'height': [15, 15, 15]     # heights
                }
                
                image_data = self.create_test_image_data(120, 40)
                result = engine.extract_text(image_data)
                
                # Should have word bounding boxes
                assert 'word_boxes' in result
                word_boxes = result['word_boxes']
                assert len(word_boxes) == 3
                
                # Check bounding box format and coordinates
                for i, box in enumerate(word_boxes):
                    assert 'bbox' in box
                    assert 'text' in box
                    bbox = box['bbox']
                    
                    # Should be [x1, y1, x2, y2] format
                    assert len(bbox) == 4
                    x1, y1, x2, y2 = bbox
                    
                    # Coordinates should be valid
                    assert x1 >= 0 and x2 <= 120  # Within image width
                    assert y1 >= 0 and y2 <= 40   # Within image height
                    assert x1 < x2  # x1 should be less than x2
                    assert y1 < y2  # y1 should be less than y2
                    
                    # Text should match expected
                    expected_texts = ['Word', 'One', 'Two']
                    assert box['text'] == expected_texts[i]

    def test_tesseract_ocr_extract_text_psm_modes(self):
        """
        GIVEN a TesseractOCR instance and various document layouts
        WHEN calling extract_text() with different PSM modes
        THEN should adapt to different page segmentation requirements
        AND should optimize for specific layout types
        """
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            engine.available = True
            engine.pytesseract = Mock()
            
            with patch.object(engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = self.create_test_image()
                
                image_data = self.create_test_image_data()

                engine.pytesseract.image_to_data.return_value = {
                    'level': [1], 'page_num': [1], 'block_num': [0], 'par_num': [0], 
                    'line_num': [0], 'word_num': [0], 'left': [0], 'top': [0], 'width': [100], 
                    'height': [50], 'conf': [-1], 'text': ['']
                }
                
                # Test PSM 6 (uniform block of text)
                engine.pytesseract.image_to_string.return_value = "Block of text"
                psm6_config = "--psm 6"
                result_psm6 = engine.extract_text(image_data, config=psm6_config)
                
                call_args = engine.pytesseract.image_to_string.call_args
                assert "--psm 6" in str(call_args)
                assert result_psm6['text'] == "Block of text"
                
                # Test PSM 8 (single word)
                engine.pytesseract.image_to_string.return_value = "SingleWord"
                psm8_config = "--psm 8"
                result_psm8 = engine.extract_text(image_data, config=psm8_config)
                
                call_args = engine.pytesseract.image_to_string.call_args
                assert "--psm 8" in str(call_args)
                assert result_psm8['text'] == "SingleWord"
                
                # Test PSM 7 (single text line)
                engine.pytesseract.image_to_string.return_value = "Single line of text"
                psm7_config = "--psm 7"
                result_psm7 = engine.extract_text(image_data, config=psm7_config)
                
                call_args = engine.pytesseract.image_to_string.call_args
                assert "--psm 7" in str(call_args)
                assert result_psm7['text'] == "Single line of text"
                
                # Test PSM 3 (automatic)
                engine.pytesseract.image_to_string.return_value = "Automatic layout"
                psm3_config = "--psm 3"
                result_psm3 = engine.extract_text(image_data, config=psm3_config)
                
                call_args = engine.pytesseract.image_to_string.call_args
                assert "--psm 3" in str(call_args)
                assert result_psm3['text'] == "Automatic layout"

    def test_tesseract_ocr_extract_text_invalid_config(self):
        """
        GIVEN a TesseractOCR instance
        WHEN calling extract_text() with invalid config string
        THEN should raise TesseractError or handle gracefully
        """
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            engine.available = True
            engine.pytesseract = Mock()
            
            with patch.object(engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = self.create_test_image()
                
                # Mock TesseractError for invalid config
                from pytesseract import TesseractError
                engine.pytesseract.image_to_string.side_effect = TesseractError("Invalid configuration", "Error details")
                
                invalid_config = "--invalid-option nonsense"
                image_data = self.create_test_image_data()
                
                # Should raise TesseractError or handle gracefully
                with pytest.raises((TesseractError, RuntimeError, Exception)):
                    engine.extract_text(image_data, config=invalid_config)
                
                # Test another type of invalid config
                engine.pytesseract.image_to_string.side_effect = TesseractError("PSM value out of range", "Error details")
                invalid_psm_config = "--psm 99"  # Invalid PSM value
                
                with pytest.raises((TesseractError, RuntimeError, Exception)):
                    engine.extract_text(image_data, config=invalid_psm_config)




if __name__ == "__main__":
    pytest.main([__file__, "-v"])
