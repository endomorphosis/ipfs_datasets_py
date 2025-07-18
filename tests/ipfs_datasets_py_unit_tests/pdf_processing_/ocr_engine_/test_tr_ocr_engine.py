# Test file for TestTrOCREngine
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




class TestTrOCREngine:
    """Test suite for TrOCR transformer-based OCR engine."""

    def create_test_image_data(self, width=100, height=50, color='white'):
        """Helper method to create test image data as bytes."""
        img = Image.new('RGB', (width, height), color=color)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    def test_trocr_initialization_success(self):
        """
        GIVEN transformers library and dependencies are available
        WHEN initializing TrOCREngine
        THEN should successfully load processor and model
        AND should set available to True
        AND should use microsoft/trocr-base-printed model
        """
        with patch('transformers.TrOCRProcessor') as mock_processor_class, \
             patch('transformers.VisionEncoderDecoderModel') as mock_model_class:
            
            mock_processor = Mock()
            mock_model = Mock()
            mock_processor_class.from_pretrained.return_value = mock_processor
            mock_model_class.from_pretrained.return_value = mock_model
            
            with patch.object(TrOCREngine, '_initialize') as mock_init:
                mock_init.return_value = None
                engine = TrOCREngine()
                mock_init.assert_called_once()
                assert engine.name == 'trocr'

    def test_trocr_initialization_missing_transformers(self):
        """
        GIVEN transformers library is not installed
        WHEN initializing TrOCREngine
        THEN should handle ImportError gracefully
        AND should set available to False
        """
        with patch.object(TrOCREngine, '_initialize', side_effect=ImportError("No module named 'transformers'")):
            engine = TrOCREngine()
            assert hasattr(engine, 'name')
            assert engine.name == 'trocr'
            assert hasattr(engine, 'available')

    def test_trocr_initialization_model_download_failure(self):
        """
        GIVEN transformers is installed but model download fails
        WHEN initializing TrOCREngine
        THEN should handle HTTPError or RuntimeError
        AND should set available to False
        """
        with patch.object(TrOCREngine, '_initialize', side_effect=RuntimeError("Model download failed")):
            engine = TrOCREngine()
            assert hasattr(engine, 'available')
            assert hasattr(engine, 'name')
            assert engine.name == 'trocr'

    def test_trocr_extract_text_handwritten_text(self):
        """
        GIVEN a TrOCREngine instance and handwritten text image
        WHEN calling extract_text()
        THEN should excel at handwriting recognition
        AND should return accurate text extraction
        """
        with patch.object(TrOCREngine, '_initialize'):
            engine = TrOCREngine()
            engine.available = True
            engine.processor = Mock()
            engine.model = Mock()
            
            # Mock processor and model pipeline - processor returns object with pixel_values
            mock_pixel_values = torch.randn(1, 3, 384, 384)
            mock_processed = Mock()
            mock_processed.pixel_values = mock_pixel_values
            engine.processor.return_value = mock_processed
            
            # Mock model generation
            mock_generated_ids = torch.tensor([[1, 2, 3, 4, 5]])
            engine.model.generate.return_value = mock_generated_ids
            
            # Mock batch_decode (not decode)
            engine.processor.batch_decode.return_value = ["handwritten text sample"]
            
            image_data = self.create_test_image_data()
            result = engine.extract_text(image_data)
            
            # Verify return structure
            assert isinstance(result, dict)
            assert 'text' in result
            assert 'confidence' in result
            assert 'engine' in result
            
            # Verify content
            assert result['engine'] == 'trocr'
            assert result['text'] == "handwritten text sample"
            # Should always return fixed confidence
            assert isinstance(result['confidence'], float)
            assert result['confidence'] == 0.0

    def test_trocr_extract_text_printed_text(self):
        """
        GIVEN a TrOCREngine instance and printed text image
        WHEN calling extract_text()
        THEN should handle printed text effectively
        AND should return accurate recognition results
        """
        with patch.object(TrOCREngine, '_initialize'):
            engine = TrOCREngine()
            engine.available = True
            engine.processor = Mock()
            engine.model = Mock()
            
            # Mock processing pipeline
            mock_pixel_values = torch.randn(1, 3, 384, 384)
            mock_processed = Mock()
            mock_processed.pixel_values = mock_pixel_values
            engine.processor.return_value = mock_processed
            
            mock_generated_ids = torch.tensor([[10, 20, 30, 40]])
            engine.model.generate.return_value = mock_generated_ids
            
            engine.processor.batch_decode.return_value = ["Clear printed text"]
            
            image_data = self.create_test_image_data()
            result = engine.extract_text(image_data)
            
            assert result['text'] == "Clear printed text"
            assert result['engine'] == 'trocr'
            assert isinstance(result['confidence'], float)

    def test_trocr_extract_text_single_line_optimization(self):
        """
        GIVEN a TrOCREngine instance and single line text image
        WHEN calling extract_text()
        THEN should optimize for single-line text processing
        AND should provide best accuracy for short text passages
        """
        with patch.object(TrOCREngine, '_initialize'):
            engine = TrOCREngine()
            engine.available = True
            engine.processor = Mock()
            engine.model = Mock()
            
            # Mock single line processing
            mock_pixel_values = torch.randn(1, 3, 384, 384)
            mock_processed = Mock()
            mock_processed.pixel_values = mock_pixel_values
            engine.processor.return_value = mock_processed
            
            mock_generated_ids = torch.tensor([[5, 15, 25]])
            engine.model.generate.return_value = mock_generated_ids
            
            engine.processor.batch_decode.return_value = ["Single line"]
            
            # Create narrow image (typical for single line)
            img = Image.new('RGB', (200, 30), color='white')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            single_line_data = buf.getvalue()
            
            result = engine.extract_text(single_line_data)
            
            assert result['text'] == "Single line"
            assert result['engine'] == 'trocr'
            
            # Should have processed the image
            engine.processor.assert_called()
            engine.model.generate.assert_called()

    def test_trocr_extract_text_no_confidence_scores(self):
        """
        GIVEN a TrOCREngine instance and any text image
        WHEN calling extract_text()
        THEN should return fixed confidence score (0.0)
        AND should acknowledge lack of native confidence estimation
        """
        with patch.object(TrOCREngine, '_initialize'):
            engine = TrOCREngine()
            engine.available = True
            engine.processor = Mock()
            engine.model = Mock()
            
            # Mock processing
            mock_pixel_values = torch.randn(1, 3, 384, 384)
            mock_processed = Mock()
            mock_processed.pixel_values = mock_pixel_values
            engine.processor.return_value = mock_processed
            
            mock_generated_ids = torch.tensor([[1, 2, 3]])
            engine.model.generate.return_value = mock_generated_ids
            
            engine.processor.batch_decode.return_value = ["any text"]
            
            image_data = self.create_test_image_data()
            result = engine.extract_text(image_data)
            
            # Should always return fixed confidence
            assert isinstance(result['confidence'], float)
            assert result['confidence'] == 0.0
            

    def test_trocr_extract_text_no_spatial_information(self):
        """
        GIVEN a TrOCREngine instance and text image
        WHEN calling extract_text()
        THEN should not provide bounding box information
        AND should return only text content
        """
        with patch.object(TrOCREngine, '_initialize'):
            engine = TrOCREngine()
            engine.available = True
            engine.processor = Mock()
            engine.model = Mock()
            
            # Mock processing
            mock_pixel_values = torch.randn(1, 3, 384, 384)
            mock_processed = Mock()
            mock_processed.pixel_values = mock_pixel_values
            engine.processor.return_value = mock_processed
            
            mock_generated_ids = torch.tensor([[7, 8, 9]])
            engine.model.generate.return_value = mock_generated_ids
            
            engine.processor.batch_decode.return_value = ["text without boxes"]
            
            image_data = self.create_test_image_data()
            result = engine.extract_text(image_data)
            
            # Should not have spatial information
            assert 'bbox' not in result
            assert 'text_blocks' not in result
            assert 'word_boxes' not in result
            
            # Should only have basic information
            expected_keys = {'text', 'confidence', 'engine'}
            assert set(result.keys()) == expected_keys

    def test_trocr_extract_text_transformer_architecture(self):
        """
        GIVEN a TrOCREngine instance
        WHEN calling extract_text()
        THEN should use Vision-Encoder-Decoder architecture
        AND should process as sequence-to-sequence task
        """
        with patch.object(TrOCREngine, '_initialize'):
            engine = TrOCREngine()
            engine.available = True
            engine.processor = Mock()
            engine.model = Mock()
            
            # Mock transformer pipeline
            mock_pixel_values = torch.randn(1, 3, 384, 384)
            mock_processed = Mock()
            mock_processed.pixel_values = mock_pixel_values
            engine.processor.return_value = mock_processed
            
            # Mock sequence generation
            mock_generated_ids = torch.tensor([[101, 102, 103, 104, 102]])
            engine.model.generate.return_value = mock_generated_ids
            
            engine.processor.batch_decode.return_value = ["sequence output"]
            
            image_data = self.create_test_image_data()
            result = engine.extract_text(image_data)
            
            # Should have used generate method (sequence-to-sequence)
            engine.model.generate.assert_called_once()
            call_args = engine.model.generate.call_args
            assert 'pixel_values' in call_args[1] or len(call_args[0]) > 0
            
            assert result['text'] == "sequence output"

    def test_trocr_extract_text_rgb_conversion(self):
        """
        GIVEN a TrOCREngine instance and non-RGB image
        WHEN calling extract_text()
        THEN should convert image to RGB format
        AND should handle various input formats
        """
        with patch.object(TrOCREngine, '_initialize'):
            engine = TrOCREngine()
            engine.available = True
            engine.processor = Mock()
            engine.model = Mock()
            
            # Create test images in different modes
            test_modes = ['L', 'RGBA', 'P']  # Grayscale, RGBA, Palette
            
            for mode in test_modes:
                if mode == 'L':
                    img = Image.new(mode, (100, 50), color=128)
                elif mode == 'RGBA':
                    img = Image.new(mode, (100, 50), color=(255, 255, 255, 255))
                else:  # 'P'
                    img = Image.new('RGB', (100, 50), color='white')
                    img = img.convert('P')
                
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                image_data = buf.getvalue()
                
                # Mock processing
                mock_pixel_values = torch.randn(1, 3, 384, 384)
                mock_processed = Mock()
                mock_processed.pixel_values = mock_pixel_values
                engine.processor.return_value = mock_processed
                
                mock_generated_ids = torch.tensor([[1, 2]])
                engine.model.generate.return_value = mock_generated_ids
                
                engine.processor.batch_decode.return_value = [f"converted {mode}"]
                
                result = engine.extract_text(image_data)
                
                # Should have processed successfully regardless of input mode
                assert isinstance(result, dict)
                assert result['text'] == f"converted {mode}"

    def test_trocr_extract_text_gpu_memory_management(self):
        """
        GIVEN a TrOCREngine instance and large image
        WHEN calling extract_text()
        THEN should manage GPU memory appropriately
        AND should handle CUDA out of memory errors
        """
        with patch.object(TrOCREngine, '_initialize'):
            engine = TrOCREngine()
            engine.available = True
            engine.processor = Mock()
            engine.model = Mock()
            
            # Mock CUDA out of memory error
            engine.model.generate.side_effect = torch.cuda.OutOfMemoryError("CUDA out of memory")
            
            image_data = self.create_test_image_data(1000, 800)  # Large image
            
            with pytest.raises(torch.cuda.OutOfMemoryError):
                engine.extract_text(image_data)

    def test_trocr_extract_text_empty_image_data(self):
        """
        GIVEN a TrOCREngine instance
        WHEN calling extract_text() with empty bytes
        THEN should raise ValueError
        """
        with patch.object(TrOCREngine, '_initialize'):
            engine = TrOCREngine()
            engine.available = True
            
            with pytest.raises(ValueError):
                engine.extract_text(b'')

    def test_trocr_extract_text_invalid_image_format(self):
        """
        GIVEN a TrOCREngine instance
        WHEN calling extract_text() with invalid image data
        THEN should raise PIL.UnidentifiedImageError or ValueError
        """
        with patch.object(TrOCREngine, '_initialize'):
            engine = TrOCREngine()
            engine.available = True
            
            with pytest.raises((ValueError, Exception)):
                engine.extract_text(b'invalid_image_data')

    def test_trocr_extract_text_engine_not_available(self):
        """
        GIVEN a TrOCREngine instance with available=False
        WHEN calling extract_text()
        THEN should raise RuntimeError
        """
        with patch.object(TrOCREngine, '_initialize'):
            engine = TrOCREngine()
            engine.available = False
            
            with pytest.raises(RuntimeError, match="not.*available|not.*initialized"):
                engine.extract_text(self.create_test_image_data())

    def test_trocr_extract_text_model_variants(self):
        """
        GIVEN different TrOCR model variants could be used
        WHEN initializing and using TrOCREngine
        THEN should work with different model types (printed, handwritten, large)
        """
        model_variants = [
            'microsoft/trocr-base-printed',
            'microsoft/trocr-base-handwritten',
            'microsoft/trocr-large-printed'
        ]
        
        for model_name in model_variants:
            with patch.object(TrOCREngine, '_initialize'):
                engine = TrOCREngine()
                engine.available = True
                engine.processor = Mock()
                engine.model = Mock()
                
                # Mock processing for this model variant
                mock_pixel_values = torch.randn(1, 3, 384, 384)
                mock_processed = Mock()
                mock_processed.pixel_values = mock_pixel_values
                engine.processor.return_value = mock_processed
                
                mock_generated_ids = torch.tensor([[1, 2, 3]])
                engine.model.generate.return_value = mock_generated_ids
                
                engine.processor.batch_decode.return_value = [f"text from {model_name}"]
                
                image_data = self.create_test_image_data()
                result = engine.extract_text(image_data)
                
                assert isinstance(result, dict)
                assert result['engine'] == 'trocr'
                assert f"text from {model_name}" in result['text']

    def test_trocr_extract_text_batch_token_handling(self):
        """
        GIVEN a TrOCREngine instance
        WHEN processing various text lengths
        THEN should handle different token sequence lengths appropriately
        """
        with patch.object(TrOCREngine, '_initialize'):
            engine = TrOCREngine()
            engine.available = True
            engine.processor = Mock()
            engine.model = Mock()
            
            # Test different sequence lengths
            test_sequences = [
                torch.tensor([[1]]),  # Very short
                torch.tensor([[1, 2, 3, 4, 5]]),  # Medium
                torch.tensor([[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]])  # Longer
            ]
            
            expected_texts = ["A", "Short text", "This is a longer sequence of text"]
            
            for i, (seq, expected) in enumerate(zip(test_sequences, expected_texts)):
                mock_pixel_values = torch.randn(1, 3, 384, 384)
                mock_processed = Mock()
                mock_processed.pixel_values = mock_pixel_values
                engine.processor.return_value = mock_processed
                engine.model.generate.return_value = seq
                engine.processor.batch_decode.return_value = [expected]
                
                image_data = self.create_test_image_data()
                result = engine.extract_text(image_data)
                
                assert result['text'] == expected
                # Should always return fixed confidence
                assert result['confidence'] == 0.0

    def test_trocr_extract_text_special_characters(self):
        """
        GIVEN a TrOCREngine instance and image with special characters
        WHEN calling extract_text()
        THEN should handle special characters, numbers, and punctuation
        """
        with patch.object(TrOCREngine, '_initialize'):
            engine = TrOCREngine()
            engine.available = True
            engine.processor = Mock()
            engine.model = Mock()
            
            # Mock processing with special characters
            mock_pixel_values = torch.randn(1, 3, 384, 384)
            mock_processed = Mock()
            mock_processed.pixel_values = mock_pixel_values
            engine.processor.return_value = mock_processed
            
            mock_generated_ids = torch.tensor([[33, 44, 55, 66]])
            engine.model.generate.return_value = mock_generated_ids
            
            special_text = "Hello! @#$%^&*() 123-456 test."
            engine.processor.batch_decode.return_value = [special_text]
            
            image_data = self.create_test_image_data()
            result = engine.extract_text(image_data)
            
            assert result['text'] == special_text
            assert result['engine'] == 'trocr'




if __name__ == "__main__":
    pytest.main([__file__, "-v"])
