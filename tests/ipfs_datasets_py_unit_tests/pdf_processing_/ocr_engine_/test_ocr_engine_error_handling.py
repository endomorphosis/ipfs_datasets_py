# Test file for TestOCREngineErrorHandling
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
from pydantic import BaseModel

import cv2
import torch
import pytesseract
from surya.recognition.schema import BaseChar

# NOTE These are already in the surya module, but we redefine them here for clarity.
class TextChar(BaseChar):
    bbox_valid: bool = True  # This is false when the given bbox is not valid


class TextWord(BaseChar):
    bbox_valid: bool = True


class TextLine(BaseChar):
    chars: List[TextChar]  # Individual characters in the line
    original_text_good: bool = False
    words: List[TextWord] | None = None


class OCRResult(BaseModel):
    text_lines: List[TextLine]
    image_bbox: List[float]


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





class TestOCREngineErrorHandling:
    """Test suite for error handling and edge cases across all engines."""

    def test_all_engines_handle_none_image_data(self):
        """
        GIVEN any OCR engine
        WHEN calling extract_text(None)
        THEN should raise TypeError
        """
        for engine in [SuryaOCR, EasyOCR, TesseractOCR, TrOCREngine]:
            with patch.object(engine, '_initialize'):
                ocr_engine = engine()
                ocr_engine.available = True
                
                with pytest.raises(TypeError):
                    ocr_engine.extract_text(None)

    def test_all_engines_handle_empty_bytes(self):
        """
        GIVEN any OCR engine
        WHEN calling extract_text(b'')
        THEN should raise ValueError
        """
        for engine in [SuryaOCR, EasyOCR, TesseractOCR, TrOCREngine]:
            with patch.object(engine, '_initialize'):
                ocr_engine = engine()
                ocr_engine.available = True
                
                with pytest.raises(ValueError):
                    ocr_engine.extract_text(b'')

    def test_all_engines_handle_non_image_data(self):
        """
        GIVEN any OCR engine
        WHEN calling extract_text() with non-image bytes (e.g., text file)
        THEN should raise PIL.UnidentifiedImageError or similar
        """
        # Create non-image data (text file content)
        text_data = b"This is not image data, just plain text content"
        
        # Test TesseractOCR
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            
            with pytest.raises((ValueError, Exception)):  # PIL.UnidentifiedImageError is subclass of Exception
                tesseract_engine.extract_text(text_data)
        
        # Test EasyOCR
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            
            with pytest.raises((ValueError, Exception)):
                easy_engine.extract_text(text_data)
        
        # Test SuryaOCR
        with patch.object(SuryaOCR, '_initialize'):
            surya_engine = SuryaOCR()
            surya_engine.available = True
            
            with pytest.raises((ValueError, Exception)):
                surya_engine.extract_text(text_data)
        
        # Test TrOCREngine
        with patch.object(TrOCREngine, '_initialize'):
            trocr_engine = TrOCREngine()
            trocr_engine.available = True
            
            with pytest.raises((ValueError, Exception)):
                trocr_engine.extract_text(text_data)

    def test_all_engines_handle_corrupted_image_data(self):
        """
        GIVEN any OCR engine
        WHEN calling extract_text() with corrupted image data
        THEN should raise appropriate exception
        AND should not crash the application
        """
        # Create corrupted image data (partial PNG header)
        corrupted_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00corrupted_data_here'
        
        # Test TesseractOCR
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            
            with pytest.raises((ValueError, Exception)):
                tesseract_engine.extract_text(corrupted_data)
        
        # Test EasyOCR
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            
            with pytest.raises((ValueError, Exception)):
                easy_engine.extract_text(corrupted_data)
        
        # Test SuryaOCR
        with patch.object(SuryaOCR, '_initialize'):
            surya_engine = SuryaOCR()
            surya_engine.available = True
            
            with pytest.raises((ValueError, Exception)):
                surya_engine.extract_text(corrupted_data)
        
        # Test TrOCREngine
        with patch.object(TrOCREngine, '_initialize'):
            trocr_engine = TrOCREngine()
            trocr_engine.available = True
            
            with pytest.raises((ValueError, Exception)):
                trocr_engine.extract_text(corrupted_data)


    def test_all_engines_handle_unsupported_image_format(self):
        """
        GIVEN any OCR engine
        WHEN calling extract_text() with unsupported image format
        THEN should raise PIL.UnidentifiedImageError or handle gracefully
        """
        # Create fake unsupported format data
        unsupported_data = b"FAKE_FORMAT_HEADER" + b"not_real_image_data" * 100
        
        # Test TesseractOCR
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            
            with pytest.raises((ValueError, Exception)):
                tesseract_engine.extract_text(unsupported_data)
        
        # Test EasyOCR
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            
            with pytest.raises((ValueError, Exception)):
                easy_engine.extract_text(unsupported_data)
        
        # Test SuryaOCR
        with patch.object(SuryaOCR, '_initialize'):
            surya_engine = SuryaOCR()
            surya_engine.available = True
            
            with pytest.raises((ValueError, Exception)):
                surya_engine.extract_text(unsupported_data)
        
        # Test TrOCREngine
        with patch.object(TrOCREngine, '_initialize'):
            trocr_engine = TrOCREngine()
            trocr_engine.available = True
            
            with pytest.raises((ValueError, Exception)):
                trocr_engine.extract_text(unsupported_data)

    def test_all_engines_handle_extremely_large_images(self):
        """
        GIVEN any OCR engine
        WHEN calling extract_text() with extremely large image
        THEN should handle memory constraints appropriately
        AND should not cause system instability
        """
        def create_large_image_data(width=5000, height=5000):
            """Helper to create large image data."""
            img = Image.new('RGB', (width, height), color='white')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        
        large_image_data = create_large_image_data()
        
        # Test TesseractOCR
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            tesseract_engine.pytesseract = Mock()
            
            # Mock preprocessing to avoid actual large image processing
            with patch.object(tesseract_engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = Image.new('RGB', (100, 50), 'white')
                tesseract_engine.pytesseract.image_to_string.return_value = "Large image text"
                tesseract_engine.pytesseract.image_to_data.return_value = {
                    'text': ['Large', 'image', 'text'],
                    'conf': [95, 92, 88],
                    'left': [10, 60, 150],
                    'top': [10, 10, 10],
                    'width': [45, 75, 40],
                    'height': [20, 20, 20]
                }
                
                # Should handle large image without crashing
                result = tesseract_engine.extract_text(large_image_data)
                assert isinstance(result, dict)
                assert 'text' in result
        
        # Test EasyOCR (with memory management)
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            easy_engine.reader = Mock()
            
            # Mock successful processing with memory awareness
            easy_engine.reader.readtext.return_value = [
                ([[10, 10], [90, 10], [90, 30], [10, 30]], 'Large image content', 0.85)
            ]
            
            # Should handle gracefully or raise appropriate memory-related exception
            try:
                result = easy_engine.extract_text(large_image_data)
                assert isinstance(result, dict)
            except (MemoryError, RuntimeError) as e:
                # Acceptable to fail with memory-related error
                assert "memory" in str(e).lower() or "resource" in str(e).lower()

    def test_all_engines_handle_extremely_small_images(self):
        """
        GIVEN any OCR engine
        WHEN calling extract_text() with tiny image (e.g., 1x1 pixel)
        THEN should handle gracefully
        AND should return appropriate empty or error result
        """
        def create_tiny_image_data():
            """Helper to create 1x1 pixel image."""
            img = Image.new('RGB', (1, 1), color='white')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        
        tiny_image_data = create_tiny_image_data()
        
        # Test TesseractOCR
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            tesseract_engine.pytesseract = Mock()
            
            with patch.object(tesseract_engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = Image.new('RGB', (1, 1), 'white')
                tesseract_engine.pytesseract.image_to_string.return_value = ""
                tesseract_engine.pytesseract.image_to_data.return_value = {
                    'text': [''], 'conf': [0], 'left': [0], 'top': [0], 
                    'width': [1], 'height': [1]
                }
                
                result = tesseract_engine.extract_text(tiny_image_data)
                assert isinstance(result, dict)
                assert result['text'] == ""
                assert 'confidence' in result
        
        # Test EasyOCR
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            easy_engine.reader = Mock()
            easy_engine.reader.readtext.return_value = []  # No text found
            
            result = easy_engine.extract_text(tiny_image_data)
            assert isinstance(result, dict)
            assert result['text'] == ""
            assert 'confidence' in result

    def test_all_engines_handle_images_without_text(self):
        """
        GIVEN any OCR engine
        WHEN calling extract_text() with image containing no text
        THEN should return empty text with appropriate confidence
        AND should not raise exceptions
        """
        def create_no_text_image_data():
            """Helper to create image with no text (just shapes/colors)."""
            img = Image.new('RGB', (100, 50), color='white')
            # Add some non-text elements (colored rectangles)
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.rectangle([10, 10, 30, 30], fill='red')
            draw.ellipse([60, 15, 85, 35], fill='blue')
            
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        
        no_text_image_data = create_no_text_image_data()
        
        # Test TesseractOCR
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            tesseract_engine.pytesseract = Mock()
            
            with patch.object(tesseract_engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = Image.new('RGB', (100, 50), 'white')
                tesseract_engine.pytesseract.image_to_string.return_value = ""
                tesseract_engine.pytesseract.image_to_data.return_value = {
                    'text': [''], 'conf': [0], 'left': [0], 'top': [0], 
                    'width': [100], 'height': [50]
                }
                
                result = tesseract_engine.extract_text(no_text_image_data)
                assert isinstance(result, dict)
                assert result['text'] == ""
                assert 'confidence' in result
        
        # Test EasyOCR
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            easy_engine.reader = Mock()
            easy_engine.reader.readtext.return_value = []  # No text detected
            
            result = easy_engine.extract_text(no_text_image_data)
            assert isinstance(result, dict)
            assert result['text'] == ""
            assert 'confidence' in result
        
        from surya.recognition.schema import OCRResult

        # Test SuryaOCR
        with patch.object(SuryaOCR, '_initialize'):
            surya_engine = SuryaOCR()
            surya_engine.available = True
            surya_engine.detection_predictor = Mock()
            surya_engine.recognition_predictor = Mock(spec=OCRResult)
            surya_engine.recognition_predictor.return_value = ([], ["en"])  # No text lines found
            
            result = surya_engine.extract_text(no_text_image_data)
            assert isinstance(result, dict)
            assert result['text'] == ""
            assert 'confidence' in result

    def test_all_engines_handle_low_contrast_images(self):
        """
        GIVEN any OCR engine
        WHEN calling extract_text() with very low contrast image
        THEN should attempt extraction but may return low confidence
        AND should not crash or hang
        """
        def create_low_contrast_image_data():
            """Helper to create low contrast image with barely visible text."""
            img = Image.new('RGB', (200, 100), color=(200, 200, 200))  # Light gray background
            from PIL import ImageDraw, ImageFont
            draw = ImageDraw.Draw(img)
            # Very low contrast text (slightly darker gray on light gray)
            draw.text((10, 40), "Low Contrast Text", fill=(180, 180, 180))
            
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        
        low_contrast_image_data = create_low_contrast_image_data()
        
        # Test TesseractOCR
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            tesseract_engine.pytesseract = Mock()
            
            with patch.object(tesseract_engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = Image.new('RGB', (200, 100), 'white')
                # Mock low confidence result
                tesseract_engine.pytesseract.image_to_string.return_value = "Low Contrast Text"
                tesseract_engine.pytesseract.image_to_data.return_value = {
                    'text': ['Low', 'Contrast', 'Text'], 'conf': [45, 42, 48], 
                    'left': [10, 50, 120], 'top': [40, 40, 40], 
                    'width': [35, 65, 30], 'height': [20, 20, 20]
                }
                
                result = tesseract_engine.extract_text(low_contrast_image_data)
                assert isinstance(result, dict)
                assert 'confidence' in result
                # Should complete without hanging or crashing
                assert isinstance(result['confidence'], (int, float))
        
        # Test EasyOCR
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            easy_engine.reader = Mock()
            # Mock low confidence detection
            easy_engine.reader.readtext.return_value = [
                ([[10, 40], [180, 40], [180, 60], [10, 60]], 'Low Contrast Text', 0.45)
            ]
            
            result = easy_engine.extract_text(low_contrast_image_data)
            assert isinstance(result, dict)
            assert 'confidence' in result
            assert result['confidence'] <= 0.6  # Should reflect low confidence

    def test_all_engines_handle_high_noise_images(self):
        """
        GIVEN any OCR engine
        WHEN calling extract_text() with very noisy image
        THEN should attempt extraction despite noise
        AND should apply appropriate preprocessing if available
        """
        def create_noisy_image_data():
            """Helper to create image with high noise level."""
            import random
            img = Image.new('RGB', (200, 100), color='white')
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            
            # Add text first
            draw.text((50, 40), "Noisy Text", fill='black')
            
            # Add random noise pixels
            pixels = img.load()
            for _ in range(2000):  # Add 2000 random noise pixels
                x = random.randint(0, 199)
                y = random.randint(0, 99)
                noise_color = random.randint(0, 255)
                pixels[x, y] = (noise_color, noise_color, noise_color)
            
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        
        noisy_image_data = create_noisy_image_data()
        
        # Test TesseractOCR (should apply preprocessing)
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            tesseract_engine.pytesseract = Mock()
            
            with patch.object(tesseract_engine, '_preprocess_image') as mock_preprocess:
                # Mock preprocessing that cleans up noise
                mock_preprocess.return_value = Image.new('RGB', (200, 100), 'white')
                tesseract_engine.pytesseract.image_to_string.return_value = "Noisy Text"
                tesseract_engine.pytesseract.image_to_data.return_value = {
                    'text': ['Noisy', 'Text'], 'conf': [78, 82], 
                    'left': [50, 100], 'top': [40, 40], 
                    'width': [45, 35], 'height': [20, 20]
                }
                
                result = tesseract_engine.extract_text(noisy_image_data)
                assert isinstance(result, dict)
                # Should have called preprocessing
                mock_preprocess.assert_called_once()
                assert 'Text' in result['text']
        
        # Test EasyOCR (should handle noise robustly)
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            easy_engine.reader = Mock()
            # Mock detection despite noise
            easy_engine.reader.readtext.return_value = [
                ([[50, 40], [150, 40], [150, 60], [50, 60]], 'Noisy Text', 0.72)
            ]
            
            result = easy_engine.extract_text(noisy_image_data)
            assert isinstance(result, dict)
            assert 'Text' in result['text']
            assert result['confidence'] > 0.5  # Should still extract despite noise



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
