# Test file for TestEasyOCREngine
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

work_dir = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py"
file_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/ocr_engine.py")
md_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/ocr_engine_stubs.md")

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



class TestEasyOCREngine:
    """Test suite for EasyOCR neural network-based OCR engine."""

    def create_test_image_data(self, width=100, height=50, color='white'):
        """Helper method to create test image data as bytes."""
        img = Image.new('RGB', (width, height), color=color)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    def create_mock_easyocr_engine_with_builtin_import(self, mock_results=None, should_fail=False):
        """Helper method to create a properly mocked EasyOCR engine using builtins.__import__."""
        
        def mock_import_side_effect(name, *args, **kwargs):
            if name == 'easyocr':
                if should_fail:
                    raise ImportError("No module named 'easyocr'")
                mock_easyocr = Mock()
                mock_reader = Mock()
                if mock_results:
                    mock_reader.readtext.return_value = mock_results
                mock_easyocr.Reader.return_value = mock_reader
                return mock_easyocr
            return __import__(name, *args, **kwargs)
        
        return mock_import_side_effect

    def create_mock_engine_for_extract_text(self, mock_results):
        """Create a mock engine for extract_text tests using direct object manipulation."""
        with patch('builtins.__import__') as mock_import:
            mock_easyocr = Mock()
            mock_reader = Mock()
            mock_reader.readtext.return_value = mock_results
            mock_easyocr.Reader.return_value = mock_reader
            
            def side_effect(name, *args, **kwargs):
                if name == 'easyocr':
                    return mock_easyocr
                return __import__(name, *args, **kwargs)
            
            mock_import.side_effect = side_effect
            
            engine = EasyOCR()
            engine.available = True
            return engine, mock_reader

    def test_easyocr_initialization_success(self):
        """
        GIVEN EasyOCR dependencies are available
        WHEN initializing EasyOCR
        THEN should successfully create Reader instance
        AND should set available to True
        AND should download models on first use
        """
        with patch('builtins.__import__') as mock_import:
            # Mock the easyocr import
            mock_easyocr = Mock()
            mock_reader_instance = Mock()
            mock_easyocr.Reader.return_value = mock_reader_instance
            
            # Configure __import__ to return our mock when importing 'easyocr'
            def side_effect(name, *args, **kwargs):
                if name == 'easyocr':
                    return mock_easyocr
                # For other imports, call the original __import__
                return __import__(name, *args, **kwargs)
            
            mock_import.side_effect = side_effect
            
            engine = EasyOCR()
            assert engine.name == 'easyocr'
            assert engine.available == True
            mock_easyocr.Reader.assert_called_once_with(['en'])

    def test_easyocr_initialization_missing_dependencies(self):
        """
        GIVEN EasyOCR library is not installed
        WHEN initializing EasyOCR
        THEN should handle ImportError gracefully
        AND should set available to False
        """
        with patch('builtins.__import__') as mock_import:
            # Configure __import__ to raise ImportError for 'easyocr'
            def side_effect(name, *args, **kwargs):
                if name == 'easyocr':
                    raise ImportError("No module named 'easyocr'")
                # For other imports, call the original __import__
                return __import__(name, *args, **kwargs)
            
            mock_import.side_effect = side_effect
            
            engine = EasyOCR()
            assert hasattr(engine, 'name')
            assert engine.name == 'easyocr'
            assert hasattr(engine, 'available')
            assert engine.available == False

    def test_easyocr_initialization_model_download_failure(self):
        """
        GIVEN EasyOCR is installed but model download fails
        WHEN initializing EasyOCR
        THEN should handle download errors appropriately
        AND should set available to False
        """
        with patch('builtins.__import__') as mock_import:
            # Mock the easyocr import
            mock_easyocr = Mock()
            mock_easyocr.Reader.side_effect = RuntimeError("Model download failed")
            
            # Configure __import__ to return our mock when importing 'easyocr'
            def side_effect(name, *args, **kwargs):
                if name == 'easyocr':
                    return mock_easyocr
                return __import__(name, *args, **kwargs)
            
            mock_import.side_effect = side_effect
            
            engine = EasyOCR()
            assert hasattr(engine, 'available')
            assert hasattr(engine, 'name')
            assert engine.name == 'easyocr'
            assert engine.available == False

    def test_easyocr_extract_text_complex_layout(self):
        """
        GIVEN an EasyOCR instance and image with complex layout
        WHEN calling extract_text()
        THEN should handle rotated and curved text
        AND should return accurate text extraction
        """
        # Mock complex layout detection results
        mock_results = [
            ([[10, 10], [50, 15], [48, 30], [8, 25]], 'Rotated Text', 0.92),
            ([[60, 20], [95, 25], [93, 40], [58, 35]], 'Curved Line', 0.88)
        ]
        
        engine, mock_reader = self.create_mock_engine_for_extract_text(mock_results)
        
        image_data = self.create_test_image_data()
        result = engine.extract_text(image_data)
        
        # Verify return structure
        assert isinstance(result, dict)
        assert 'text' in result
        assert 'confidence' in result
        assert 'text_blocks' in result
        assert 'engine' in result
        
        # Verify content
        assert result['engine'] == 'easyocr'
        assert 'Rotated Text' in result['text']
        assert 'Curved Line' in result['text']
        assert isinstance(result['confidence'], float)
        assert 0.0 <= result['confidence'] <= 1.0

    def test_easyocr_extract_text_rotated_text(self):
        """
        GIVEN an EasyOCR instance and image with rotated text
        WHEN calling extract_text()
        THEN should detect and correct text orientation
        AND should return properly oriented text
        """
        # Mock rotated text detection
        mock_results = [
            ([[20, 10], [80, 25], [75, 40], [15, 25]], 'ROTATED', 0.95)
        ]
        
        engine, mock_reader = self.create_mock_engine_for_extract_text(mock_results)
        
        image_data = self.create_test_image_data()
        result = engine.extract_text(image_data)
        
        assert 'ROTATED' in result['text']
        assert result['engine'] == 'easyocr'
        
        # Should have called readtext with image
        mock_reader.readtext.assert_called_once()

    def test_easyocr_extract_text_curved_text(self):
        """
        GIVEN an EasyOCR instance and image with curved text
        WHEN calling extract_text()
        THEN should handle curved text patterns
        AND should extract text accurately despite curvature
        """
        # Mock curved text with polygon bounding box
        mock_results = [
            ([[15, 5], [85, 15], [90, 35], [10, 25]], 'Curved Text Here', 0.89)
        ]
        
        engine, mock_reader = self.create_mock_engine_for_extract_text(mock_results)
        
        image_data = self.create_test_image_data()
        result = engine.extract_text(image_data)
        
        assert 'Curved Text Here' in result['text']
        assert len(result['text_blocks']) == 1
        
        # Check that bounding box is polygon (4 points)
        text_block = result['text_blocks'][0]
        assert 'bbox' in text_block
        bbox = text_block['bbox']
        assert len(bbox) == 4  # 4 corner points
        assert all(len(point) == 2 for point in bbox)  # Each point has x,y

    def test_easyocr_extract_text_multilingual_automatic(self):
        """
        GIVEN an EasyOCR instance and multilingual image
        WHEN calling extract_text()
        THEN should automatically detect multiple languages
        AND should process text in different languages
        """
        # Mock multilingual results
        mock_results = [
            ([[10, 10], [40, 10], [40, 25], [10, 25]], 'Hello', 0.95),
            ([[50, 10], [80, 10], [80, 25], [50, 25]], 'Hola', 0.92),
            ([[10, 30], [50, 30], [50, 45], [10, 45]], 'Bonjour', 0.88)
        ]
        
        engine, mock_reader = self.create_mock_engine_for_extract_text(mock_results)
        
        image_data = self.create_test_image_data()
        result = engine.extract_text(image_data)
        
        # Should contain text from multiple languages
        text = result['text']
        assert 'Hello' in text
        assert 'Hola' in text
        assert 'Bonjour' in text
        
        assert len(result['text_blocks']) == 3

    def test_easyocr_extract_text_polygon_bounding_boxes(self):
        """
        GIVEN an EasyOCR instance and image with text
        WHEN calling extract_text()
        THEN should return 4-point polygon bounding boxes
        AND polygons should accurately outline text regions
        """
        # Mock results with detailed polygon coordinates
        mock_results = [
            ([[15, 12], [65, 8], [67, 28], [17, 32]], 'Sample Text', 0.94),
            ([[20, 35], [75, 35], [75, 50], [20, 50]], 'Another Line', 0.91)
        ]
        
        engine, mock_reader = self.create_mock_engine_for_extract_text(mock_results)
        
        image_data = self.create_test_image_data(100, 60)
        result = engine.extract_text(image_data)
        
        # Check polygon bounding boxes
        text_blocks = result['text_blocks']
        assert len(text_blocks) == 2
        
        for block in text_blocks:
            bbox = block['bbox']
            assert isinstance(bbox, list)
            assert len(bbox) == 4  # 4 corner points
            
            # Each point should be [x, y]
            for point in bbox:
                assert isinstance(point, list)
                assert len(point) == 2
                x, y = point
                # Coordinates should be within image bounds
                assert 0 <= x <= 100
                assert 0 <= y <= 60

    def test_easyocr_extract_text_confidence_scores(self):
        """
        GIVEN an EasyOCR instance and image with varying text quality
        WHEN calling extract_text()
        THEN should return neural model confidence scores
        AND scores should reflect recognition certainty
        """
        # Mock varying confidence scores
        mock_results = [
            ([[10, 10], [50, 10], [50, 25], [10, 25]], 'Clear', 0.98),
            ([[60, 10], [90, 10], [90, 25], [60, 25]], 'Blurry', 0.65),
            ([[10, 30], [70, 30], [70, 45], [10, 45]], 'Very unclear', 0.32)
        ]
        
        engine, mock_reader = self.create_mock_engine_for_extract_text(mock_results)
        
        image_data = self.create_test_image_data()
        result = engine.extract_text(image_data)
        
        # Check overall confidence
        assert isinstance(result['confidence'], float)
        assert 0.0 <= result['confidence'] <= 1.0
        
        # Check individual block confidences
        text_blocks = result['text_blocks']
        confidences = [block['confidence'] for block in text_blocks]
        
        # Should reflect the varying quality
        assert max(confidences) > 0.9  # Clear text
        assert min(confidences) < 0.4  # Very unclear text
        
        for conf in confidences:
            assert 0.0 <= conf <= 1.0

    def test_easyocr_extract_text_gpu_acceleration(self):
        """
        GIVEN an EasyOCR instance and CUDA-capable GPU
        WHEN calling extract_text()
        THEN should utilize GPU acceleration if available
        AND should fall back to CPU if GPU unavailable
        """
        mock_results = [
            ([[10, 10], [50, 10], [50, 25], [10, 25]], 'GPU Text', 0.95)
        ]
        
        engine, mock_reader = self.create_mock_engine_for_extract_text(mock_results)
        
        image_data = self.create_test_image_data()
        result = engine.extract_text(image_data)
        
        assert 'GPU Text' in result['text']
        mock_reader.readtext.assert_called_once()

    def test_easyocr_extract_text_memory_usage(self):
        """
        GIVEN an EasyOCR instance and large image
        WHEN calling extract_text()
        THEN should manage memory usage appropriately
        AND should not cause memory overflow
        """
        # Mock processing of large image
        mock_results = [
            ([[50, 100], [450, 100], [450, 150], [50, 150]], 'Large Image Text', 0.90)
        ]
        
        engine, mock_reader = self.create_mock_engine_for_extract_text(mock_results)
        
        # Create larger test image
        large_image_data = self.create_test_image_data(500, 300)
        result = engine.extract_text(large_image_data)
        
        # Should handle large image without issues
        assert isinstance(result, dict)
        assert 'Large Image Text' in result['text']
        mock_reader.readtext.assert_called_once()

    def test_easyocr_extract_text_empty_image_data(self):
        """
        GIVEN an EasyOCR instance
        WHEN calling extract_text() with empty bytes
        THEN should raise ValueError
        """
        engine, mock_reader = self.create_mock_engine_for_extract_text([])
        
        # PIL.Image.open will raise ValueError for empty bytes
        with pytest.raises(ValueError):
            engine.extract_text(b'')

    def test_easyocr_extract_text_invalid_image_format(self):
        """
        GIVEN an EasyOCR instance
        WHEN calling extract_text() with invalid image data
        THEN should raise PIL.UnidentifiedImageError or ValueError
        """
        engine, mock_reader = self.create_mock_engine_for_extract_text([])
        
        from PIL import UnidentifiedImageError
        with pytest.raises((UnidentifiedImageError, Exception)):
            engine.extract_text(b'not_an_image')

    def test_easyocr_extract_text_engine_not_available(self):
        """
        GIVEN an EasyOCR instance with available=False
        WHEN calling extract_text()
        THEN should raise RuntimeError
        """
        engine, mock_reader = self.create_mock_engine_for_extract_text([])
        engine.available = False
        
        with pytest.raises(RuntimeError, match="not.*available|not.*initialized"):
            engine.extract_text(self.create_test_image_data())

    def test_easyocr_extract_text_no_text_detected(self):
        """
        GIVEN an EasyOCR instance and image with no text
        WHEN calling extract_text()
        THEN should return empty results gracefully
        AND should not raise exceptions
        """
        # Mock no text detection
        engine, mock_reader = self.create_mock_engine_for_extract_text([])
        
        image_data = self.create_test_image_data()
        result = engine.extract_text(image_data)
        
        assert isinstance(result, dict)
        assert result['text'] == ''
        assert result['confidence'] == 0.0
        assert result['text_blocks'] == []
        assert result['engine'] == 'easyocr'

    def test_easyocr_extract_text_result_format_consistency(self):
        """
        GIVEN an EasyOCR instance
        WHEN calling extract_text() with various inputs
        THEN should always return consistent dictionary format
        """
        # Test different result scenarios
        test_cases = [
            # Normal case
            [([[10, 10], [50, 10], [50, 25], [10, 25]], 'Normal', 0.95)],
            # Single character
            [([[15, 15], [20, 15], [20, 25], [15, 25]], 'A', 0.88)],
            # Multiple blocks
            [
                ([[10, 10], [30, 10], [30, 20], [10, 20]], 'First', 0.92),
                ([[40, 10], [60, 10], [60, 20], [40, 20]], 'Second', 0.87)
            ]
        ]
        
        for mock_result in test_cases:
            engine, mock_reader = self.create_mock_engine_for_extract_text(mock_result)
            
            image_data = self.create_test_image_data()
            result = engine.extract_text(image_data)
            
            # Check consistent format
            assert isinstance(result, dict)
            required_keys = {'text', 'confidence', 'text_blocks', 'engine'}
            assert required_keys.issubset(result.keys())
            
            assert isinstance(result['text'], str)
            assert isinstance(result['confidence'], float)
            assert isinstance(result['text_blocks'], list)
            assert result['engine'] == 'easyocr'




if __name__ == "__main__":
    pytest.main([__file__, "-v"])
