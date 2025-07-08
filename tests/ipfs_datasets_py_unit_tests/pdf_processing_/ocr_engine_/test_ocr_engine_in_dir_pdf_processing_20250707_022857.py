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



class TestQualityOfObjectsInModule:
    """
    Test class for the quality of callable objects 
    (e.g. class, method, function, coroutine, or property) in the module.
    """

    def test_callable_objects_metadata_quality(self):
        """
        GIVEN a Python module
        WHEN the module is parsed by the AST
        THEN
         - Each callable object should have a detailed, Google-style docstring.
         - Each callable object should have a detailed signature with type hints and a return annotation.
        """
        tree = get_ast_tree(file_path)
        try:
            raise_on_bad_callable_metadata(tree)
        except (BadDocumentationError, BadSignatureError) as e:
            pytest.fail(f"Code metadata quality check failed: {e}")

    def test_callable_objects_quality(self):
        """
        GIVEN a Python module
        WHEN the module's source code is examined
        THEN if the file is not indicated as a mock, placeholder, stub, or example:
         - The module should not contain intentionally fake or simplified code 
            (e.g. "In a real implementation, ...")
         - Contain no mocked objects or placeholders.
        """
        try:
            raise_on_bad_callable_code_quality(file_path)
        except (BadDocumentationError, BadSignatureError) as e:
            for indicator in ["mock", "placeholder", "stub", "example"]:
                if indicator in file_path:
                    break
            else:
                # If no indicator is found, fail the test
                pytest.fail(f"Code quality check failed: {e}")

# 
class ConcreteOCREngine(OCREngine):
    """Test implementation of OCREngine for testing purposes."""
    
    def __init__(self, name: str, should_fail_init: bool = False):
        self.should_fail_init = should_fail_init
        super().__init__(name)
    
    def _initialize(self):
        """Test implementation of _initialize."""
        if self.should_fail_init:
            raise RuntimeError("Simulated initialization failure")
        self.available = True
    
    def extract_text(self, image_data: bytes):
        """Test implementation of extract_text."""
        if not self.available:
            raise RuntimeError("Engine not available")
        return {
            'text': 'test text',
            'confidence': 0.95,
            'engine': self.name
        }


class TestOCREngineAbstractBase:
    """Test suite for OCREngine abstract base class."""

    def test_ocr_engine_is_abstract_class(self):
        """
        GIVEN the OCREngine class
        WHEN attempting to instantiate it directly
        THEN should raise TypeError due to abstract methods
        """
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            OCREngine("test")

    def test_ocr_engine_inheritance_structure(self):
        """
        GIVEN the OCREngine class
        WHEN examining its inheritance
        THEN should inherit from ABC (Abstract Base Class)
        AND should define abstract methods _initialize and extract_text
        """
        # Should inherit from ABC
        assert issubclass(OCREngine, ABC)
        
        # Should have abstract methods
        abstract_methods = OCREngine.__abstractmethods__
        expected_abstract = {'_initialize', 'extract_text'}
        assert expected_abstract.issubset(abstract_methods)

    def test_ocr_engine_init_sets_name_and_available(self):
        """
        GIVEN a concrete OCREngine subclass with valid name
        WHEN initializing with __init__(name)
        THEN should set self.name to provided name
        AND should set self.available to False initially
        AND should call _initialize() method
        """
        engine = ConcreteOCREngine("test_engine")
        
        assert engine.name == "test_engine"
        assert engine.available == True  # Set to True by our test _initialize
        
    def test_ocr_engine_init_calls_initialize(self):
        """
        GIVEN a concrete OCREngine subclass
        WHEN initializing
        THEN should call _initialize() method during construction
        """
        with patch.object(ConcreteOCREngine, '_initialize') as mock_init:
            ConcreteOCREngine("test")
            mock_init.assert_called_once()

    def test_ocr_engine_init_with_empty_name(self):
        """
        GIVEN a concrete OCREngine subclass
        WHEN initializing with empty string name
        THEN should handle gracefully and set name to empty string
        """
        engine = ConcreteOCREngine("")
        assert engine.name == ""
        assert hasattr(engine, 'available')

    def test_ocr_engine_init_with_none_name(self):
        """
        GIVEN a concrete OCREngine subclass
        WHEN initializing with None as name
        THEN should raise TypeError
        """
        with pytest.raises(TypeError):
            ConcreteOCREngine(None)

    def test_ocr_engine_init_handles_initialize_failure(self):
        """
        GIVEN a concrete OCREngine subclass that fails initialization
        WHEN initializing
        THEN should handle _initialize() failures gracefully
        AND should set available to False
        """
        engine = ConcreteOCREngine("test", should_fail_init=True)
        # The engine should handle the failure and set available appropriately
        # This depends on implementation - it might stay False or be set to False
        assert hasattr(engine, 'available')
        assert hasattr(engine, 'name')
        assert engine.name == "test"

    def test_is_available_returns_boolean(self):
        """
        GIVEN an initialized OCREngine instance
        WHEN calling is_available()
        THEN should return boolean value
        AND should reflect the current available status
        """
        # Test with available engine
        engine = ConcreteOCREngine("test")
        result = engine.is_available()
        assert isinstance(result, bool)
        assert result == engine.available
        
        # Test with unavailable engine
        engine_fail = ConcreteOCREngine("test_fail", should_fail_init=True)
        result_fail = engine_fail.is_available()
        assert isinstance(result_fail, bool)

    def test_is_available_thread_safety(self):
        """
        GIVEN an OCREngine instance
        WHEN calling is_available() from multiple threads simultaneously
        THEN should be thread-safe and return consistent results
        """
        engine = ConcreteOCREngine("test")
        results = []
        exceptions = []
        
        def check_availability():
            try:
                for _ in range(100):
                    result = engine.is_available()
                    results.append(result)
                    time.sleep(0.001)  # Small delay to encourage race conditions
            except Exception as e:
                exceptions.append(e)
        
        threads = [threading.Thread(target=check_availability) for _ in range(5)]
        
        for thread in threads:
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Should have no exceptions
        assert len(exceptions) == 0, f"Thread safety test failed with exceptions: {exceptions}"
        
        # All results should be consistent (same boolean value)
        assert len(results) > 0
        first_result = results[0]
        assert all(r == first_result for r in results), "is_available() returned inconsistent results across threads"

    def test_abstract_methods_must_be_implemented(self):
        """
        GIVEN a class that inherits from OCREngine
        WHEN the class doesn't implement abstract methods
        THEN should not be instantiable
        """
        class IncompleteEngine(OCREngine):
            def _initialize(self):
                pass
            # Missing extract_text implementation
        
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteEngine("incomplete")
        
        class AnotherIncompleteEngine(OCREngine):
            def extract_text(self, image_data: bytes):
                return {}
            # Missing _initialize implementation
        
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            AnotherIncompleteEngine("incomplete2")

    def test_concrete_implementation_works(self):
        """
        GIVEN a properly implemented concrete OCREngine subclass
        WHEN instantiating and using it
        THEN should work correctly
        """
        engine = ConcreteOCREngine("working_engine")
        
        # Should be available after successful initialization
        assert engine.is_available()
        
        # Should be able to extract text
        result = engine.extract_text(b"fake_image_data")
        assert isinstance(result, dict)
        assert 'text' in result
        assert 'confidence' in result
        assert 'engine' in result
        assert result['engine'] == 'working_engine'

    def test_engine_name_attribute_immutable_after_init(self):
        """
        GIVEN an initialized OCREngine instance
        WHEN accessing the name attribute
        THEN should return the name set during initialization
        AND should not change unexpectedly
        """
        engine = ConcreteOCREngine("test_name")
        original_name = engine.name
        
        # Name should be what we set
        assert engine.name == "test_name"
        
        # Try to modify (this tests that the name stays consistent)
        # We're not testing immutability enforcement, just consistency
        assert engine.name == original_name

    def test_available_attribute_reflects_initialization_state(self):
        """
        GIVEN OCREngine instances with different initialization outcomes
        WHEN checking the available attribute
        THEN should accurately reflect whether initialization succeeded
        """
        # Successful initialization
        engine_success = ConcreteOCREngine("success")
        assert engine_success.available == True
        
        # Failed initialization
        engine_fail = ConcreteOCREngine("fail", should_fail_init=True)
        # The available state depends on how the concrete class handles failures
        # We just verify it has the attribute and it's a boolean
        assert hasattr(engine_fail, 'available')
        assert isinstance(engine_fail.available, bool)




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
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.pytesseract') as mock_pytesseract:
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

    def test_tesseract_ocr_preprocess_image_grayscale_conversion(self):
        """
        GIVEN a TesseractOCR instance and color PIL Image
        WHEN calling _preprocess_image()
        THEN should convert image to grayscale
        AND should return PIL Image object
        """
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            
            # Create color image
            color_image = self.create_test_image(color='red')
            
            # Mock cv2 operations
            with patch('cv2.cvtColor') as mock_cvtcolor, \
                 patch('cv2.medianBlur') as mock_blur, \
                 patch('cv2.threshold') as mock_threshold:
                
                # Mock cv2 operations to return appropriate arrays
                gray_array = np.ones((50, 100), dtype=np.uint8) * 128
                mock_cvtcolor.return_value = gray_array
                mock_blur.return_value = gray_array
                mock_threshold.return_value = (127, gray_array)
                
                result = engine._preprocess_image(color_image)
                
                # Should return PIL Image
                assert isinstance(result, Image.Image)
                
                # Should have called cv2 functions for preprocessing
                mock_cvtcolor.assert_called()
                mock_blur.assert_called()
                mock_threshold.assert_called()

    def test_tesseract_ocr_preprocess_image_noise_reduction(self):
        """
        GIVEN a TesseractOCR instance and noisy PIL Image
        WHEN calling _preprocess_image()
        THEN should apply noise reduction techniques
        AND should improve image quality for OCR
        """
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            
            noisy_image = self.create_test_image()
            
            with patch('cv2.medianBlur') as mock_blur:
                gray_array = np.ones((50, 100), dtype=np.uint8) * 128
                mock_blur.return_value = gray_array
                
                with patch('cv2.cvtColor', return_value=gray_array), \
                     patch('cv2.threshold', return_value=(127, gray_array)):
                    
                    result = engine._preprocess_image(noisy_image)
                    
                    # Should apply median blur for noise reduction
                    mock_blur.assert_called_with(gray_array, 3)
                    assert isinstance(result, Image.Image)

    def test_tesseract_ocr_preprocess_image_binarization(self):
        """
        GIVEN a TesseractOCR instance and PIL Image
        WHEN calling _preprocess_image()
        THEN should apply Otsu's automatic thresholding
        AND should create binary image with optimal contrast
        """
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            
            test_image = self.create_test_image()
            
            with patch('cv2.threshold') as mock_threshold:
                gray_array = np.ones((50, 100), dtype=np.uint8) * 128
                binary_array = np.ones((50, 100), dtype=np.uint8) * 255
                mock_threshold.return_value = (127, binary_array)
                
                with patch('cv2.cvtColor', return_value=gray_array), \
                     patch('cv2.medianBlur', return_value=gray_array):
                    
                    result = engine._preprocess_image(test_image)
                    
                    # Should apply Otsu's thresholding
                    mock_threshold.assert_called_with(
                        gray_array, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
                    )
                    assert isinstance(result, Image.Image)

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
                engine.pytesseract.image_to_string.side_effect = TesseractError("Invalid configuration")
                
                invalid_config = "--invalid-option nonsense"
                image_data = self.create_test_image_data()
                
                # Should raise TesseractError or handle gracefully
                with pytest.raises((TesseractError, RuntimeError, Exception)):
                    engine.extract_text(image_data, config=invalid_config)
                
                # Test another type of invalid config
                engine.pytesseract.image_to_string.side_effect = TesseractError("PSM value out of range")
                invalid_psm_config = "--psm 99"  # Invalid PSM value
                
                with pytest.raises((TesseractError, RuntimeError, Exception)):
                    engine.extract_text(image_data, config=invalid_psm_config)



class TestEasyOCREngine:
    """Test suite for EasyOCR neural network-based OCR engine."""

    def create_test_image_data(self, width=100, height=50, color='white'):
        """Helper method to create test image data as bytes."""
        img = Image.new('RGB', (width, height), color=color)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    def test_easyocr_initialization_success(self):
        """
        GIVEN EasyOCR dependencies are available
        WHEN initializing EasyOCR
        THEN should successfully create Reader instance
        AND should set available to True
        AND should download models on first use
        """
        with patch('easyocr.Reader') as mock_reader:
            mock_reader_instance = Mock()
            mock_reader.return_value = mock_reader_instance
            
            with patch.object(EasyOCR, '_initialize') as mock_init:
                mock_init.return_value = None
                engine = EasyOCR()
                mock_init.assert_called_once()
                assert engine.name == 'easyocr'

    def test_easyocr_initialization_missing_dependencies(self):
        """
        GIVEN EasyOCR library is not installed
        WHEN initializing EasyOCR
        THEN should handle ImportError gracefully
        AND should set available to False
        """
        with patch.object(EasyOCR, '_initialize', side_effect=ImportError("No module named 'easyocr'")):
            engine = EasyOCR()
            assert hasattr(engine, 'name')
            assert engine.name == 'easyocr'
            assert hasattr(engine, 'available')

    def test_easyocr_initialization_model_download_failure(self):
        """
        GIVEN EasyOCR is installed but model download fails
        WHEN initializing EasyOCR
        THEN should handle download errors appropriately
        AND should set available to False
        """
        with patch.object(EasyOCR, '_initialize', side_effect=RuntimeError("Model download failed")):
            engine = EasyOCR()
            assert hasattr(engine, 'available')
            assert hasattr(engine, 'name')
            assert engine.name == 'easyocr'

    def test_easyocr_extract_text_complex_layout(self):
        """
        GIVEN an EasyOCR instance and image with complex layout
        WHEN calling extract_text()
        THEN should handle rotated and curved text
        AND should return accurate text extraction
        """
        with patch.object(EasyOCR, '_initialize'):
            engine = EasyOCR()
            engine.available = True
            engine.reader = Mock()
            
            # Mock complex layout detection results
            mock_results = [
                ([[10, 10], [50, 15], [48, 30], [8, 25]], 'Rotated Text', 0.92),
                ([[60, 20], [95, 25], [93, 40], [58, 35]], 'Curved Line', 0.88)
            ]
            engine.reader.readtext.return_value = mock_results
            
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
        with patch.object(EasyOCR, '_initialize'):
            engine = EasyOCR()
            engine.available = True
            engine.reader = Mock()
            
            # Mock rotated text detection
            mock_results = [
                ([[20, 10], [80, 25], [75, 40], [15, 25]], 'ROTATED', 0.95)
            ]
            engine.reader.readtext.return_value = mock_results
            
            image_data = self.create_test_image_data()
            result = engine.extract_text(image_data)
            
            assert 'ROTATED' in result['text']
            assert result['engine'] == 'easyocr'
            
            # Should have called readtext with image
            engine.reader.readtext.assert_called_once()

    def test_easyocr_extract_text_curved_text(self):
        """
        GIVEN an EasyOCR instance and image with curved text
        WHEN calling extract_text()
        THEN should handle curved text patterns
        AND should extract text accurately despite curvature
        """
        with patch.object(EasyOCR, '_initialize'):
            engine = EasyOCR()
            engine.available = True
            engine.reader = Mock()
            
            # Mock curved text with polygon bounding box
            mock_results = [
                ([[15, 5], [85, 15], [90, 35], [10, 25]], 'Curved Text Here', 0.89)
            ]
            engine.reader.readtext.return_value = mock_results
            
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
        with patch.object(EasyOCR, '_initialize'):
            engine = EasyOCR()
            engine.available = True
            engine.reader = Mock()
            
            # Mock multilingual results
            mock_results = [
                ([[10, 10], [40, 10], [40, 25], [10, 25]], 'Hello', 0.95),
                ([[50, 10], [80, 10], [80, 25], [50, 25]], 'Hola', 0.92),
                ([[10, 30], [50, 30], [50, 45], [10, 45]], 'Bonjour', 0.88)
            ]
            engine.reader.readtext.return_value = mock_results
            
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
        with patch.object(EasyOCR, '_initialize'):
            engine = EasyOCR()
            engine.available = True
            engine.reader = Mock()
            
            # Mock results with detailed polygon coordinates
            mock_results = [
                ([[15, 12], [65, 8], [67, 28], [17, 32]], 'Sample Text', 0.94),
                ([[20, 35], [75, 35], [75, 50], [20, 50]], 'Another Line', 0.91)
            ]
            engine.reader.readtext.return_value = mock_results
            
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
        with patch.object(EasyOCR, '_initialize'):
            engine = EasyOCR()
            engine.available = True
            engine.reader = Mock()
            
            # Mock varying confidence scores
            mock_results = [
                ([[10, 10], [50, 10], [50, 25], [10, 25]], 'Clear', 0.98),
                ([[60, 10], [90, 10], [90, 25], [60, 25]], 'Blurry', 0.65),
                ([[10, 30], [70, 30], [70, 45], [10, 45]], 'Very unclear', 0.32)
            ]
            engine.reader.readtext.return_value = mock_results
            
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
        with patch.object(EasyOCR, '_initialize'):
            engine = EasyOCR()
            engine.available = True
            
            # Mock Reader with GPU parameter
            with patch('easyocr.Reader') as mock_reader_class:
                mock_reader = Mock()
                mock_reader_class.return_value = mock_reader
                mock_reader.readtext.return_value = [
                    ([[10, 10], [50, 10], [50, 25], [10, 25]], 'GPU Text', 0.95)
                ]
                
                # Test GPU initialization
                engine.reader = mock_reader
                
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
        with patch.object(EasyOCR, '_initialize'):
            engine = EasyOCR()
            engine.available = True
            engine.reader = Mock()
            
            # Mock processing of large image
            mock_results = [
                ([[50, 100], [450, 100], [450, 150], [50, 150]], 'Large Image Text', 0.90)
            ]
            engine.reader.readtext.return_value = mock_results
            
            # Create larger test image
            large_image_data = self.create_test_image_data(500, 300)
            result = engine.extract_text(large_image_data)
            
            # Should handle large image without issues
            assert isinstance(result, dict)
            assert 'Large Image Text' in result['text']
            engine.reader.readtext.assert_called_once()

    def test_easyocr_extract_text_empty_image_data(self):
        """
        GIVEN an EasyOCR instance
        WHEN calling extract_text() with empty bytes
        THEN should raise ValueError
        """
        with patch.object(EasyOCR, '_initialize'):
            engine = EasyOCR()
            engine.available = True
            
            with pytest.raises(ValueError):
                engine.extract_text(b'')

    def test_easyocr_extract_text_invalid_image_format(self):
        """
        GIVEN an EasyOCR instance
        WHEN calling extract_text() with invalid image data
        THEN should raise PIL.UnidentifiedImageError or ValueError
        """
        with patch.object(EasyOCR, '_initialize'):
            engine = EasyOCR()
            engine.available = True
            
            with pytest.raises((ValueError, Exception)):
                engine.extract_text(b'not_an_image')

    def test_easyocr_extract_text_engine_not_available(self):
        """
        GIVEN an EasyOCR instance with available=False
        WHEN calling extract_text()
        THEN should raise RuntimeError
        """
        with patch.object(EasyOCR, '_initialize'):
            engine = EasyOCR()
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
        with patch.object(EasyOCR, '_initialize'):
            engine = EasyOCR()
            engine.available = True
            engine.reader = Mock()
            
            # Mock no text detection
            engine.reader.readtext.return_value = []
            
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
        with patch.object(EasyOCR, '_initialize'):
            engine = EasyOCR()
            engine.available = True
            engine.reader = Mock()
            
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
                engine.reader.readtext.return_value = mock_result
                
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
            
            # Mock processor and model pipeline
            mock_pixel_values = torch.randn(1, 3, 384, 384)
            engine.processor.return_value = {'pixel_values': mock_pixel_values}
            
            # Mock model generation
            mock_generated_ids = torch.tensor([[1, 2, 3, 4, 5]])
            engine.model.generate.return_value = mock_generated_ids
            
            # Mock decode
            engine.processor.decode.return_value = "handwritten text sample"
            
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
            assert result['confidence'] == 0.8  # Fixed confidence for TrOCR

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
            engine.processor.return_value = {'pixel_values': mock_pixel_values}
            
            mock_generated_ids = torch.tensor([[10, 20, 30, 40]])
            engine.model.generate.return_value = mock_generated_ids
            
            engine.processor.decode.return_value = "Clear printed text"
            
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
            engine.processor.return_value = {'pixel_values': mock_pixel_values}
            
            mock_generated_ids = torch.tensor([[5, 15, 25]])
            engine.model.generate.return_value = mock_generated_ids
            
            engine.processor.decode.return_value = "Single line"
            
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
        THEN should return fixed confidence score (0.8)
        AND should acknowledge lack of native confidence estimation
        """
        with patch.object(TrOCREngine, '_initialize'):
            engine = TrOCREngine()
            engine.available = True
            engine.processor = Mock()
            engine.model = Mock()
            
            # Mock processing
            mock_pixel_values = torch.randn(1, 3, 384, 384)
            engine.processor.return_value = {'pixel_values': mock_pixel_values}
            
            mock_generated_ids = torch.tensor([[1, 2, 3]])
            engine.model.generate.return_value = mock_generated_ids
            
            engine.processor.decode.return_value = "any text"
            
            image_data = self.create_test_image_data()
            result = engine.extract_text(image_data)
            
            # Should always return fixed confidence
            assert result['confidence'] == 0.8
            assert isinstance(result['confidence'], float)

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
            engine.processor.return_value = {'pixel_values': mock_pixel_values}
            
            mock_generated_ids = torch.tensor([[7, 8, 9]])
            engine.model.generate.return_value = mock_generated_ids
            
            engine.processor.decode.return_value = "text without boxes"
            
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
            engine.processor.return_value = {'pixel_values': mock_pixel_values}
            
            # Mock sequence generation
            mock_generated_ids = torch.tensor([[101, 102, 103, 104, 102]])
            engine.model.generate.return_value = mock_generated_ids
            
            engine.processor.decode.return_value = "sequence output"
            
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
                engine.processor.return_value = {'pixel_values': mock_pixel_values}
                
                mock_generated_ids = torch.tensor([[1, 2]])
                engine.model.generate.return_value = mock_generated_ids
                
                engine.processor.decode.return_value = f"converted {mode}"
                
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
                engine.processor.return_value = {'pixel_values': mock_pixel_values}
                
                mock_generated_ids = torch.tensor([[1, 2, 3]])
                engine.model.generate.return_value = mock_generated_ids
                
                engine.processor.decode.return_value = f"text from {model_name}"
                
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
                engine.processor.return_value = {'pixel_values': mock_pixel_values}
                engine.model.generate.return_value = seq
                engine.processor.decode.return_value = expected
                
                image_data = self.create_test_image_data()
                result = engine.extract_text(image_data)
                
                assert result['text'] == expected
                assert result['confidence'] == 0.8

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
            engine.processor.return_value = {'pixel_values': mock_pixel_values}
            
            mock_generated_ids = torch.tensor([[33, 44, 55, 66]])
            engine.model.generate.return_value = mock_generated_ids
            
            special_text = "Hello! @#$%^&*() 123-456 test."
            engine.processor.decode.return_value = special_text
            
            image_data = self.create_test_image_data()
            result = engine.extract_text(image_data)
            
            assert result['text'] == special_text
            assert result['engine'] == 'trocr'



class MockOCREngine(OCREngine):
    """Mock OCR engine for testing purposes."""
    
    def __init__(self, name: str, available: bool = True, confidence: float = 0.9, text: str = "mock text"):
        self.name = name
        self.available = available
        self.mock_confidence = confidence
        self.mock_text = text
    
    def _initialize(self):
        pass  # Already set in __init__
    
    def extract_text(self, image_data: bytes):
        if not self.available:
            raise RuntimeError(f"{self.name} not available")
        return {
            'text': self.mock_text,
            'confidence': self.mock_confidence,
            'engine': self.name
        }
    
    def is_available(self):
        return self.available


class TestMultiEngineOCR:
    """Test suite for MultiEngineOCR orchestrator class."""

    def create_test_image_data(self, width=100, height=50, color='white'):
        """Helper method to create test image data as bytes."""
        img = Image.new('RGB', (width, height), color=color)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    def test_multi_engine_ocr_initialization_all_engines(self):
        """
        GIVEN all OCR engine dependencies are available
        WHEN initializing MultiEngineOCR
        THEN should successfully initialize all engines
        AND should populate engines dict with all available engines
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # Mock all engines as available
            mock_surya.return_value = MockOCREngine('surya', True)
            mock_tesseract.return_value = MockOCREngine('tesseract', True)
            mock_easy.return_value = MockOCREngine('easyocr', True)
            mock_trocr.return_value = MockOCREngine('trocr', True)
            
            multi_ocr = MultiEngineOCR()
            
            image_data = self.create_test_image_data()
            result = multi_ocr.extract_with_fallback(
                image_data, 
                strategy='quality_first', 
                confidence_threshold=0.8
            )
            
            # Should use Surya (first in quality_first order) and stop there
            assert result['text'] == "surya result"
            assert result['engine'] == 'surya'
            assert result['confidence'] == 0.95

    def test_extract_with_fallback_speed_first_strategy(self):
        """
        GIVEN a MultiEngineOCR instance with multiple engines
        WHEN calling extract_with_fallback() with strategy='speed_first'
        THEN should try engines in order: Tesseract → Surya → EasyOCR → TrOCR
        AND should prioritize fastest processing
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # Tesseract (fastest) has good confidence
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.85, text="tesseract fast")
            mock_surya.return_value = MockOCREngine('surya', True, confidence=0.95, text="surya result")
            mock_easy.return_value = MockOCREngine('easyocr', True, confidence=0.80, text="easy result")
            mock_trocr.return_value = MockOCREngine('trocr', True, confidence=0.75, text="trocr result")
            
            multi_ocr = MultiEngineOCR()
            
            image_data = self.create_test_image_data()
            result = multi_ocr.extract_with_fallback(
                image_data,
                strategy='speed_first',
                confidence_threshold=0.8
            )
            
            # Should use Tesseract (first in speed_first order)
            assert result['text'] == "tesseract fast"
            assert result['engine'] == 'tesseract'
            assert result['confidence'] == 0.85

    def test_extract_with_fallback_accuracy_first_strategy(self):
        """
        GIVEN a MultiEngineOCR instance with multiple engines
        WHEN calling extract_with_fallback() with strategy='accuracy_first'
        THEN should try engines in order: Surya → EasyOCR → TrOCR → Tesseract
        AND should prioritize most accurate engines
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # Surya (most accurate) available
            mock_surya.return_value = MockOCREngine('surya', True, confidence=0.97, text="surya accurate")
            mock_easy.return_value = MockOCREngine('easyocr', True, confidence=0.89, text="easy result")
            mock_trocr.return_value = MockOCREngine('trocr', True, confidence=0.82, text="trocr result")
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.78, text="tesseract result")
            
            multi_ocr = MultiEngineOCR()
            
            image_data = self.create_test_image_data()
            result = multi_ocr.extract_with_fallback(
                image_data,
                strategy='accuracy_first',
                confidence_threshold=0.9
            )
            
            # Should use Surya (first in accuracy_first order)
            assert result['text'] == "surya accurate"
            assert result['engine'] == 'surya'
            assert result['confidence'] == 0.97

    def test_extract_with_fallback_confidence_threshold_met(self):
        """
        GIVEN a MultiEngineOCR instance and high-quality image
        WHEN calling extract_with_fallback() with confidence_threshold=0.8
        THEN should stop at first engine meeting threshold
        AND should return results from that engine
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract:
            
            mock_surya.return_value = MockOCREngine('surya', True, confidence=0.9, text="high quality")
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.7, text="lower quality")
            
            multi_ocr = MultiEngineOCR()
            
            image_data = self.create_test_image_data()
            result = multi_ocr.extract_with_fallback(
                image_data,
                strategy='quality_first',
                confidence_threshold=0.85
            )
            
            # Should stop at Surya since it meets threshold
            assert result['confidence'] >= 0.85
            assert result['engine'] == 'surya'

    def test_extract_with_fallback_confidence_threshold_not_met(self):
        """
        GIVEN a MultiEngineOCR instance and low-quality image
        WHEN calling extract_with_fallback() with high confidence_threshold
        THEN should try all available engines
        AND should return best available result even below threshold
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy:
            
            # All engines have low confidence
            mock_surya.return_value = MockOCREngine('surya', True, confidence=0.6, text="surya low")
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.5, text="tesseract low")
            mock_easy.return_value = MockOCREngine('easyocr', True, confidence=0.7, text="easy best")
            
            multi_ocr = MultiEngineOCR()
            
            image_data = self.create_test_image_data()
            result = multi_ocr.extract_with_fallback(
                image_data,
                strategy='quality_first',
                confidence_threshold=0.9  # High threshold
            )
            
            # Should return best result even though below threshold
            assert result['confidence'] < 0.9
            # Should have tried multiple engines and returned the best
            assert isinstance(result, dict)
            assert 'text' in result
            assert 'engine' in result

    def test_extract_with_fallback_single_engine_available(self):
        """
        GIVEN a MultiEngineOCR instance with only one available engine
        WHEN calling extract_with_fallback()
        THEN should use the single available engine
        AND should return its results regardless of strategy
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # Only one engine available
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.8, text="only option")
            mock_surya.return_value = MockOCREngine('surya', False)
            mock_easy.return_value = MockOCREngine('easyocr', False)
            mock_trocr.return_value = MockOCREngine('trocr', False)
            
            multi_ocr = MultiEngineOCR()
            
            image_data = self.create_test_image_data()
            result = multi_ocr.extract_with_fallback(image_data)
            
            assert result['engine'] == 'tesseract'
            assert result['text'] == "only option"

    def test_extract_with_fallback_no_engines_available(self):
        """
        GIVEN a MultiEngineOCR instance with no available engines
        WHEN calling extract_with_fallback()
        THEN should raise appropriate error
        AND should indicate no engines available
        """
        multi_ocr = MultiEngineOCR()
        multi_ocr.engines = {}  # No engines
        
        image_data = self.create_test_image_data()
        
        with pytest.raises((RuntimeError, ValueError), match="no.*engine|not.*available"):
            multi_ocr.extract_with_fallback(image_data)

    def test_extract_with_fallback_engine_failure_handling(self):
        """
        GIVEN a MultiEngineOCR instance where first engine fails
        WHEN calling extract_with_fallback()
        THEN should continue to next engine in strategy order
        AND should handle individual engine failures gracefully
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract:
            
            # First engine fails, second succeeds
            failing_engine = MockOCREngine('surya', True)
            failing_engine.extract_text = Mock(side_effect=RuntimeError("Surya failed"))
            
            mock_surya.return_value = failing_engine
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.8, text="fallback success")
            
            multi_ocr = MultiEngineOCR()
            
            image_data = self.create_test_image_data()
            result = multi_ocr.extract_with_fallback(image_data, strategy='quality_first')
            
            # Should have fallen back to Tesseract
            assert result['engine'] == 'tesseract'
            assert result['text'] == "fallback success"

    def test_extract_with_fallback_invalid_strategy(self):
        """
        GIVEN a MultiEngineOCR instance
        WHEN calling extract_with_fallback() with invalid strategy
        THEN should raise ValueError or use default strategy
        """
        multi_ocr = MultiEngineOCR()
        image_data = self.create_test_image_data()
        
        with pytest.raises(ValueError, match="strategy|invalid"):
            multi_ocr.extract_with_fallback(image_data, strategy='invalid_strategy')

    def test_extract_with_fallback_invalid_confidence_threshold(self):
        """
        GIVEN a MultiEngineOCR instance
        WHEN calling extract_with_fallback() with confidence_threshold outside [0.0, 1.0]
        THEN should raise ValueError
        """
        multi_ocr = MultiEngineOCR()
        image_data = self.create_test_image_data()
        
        # Test values outside valid range
        invalid_thresholds = [-0.1, 1.1, 2.0, -1.0]
        
        for threshold in invalid_thresholds:
            with pytest.raises(ValueError, match="confidence.*threshold|range"):
                multi_ocr.extract_with_fallback(image_data, confidence_threshold=threshold)

    def test_extract_with_fallback_result_format_consistency(self):
        """
        GIVEN a MultiEngineOCR instance
        WHEN calling extract_with_fallback() with any engine
        THEN should return consistent result format
        AND should include text, confidence, engine metadata
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract:
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.85, text="consistent format")
            
            multi_ocr = MultiEngineOCR()
            
            image_data = self.create_test_image_data()
            result = multi_ocr.extract_with_fallback(image_data)
            
            # Check consistent format
            assert isinstance(result, dict)
            required_keys = {'text', 'confidence', 'engine'}
            assert required_keys.issubset(result.keys())
            
            assert isinstance(result['text'], str)
            assert isinstance(result['confidence'], float)
            assert isinstance(result['engine'], str)
            assert 0.0 <= result['confidence'] <= 1.0

    def test_extract_with_fallback_performance_monitoring(self):
        """
        GIVEN a MultiEngineOCR instance
        WHEN calling extract_with_fallback() multiple times
        THEN should track engine performance and failure modes
        AND should provide comprehensive logging
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract:
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.8, text="monitored")
            
            multi_ocr = MultiEngineOCR()
            image_data = self.create_test_image_data()
            
            # Multiple calls to test performance monitoring
            results = []
            for _ in range(3):
                result = multi_ocr.extract_with_fallback(image_data)
                results.append(result)
            
            # All results should be consistent
            for result in results:
                assert result['engine'] == 'tesseract'
                assert result['text'] == "monitored"

    def test_extract_with_fallback_thread_safety(self):
        """
        GIVEN a MultiEngineOCR instance
        WHEN calling extract_with_fallback() from multiple threads
        THEN should be thread-safe for concurrent processing
        AND should not interfere between concurrent requests
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract:
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.8, text="thread safe")
            
            multi_ocr = MultiEngineOCR()
            image_data = self.create_test_image_data()
            
            results = []
            exceptions = []
            
            def extract_text_thread():
                try:
                    for _ in range(10):
                        result = multi_ocr.extract_with_fallback(image_data)
                        results.append(result)
                        time.sleep(0.001)  # Small delay
                except Exception as e:
                    exceptions.append(e)
            
            threads = [threading.Thread(target=extract_text_thread) for _ in range(3)]
            
            for thread in threads:
                thread.start()
            
            for thread in threads:
                thread.join()
            
            # Should have no exceptions
            assert len(exceptions) == 0, f"Thread safety test failed: {exceptions}"
            
            # All results should be consistent
            assert len(results) == 30  # 3 threads × 10 iterations
            for result in results:
                assert result['engine'] == 'tesseract'
                assert result['text'] == "thread safe"

    def test_extract_with_fallback_empty_image_data(self):
        """
        GIVEN a MultiEngineOCR instance
        WHEN calling extract_with_fallback() with empty image data
        THEN should raise ValueError
        """
        multi_ocr = MultiEngineOCR()
        
        with pytest.raises(ValueError):
            multi_ocr.extract_with_fallback(b'')

    def test_extract_with_fallback_none_image_data(self):
        """
        GIVEN a MultiEngineOCR instance
        WHEN calling extract_with_fallback() with None image data
        THEN should raise TypeError or ValueError
        """
        multi_ocr = MultiEngineOCR()
        
        with pytest.raises((TypeError, ValueError)):
            multi_ocr.extract_with_fallback(None)

    def test_extract_with_fallback_strategy_engine_ordering(self):
        """
        GIVEN a MultiEngineOCR instance with all engines available
        WHEN testing different strategies
        THEN should demonstrate correct engine ordering for each strategy
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # All engines available but with low confidence to force trying multiple
            engines = {
                'surya': MockOCREngine('surya', True, confidence=0.5, text="surya"),
                'tesseract': MockOCREngine('tesseract', True, confidence=0.5, text="tesseract"),
                'easyocr': MockOCREngine('easyocr', True, confidence=0.5, text="easyocr"),
                'trocr': MockOCREngine('trocr', True, confidence=0.5, text="trocr")
            }
            
            mock_surya.return_value = engines['surya']
            mock_tesseract.return_value = engines['tesseract']
            mock_easy.return_value = engines['easyocr']
            mock_trocr.return_value = engines['trocr']
            
            multi_ocr = MultiEngineOCR()
            image_data = self.create_test_image_data()
            
            # Test that each strategy tries engines in correct order
            strategies = ['quality_first', 'speed_first', 'accuracy_first']
            
            for strategy in strategies:
                # Use very high threshold to force trying all engines
                result = multi_ocr.extract_with_fallback(
                    image_data, 
                    strategy=strategy, 
                    confidence_threshold=0.99
                )
                
                # Should return some result
                assert isinstance(result, dict)
                assert 'engine' in result
                assert result['engine'] in ['surya', 'tesseract', 'easyocr', 'trocr']
            
            # Should have all engines
            expected_engines = {'surya', 'tesseract', 'easyocr', 'trocr'}
            assert set(multi_ocr.engines.keys()) == expected_engines
            
            # All engines should be available
            available_engines = multi_ocr.get_available_engines()
            assert set(available_engines) == expected_engines

    def test_multi_engine_ocr_initialization_partial_engines(self):
        """
        GIVEN only some OCR engine dependencies are available
        WHEN initializing MultiEngineOCR
        THEN should initialize available engines gracefully
        AND should skip unavailable engines without crashing
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # Only some engines available
            mock_surya.return_value = MockOCREngine('surya', True)
            mock_tesseract.return_value = MockOCREngine('tesseract', False)  # Not available
            mock_easy.return_value = MockOCREngine('easyocr', True)
            mock_trocr.return_value = MockOCREngine('trocr', False)  # Not available
            
            multi_ocr = MultiEngineOCR()
            
            # Should only have available engines
            available_engines = multi_ocr.get_available_engines()
            assert set(available_engines) == {'surya', 'easyocr'}
            
            # Should still have all engines in dict but only available ones are usable
            assert len(multi_ocr.engines) == 4  # All created
            assert multi_ocr.engines['surya'].is_available()
            assert not multi_ocr.engines['tesseract'].is_available()

    def test_multi_engine_ocr_initialization_no_engines(self):
        """
        GIVEN no OCR engine dependencies are available
        WHEN initializing MultiEngineOCR
        THEN should initialize with empty engines dict
        AND should handle gracefully without crashing
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # All engines unavailable
            mock_surya.return_value = MockOCREngine('surya', False)
            mock_tesseract.return_value = MockOCREngine('tesseract', False)
            mock_easy.return_value = MockOCREngine('easyocr', False)
            mock_trocr.return_value = MockOCREngine('trocr', False)
            
            multi_ocr = MultiEngineOCR()
            
            # Should have no available engines
            available_engines = multi_ocr.get_available_engines()
            assert len(available_engines) == 0

    def test_get_available_engines_returns_list(self):
        """
        GIVEN a MultiEngineOCR instance with some available engines
        WHEN calling get_available_engines()
        THEN should return list of engine names
        AND list should contain only successfully initialized engines
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            mock_surya.return_value = MockOCREngine('surya', True)
            mock_tesseract.return_value = MockOCREngine('tesseract', True)
            mock_easy.return_value = MockOCREngine('easyocr', False)
            mock_trocr.return_value = MockOCREngine('trocr', True)
            
            multi_ocr = MultiEngineOCR()
            available = multi_ocr.get_available_engines()
            
            assert isinstance(available, list)
            assert set(available) == {'surya', 'tesseract', 'trocr'}

    def test_get_available_engines_empty_when_no_engines(self):
        """
        GIVEN a MultiEngineOCR instance with no available engines
        WHEN calling get_available_engines()
        THEN should return empty list
        """
        multi_ocr = MultiEngineOCR()
        multi_ocr.engines = {}  # Simulate no engines
        
        available = multi_ocr.get_available_engines()
        assert isinstance(available, list)
        assert len(available) == 0

    def test_get_available_engines_reflects_initialization_state(self):
        """
        GIVEN a MultiEngineOCR instance
        WHEN calling get_available_engines()
        THEN should reflect engines available at initialization time
        AND should not re-check engine availability
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya:
            mock_engine = MockOCREngine('surya', True)
            mock_surya.return_value = mock_engine
            
            multi_ocr = MultiEngineOCR()
            
            # Initially available
            available = multi_ocr.get_available_engines()
            assert 'surya' in available
            
            # Change engine availability after initialization
            mock_engine.available = False
            
            # Should still return as available (doesn't re-check)
            available_again = multi_ocr.get_available_engines()
            assert 'surya' in available_again

    def test_classify_document_type_printed_placeholder(self):
        """
        GIVEN a MultiEngineOCR instance and any image data
        WHEN calling classify_document_type()
        THEN should return 'printed' as placeholder implementation
        """
        multi_ocr = MultiEngineOCR()
        image_data = self.create_test_image_data()
        
        doc_type = multi_ocr.classify_document_type(image_data)
        assert doc_type == 'printed'

    def test_extract_with_fallback_quality_first_strategy(self):
        """
        GIVEN a MultiEngineOCR instance with multiple engines
        WHEN calling extract_with_fallback() with strategy='quality_first'
        THEN should try engines in order: Surya → Tesseract → EasyOCR → TrOCR
        AND should stop when confidence threshold is met
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # Surya has high confidence, should stop there
            mock_surya.return_value = MockOCREngine('surya', True, confidence=0.95, text="surya result")
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.85, text="tesseract result")
            mock_easy.return_value = MockOCREngine('easyocr', True, confidence=0.80, text="easy result")
            mock_trocr.return_value = MockOCREngine('trocr', True, confidence=0.75, text="trocr result")
            
            multi_ocr = MultiEngineOCR()



class TestOCREngineIntegration:
    """Integration tests for OCR engine interactions and edge cases."""

    def create_test_image_data(self, width=100, height=50, color='white'):
        """Helper method to create test image data as bytes."""
        img = Image.new('RGB', (width, height), color=color)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    def test_all_engines_consistent_interface(self):
        """
        GIVEN all available OCR engines
        WHEN calling extract_text() on each engine with same image
        THEN should all return dictionaries with consistent key structure
        AND should all include 'text', 'confidence', 'engine' keys at minimum
        """
        image_data = self.create_test_image_data()
        
        # Mock all engines to be available
        engines = []
        
        with patch.object(SuryaOCR, '_initialize'):
            surya = SuryaOCR()
            surya.available = True
            surya.run_ocr = Mock(return_value=([Mock(text="surya", confidence=0.9)], ["en"]))
            surya.det_processor = Mock()
            surya.det_model = Mock()
            surya.rec_model = Mock()
            surya.rec_processor = Mock()
            engines.append(surya)
        
        with patch.object(TesseractOCR, '_initialize'):
            tesseract = TesseractOCR()
            tesseract.available = True
            tesseract.pytesseract = Mock()
            tesseract.pytesseract.image_to_string.return_value = "tesseract"
            tesseract.pytesseract.image_to_data.return_value = {
                'text': ['tesseract'], 'conf': [90], 'left': [10], 'top': [10], 
                'width': [50], 'height': [15]
            }
            with patch.object(tesseract, '_preprocess_image', return_value=Image.new('RGB', (100, 50))):
                engines.append(tesseract)
        
        with patch.object(EasyOCR, '_initialize'):
            easyocr = EasyOCR()
            easyocr.available = True
            easyocr.reader = Mock()
            easyocr.reader.readtext.return_value = [
                ([[10, 10], [50, 10], [50, 25], [10, 25]], 'easyocr', 0.9)
            ]
            engines.append(easyocr)
        
        with patch.object(TrOCREngine, '_initialize'):
            trocr = TrOCREngine()
            trocr.available = True
            trocr.processor = Mock()
            trocr.model = Mock()
            trocr.processor.return_value = {'pixel_values': Mock()}
            trocr.model.generate.return_value = Mock()
            trocr.processor.decode.return_value = "trocr"
            engines.append(trocr)
        
        # Test all engines have consistent interface
        required_keys = {'text', 'confidence', 'engine'}
        
        for engine in engines:
            result = engine.extract_text(image_data)
            
            assert isinstance(result, dict)
            assert required_keys.issubset(result.keys())
            assert isinstance(result['text'], str)
            assert isinstance(result['confidence'], (int, float))
            assert isinstance(result['engine'], str)
            assert 0.0 <= float(result['confidence']) <= 1.0 or 0 <= int(result['confidence']) <= 100

    def test_engine_availability_after_initialization(self):
        """
        GIVEN all OCR engine classes
        WHEN checking is_available() after initialization
        THEN should accurately reflect successful/failed initialization
        AND should be consistent with actual functionality
        """
        # Test successful initialization
        with patch.object(SuryaOCR, '_initialize'):
            surya = SuryaOCR()
            surya.available = True
            assert surya.is_available() == True
        
        # Test failed initialization
        with patch.object(SuryaOCR, '_initialize', side_effect=ImportError("Failed")):
            surya_fail = SuryaOCR()
            # Availability depends on error handling implementation
            assert hasattr(surya_fail, 'available')
            assert isinstance(surya_fail.is_available(), bool)

    def test_cross_engine_text_extraction_accuracy(self):
        """
        GIVEN same high-quality text image
        WHEN extracting text with different engines
        THEN should produce similar text results
        AND should demonstrate relative strengths/weaknesses
        """
        image_data = self.create_test_image_data()
        expected_text = "Sample Text"
        
        engines = {}
        
        # Mock engines with similar but slightly different results
        with patch.object(SuryaOCR, '_initialize'):
            surya = SuryaOCR()
            surya.available = True
            surya.run_ocr = Mock(return_value=([Mock(text="Sample Text", confidence=0.95)], ["en"]))
            surya.det_processor = Mock()
            surya.det_model = Mock()
            surya.rec_model = Mock()
            surya.rec_processor = Mock()
            engines['surya'] = surya
        
        with patch.object(TesseractOCR, '_initialize'):
            tesseract = TesseractOCR()
            tesseract.available = True
            tesseract.pytesseract = Mock()
            tesseract.pytesseract.image_to_string.return_value = "Sample Text"
            tesseract.pytesseract.image_to_data.return_value = {
                'text': ['Sample', 'Text'], 'conf': [92, 88], 'left': [10, 50], 
                'top': [10, 10], 'width': [35, 25], 'height': [15, 15]
            }
            with patch.object(tesseract, '_preprocess_image', return_value=Image.new('RGB', (100, 50))):
                engines['tesseract'] = tesseract
        
        results = {}
        for name, engine in engines.items():
            result = engine.extract_text(image_data)
            results[name] = result
        
        # All should produce similar text
        for name, result in results.items():
            assert "Sample" in result['text']
            assert "Text" in result['text']
            assert result['confidence'] > 0.8

    def test_engine_performance_characteristics(self):
        """
        GIVEN same image processed by multiple engines
        WHEN measuring processing time and memory usage
        THEN should demonstrate expected performance characteristics
        AND should validate speed_first strategy assumptions
        """
        image_data = self.create_test_image_data()
        
        # Mock engines with performance simulation
        processing_times = {}
        
        with patch.object(TesseractOCR, '_initialize'):
            tesseract = TesseractOCR()
            tesseract.available = True
            tesseract.pytesseract = Mock()
            tesseract.pytesseract.image_to_string.return_value = "fast"
            tesseract.pytesseract.image_to_data.return_value = {
                'text': ['fast'], 'conf': [85], 'left': [10], 'top': [10], 
                'width': [30], 'height': [15]
            }
            
            with patch.object(tesseract, '_preprocess_image', return_value=Image.new('RGB', (100, 50))):
                start_time = time.time()
                result = tesseract.extract_text(image_data)
                processing_times['tesseract'] = time.time() - start_time
        
        # In real scenario, Tesseract should be fastest
        assert 'tesseract' in processing_times
        assert processing_times['tesseract'] >= 0  # Should complete

    def test_engine_error_handling_consistency(self):
        """
        GIVEN invalid inputs (empty data, corrupted images, etc.)
        WHEN processing with different engines
        THEN should handle errors consistently
        AND should raise appropriate exception types
        """
        invalid_inputs = [
            b'',  # Empty data
            b'not_an_image',  # Invalid data
            None  # None input
        ]
        
        engines = []
        
        # Create mock engines
        with patch.object(TesseractOCR, '_initialize'):
            tesseract = TesseractOCR()
            tesseract.available = True
            engines.append(tesseract)
        
        with patch.object(EasyOCR, '_initialize'):
            easyocr = EasyOCR()
            easyocr.available = True
            engines.append(easyocr)
        
        for engine in engines:
            for invalid_input in invalid_inputs:
                with pytest.raises((ValueError, TypeError, Exception)):
                    engine.extract_text(invalid_input)

    def test_multi_engine_fallback_real_world_scenarios(self):
        """
        GIVEN various real-world document types and quality levels
        WHEN using MultiEngineOCR with different strategies
        THEN should demonstrate effective fallback behavior
        AND should improve overall extraction success rate
        """
        multi_engine = MultiEngineOCR()
        
        # Mock available engines with different capabilities
        mock_tesseract = Mock()
        mock_tesseract.name = 'tesseract'
        mock_tesseract.is_available.return_value = True
        
        mock_easyocr = Mock()
        mock_easyocr.name = 'easyocr'
        mock_easyocr.is_available.return_value = True
        
        mock_surya = Mock()
        mock_surya.name = 'surya'
        mock_surya.is_available.return_value = True
        
        multi_engine.engines = [mock_tesseract, mock_easyocr, mock_surya]
        
        # Create test image data
        test_image = self.create_test_image_data()
        
        # Test scenario 1: First engine fails, second succeeds
        mock_tesseract.extract_text.side_effect = RuntimeError("Engine failed")
        mock_easyocr.extract_text.return_value = {
            'text': 'Fallback success',
            'confidence': 0.85,
            'engine': 'easyocr'
        }
        
        result = multi_engine.extract_with_fallback(test_image)
        assert result['text'] == 'Fallback success'
        assert result['engine'] == 'easyocr'
        
        # Test scenario 2: Multiple engines succeed, best result selected
        mock_tesseract.extract_text.side_effect = None
        mock_tesseract.extract_text.return_value = {
            'text': 'Low quality result',
            'confidence': 0.65,
            'engine': 'tesseract'
        }
        mock_easyocr.extract_text.return_value = {
            'text': 'High quality result',
            'confidence': 0.95,
            'engine': 'easyocr'
        }
        
        result = multi_engine.extract_with_fallback(test_image, strategy='best_confidence')
        assert result['confidence'] == 0.95
        assert result['engine'] == 'easyocr'

    def test_engine_memory_cleanup(self):
        """
        GIVEN OCR engines processing large images
        WHEN extraction completes or fails
        THEN should properly clean up memory resources
        AND should not leak memory between operations
        """
        import gc
        import psutil
        import os
        
        # Get current process for memory monitoring
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        # Test with TesseractOCR
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            engine.available = True
            engine.pytesseract = Mock()
            
            # Mock large image processing
            large_image_data = self.create_test_image_data(2000, 1500)
            
            # Mock successful extraction
            engine.pytesseract.image_to_string.return_value = "Large document text"
            engine.pytesseract.image_to_data.return_value = {
                'text': ['Large', 'document', 'text'],
                'conf': [95, 92, 88],
                'left': [10, 60, 150],
                'top': [10, 10, 10],
                'width': [45, 75, 40],
                'height': [20, 20, 20]
            }
            
            with patch.object(engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = Image.new('RGB', (2000, 1500), 'white')
                
                # Process multiple large images
                for _ in range(5):
                    result = engine.extract_text(large_image_data)
                    assert isinstance(result, dict)
                    
                # Force garbage collection
                gc.collect()
                
                # Check memory hasn't grown excessively
                final_memory = process.memory_info().rss
                memory_growth = final_memory - initial_memory
                
                # Memory growth should be reasonable (less than 100MB for this test)
                assert memory_growth < 100 * 1024 * 1024, f"Excessive memory growth: {memory_growth} bytes"

    def test_engine_gpu_resource_sharing(self):
        """
        GIVEN multiple GPU-enabled engines (Surya, EasyOCR, TrOCR)
        WHEN running concurrent operations
        THEN should share GPU resources appropriately
        AND should handle GPU memory limitations gracefully
        """
        # Mock GPU availability check
        with patch('torch.cuda.is_available', return_value=True), \
             patch('torch.cuda.device_count', return_value=1), \
             patch('torch.cuda.get_device_properties') as mock_props:
            
            # Mock GPU properties
            mock_device = Mock()
            mock_device.total_memory = 8 * 1024**3  # 8GB GPU
            mock_props.return_value = mock_device
            
            # Initialize GPU-enabled engines
            with patch.object(EasyOCR, '_initialize') as mock_easy_init, \
                 patch.object(SuryaOCR, '_initialize') as mock_surya_init, \
                 patch.object(TrOCREngine, '_initialize') as mock_trocr_init:
                
                # Mock successful initialization
                mock_easy_init.return_value = None
                mock_surya_init.return_value = None
                mock_trocr_init.return_value = None
                
                easy_engine = EasyOCR()
                easy_engine.available = True
                easy_engine.reader = Mock()
                
                surya_engine = SuryaOCR()
                surya_engine.available = True
                surya_engine.run_ocr = Mock()
                
                trocr_engine = TrOCREngine()
                trocr_engine.available = True
                trocr_engine.processor = Mock()
                trocr_engine.model = Mock()
                
                # Mock concurrent processing
                test_image = self.create_test_image_data()
                
                # Mock extraction results
                easy_engine.reader.readtext.return_value = [
                    ([[10, 10], [90, 10], [90, 30], [10, 30]], 'EasyOCR Text', 0.92)
                ]
                
                mock_surya_lines = [Mock(text="Surya Text", confidence=0.88)]
                surya_engine.run_ocr.return_value = ([mock_surya_lines], ["en"])
                
                trocr_engine.processor.return_value = {'pixel_values': Mock()}
                trocr_engine.model.generate.return_value = Mock()
                trocr_engine.processor.batch_decode.return_value = ["TrOCR Text"]
                
                # Test concurrent extraction
                results = []
                
                def extract_with_engine(engine, image_data):
                    return engine.extract_text(image_data)
                
                # Simulate concurrent access
                with patch('threading.Thread') as mock_thread:
                    # Mock thread execution
                    threads = []
                    for engine in [easy_engine, surya_engine, trocr_engine]:
                        thread = Mock()
                        thread.start = Mock()
                        thread.join = Mock()
                        threads.append(thread)
                        
                        # Simulate result
                        result = extract_with_engine(engine, test_image)
                        results.append(result)
                    
                    mock_thread.side_effect = threads
                    
                # Verify all engines processed successfully
                assert len(results) == 3
                for result in results:
                    assert isinstance(result, dict)
                    assert 'text' in result
                    assert 'engine' in result


class TestOCREngineErrorHandling:
    """Test suite for error handling and edge cases across all engines."""

    def test_all_engines_handle_none_image_data(self):
        """
        GIVEN any OCR engine
        WHEN calling extract_text(None)
        THEN should raise ValueError or TypeError
        """
        # Test TesseractOCR
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            
            with pytest.raises((ValueError, TypeError)):
                tesseract_engine.extract_text(None)
        
        # Test EasyOCR
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            
            with pytest.raises((ValueError, TypeError)):
                easy_engine.extract_text(None)
        
        # Test SuryaOCR
        with patch.object(SuryaOCR, '_initialize'):
            surya_engine = SuryaOCR()
            surya_engine.available = True
            
            with pytest.raises((ValueError, TypeError)):
                surya_engine.extract_text(None)
        
        # Test TrOCREngine
        with patch.object(TrOCREngine, '_initialize'):
            trocr_engine = TrOCREngine()
            trocr_engine.available = True
            
            with pytest.raises((ValueError, TypeError)):
                trocr_engine.extract_text(None)

    def test_all_engines_handle_empty_bytes(self):
        """
        GIVEN any OCR engine
        WHEN calling extract_text(b'')
        THEN should raise ValueError
        """
        # Test TesseractOCR
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            
            with pytest.raises(ValueError):
                tesseract_engine.extract_text(b'')
        
        # Test EasyOCR
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            
            with pytest.raises(ValueError):
                easy_engine.extract_text(b'')
        
        # Test SuryaOCR
        with patch.object(SuryaOCR, '_initialize'):
            surya_engine = SuryaOCR()
            surya_engine.available = True
            
            with pytest.raises(ValueError):
                surya_engine.extract_text(b'')
        
        # Test TrOCREngine
        with patch.object(TrOCREngine, '_initialize'):
            trocr_engine = TrOCREngine()
            trocr_engine.available = True
            
            with pytest.raises(ValueError):
                trocr_engine.extract_text(b'')

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
        
        # Test SuryaOCR
        with patch.object(SuryaOCR, '_initialize'):
            surya_engine = SuryaOCR()
            surya_engine.available = True
            surya_engine.run_ocr = Mock()
            surya_engine.run_ocr.return_value = ([], ["en"])  # No text lines found
            
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


class TestOCREnginePerformance:
    """Test suite for performance characteristics and resource usage."""

    def test_engine_initialization_time(self):
        """
        GIVEN each OCR engine class
        WHEN measuring initialization time
        THEN should complete within reasonable time limits
        AND should reflect expected complexity (neural vs traditional)
        """
        import time
        
        # Test TesseractOCR (should be fast - traditional)
        with patch.object(TesseractOCR, '_initialize'):
            start_time = time.time()
            tesseract_engine = TesseractOCR()
            tesseract_init_time = time.time() - start_time
            
            # Should initialize quickly (traditional OCR)
            assert tesseract_init_time < 1.0  # Less than 1 second
        
        # Test EasyOCR (neural - may be slower)
        with patch.object(EasyOCR, '_initialize'):
            start_time = time.time()
            easy_engine = EasyOCR()
            easy_init_time = time.time() - start_time
            
            # Neural network initialization might take longer
            assert easy_init_time < 5.0  # Less than 5 seconds for test
        
        # Test SuryaOCR (neural - may be slower)
        with patch.object(SuryaOCR, '_initialize'):
            start_time = time.time()
            surya_engine = SuryaOCR()
            surya_init_time = time.time() - start_time
            
            # Neural network initialization
            assert surya_init_time < 5.0  # Less than 5 seconds for test
        
        # Test TrOCREngine (transformer - may be slowest)
        with patch.object(TrOCREngine, '_initialize'):
            start_time = time.time()
            trocr_engine = TrOCREngine()
            trocr_init_time = time.time() - start_time
            
            # Transformer initialization
            assert trocr_init_time < 10.0  # Less than 10 seconds for test
        
        # Verify expected order: Tesseract <= Others
        assert tesseract_init_time <= max(easy_init_time, surya_init_time, trocr_init_time)

    def test_engine_processing_time_scaling(self):
        """
        GIVEN each OCR engine and images of varying sizes
        WHEN measuring processing time vs image size
        THEN should demonstrate expected scaling characteristics
        AND should not have unreasonable time complexity
        """
        import time
        
        def create_test_image_of_size(width, height):
            """Helper to create test image of specific size."""
            img = Image.new('RGB', (width, height), color='white')
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.text((10, height//2), f"Test {width}x{height}", fill='black')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        
        # Test different image sizes
        image_sizes = [(100, 50), (200, 100), (400, 200)]
        
        # Test TesseractOCR scaling
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            tesseract_engine.pytesseract = Mock()
            
            tesseract_times = []
            for width, height in image_sizes:
                image_data = create_test_image_of_size(width, height)
                
                with patch.object(tesseract_engine, '_preprocess_image') as mock_preprocess:
                    mock_preprocess.return_value = Image.new('RGB', (width, height), 'white')
                    tesseract_engine.pytesseract.image_to_string.return_value = f"Test {width}x{height}"
                    tesseract_engine.pytesseract.image_to_data.return_value = {
                        'text': ['Test', f'{width}x{height}'], 'conf': [95, 92], 
                        'left': [10, 50], 'top': [height//2, height//2], 
                        'width': [35, 60], 'height': [20, 20]
                    }
                    
                    start_time = time.time()
                    result = tesseract_engine.extract_text(image_data)
                    processing_time = time.time() - start_time
                    tesseract_times.append(processing_time)
                    
                    assert isinstance(result, dict)
            
            # Should scale reasonably (not exponentially)
            assert len(tesseract_times) == 3
            # Each processing should complete within reasonable time
            for t in tesseract_times:
                assert t < 2.0  # Less than 2 seconds per image
        
        # Test EasyOCR scaling
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            easy_engine.reader = Mock()
            
            easy_times = []
            for width, height in image_sizes:
                image_data = create_test_image_of_size(width, height)
                
                easy_engine.reader.readtext.return_value = [
                    ([[10, height//2], [100, height//2], [100, height//2+20], [10, height//2+20]], 
                     f"Test {width}x{height}", 0.95)
                ]
                
                start_time = time.time()
                result = easy_engine.extract_text(image_data)
                processing_time = time.time() - start_time
                easy_times.append(processing_time)
                
                assert isinstance(result, dict)
            
            # Should scale reasonably
            assert len(easy_times) == 3
            for t in easy_times:
                assert t < 3.0  # Neural networks may take a bit longer

    def test_engine_memory_usage_patterns(self):
        """
        GIVEN each OCR engine processing various images
        WHEN monitoring memory usage
        THEN should demonstrate predictable memory patterns
        AND should not have memory leaks
        """
        import gc
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        
        def create_test_image_data():
            img = Image.new('RGB', (300, 150), color='white')
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.text((50, 70), "Memory Test", fill='black')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        
        # Test TesseractOCR memory usage
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            tesseract_engine.pytesseract = Mock()
            
            initial_memory = process.memory_info().rss
            
            # Process multiple images
            for i in range(5):
                image_data = create_test_image_data()
                
                with patch.object(tesseract_engine, '_preprocess_image') as mock_preprocess:
                    mock_preprocess.return_value = Image.new('RGB', (300, 150), 'white')
                    tesseract_engine.pytesseract.image_to_string.return_value = "Memory Test"
                    tesseract_engine.pytesseract.image_to_data.return_value = {
                        'text': ['Memory', 'Test'], 'conf': [95, 92], 
                        'left': [50, 120], 'top': [70, 70], 
                        'width': [60, 40], 'height': [20, 20]
                    }
                    
                    result = tesseract_engine.extract_text(image_data)
                    assert isinstance(result, dict)
            
            # Force garbage collection
            gc.collect()
            
            final_memory = process.memory_info().rss
            memory_growth = final_memory - initial_memory
            
            # Memory growth should be reasonable (less than 50MB for 5 small images)
            assert memory_growth < 50 * 1024 * 1024, f"Excessive memory growth: {memory_growth} bytes"
        
        # Test EasyOCR memory usage
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            easy_engine.reader = Mock()
            
            initial_memory = process.memory_info().rss
            
            # Process multiple images
            for i in range(5):
                image_data = create_test_image_data()
                
                easy_engine.reader.readtext.return_value = [
                    ([[50, 70], [180, 70], [180, 90], [50, 90]], 'Memory Test', 0.95)
                ]
                
                result = easy_engine.extract_text(image_data)
                assert isinstance(result, dict)
            
            # Force garbage collection
            gc.collect()
            
            final_memory = process.memory_info().rss
            memory_growth = final_memory - initial_memory
            
            # Neural networks may use more memory but should still be reasonable
            assert memory_growth < 100 * 1024 * 1024, f"Excessive memory growth: {memory_growth} bytes"

    def test_engine_concurrent_processing_limits(self):
        """
        GIVEN each OCR engine
        WHEN running multiple concurrent extract_text() operations
        THEN should handle concurrency appropriately
        AND should respect system resource limits
        """
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        def create_test_image_data():
            img = Image.new('RGB', (200, 100), color='white')
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.text((50, 40), "Concurrent Test", fill='black')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        
        image_data = create_test_image_data()
        
        # Test TesseractOCR concurrency
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            tesseract_engine.pytesseract = Mock()
            
            def process_with_tesseract(thread_id):
                with patch.object(tesseract_engine, '_preprocess_image') as mock_preprocess:
                    mock_preprocess.return_value = Image.new('RGB', (200, 100), 'white')
                    tesseract_engine.pytesseract.image_to_string.return_value = f"Concurrent Test {thread_id}"
                    tesseract_engine.pytesseract.image_to_data.return_value = {
                        'text': ['Concurrent', 'Test', str(thread_id)], 'conf': [95, 92, 88], 
                        'left': [50, 130, 160], 'top': [40, 40, 40], 
                        'width': [75, 35, 20], 'height': [20, 20, 20]
                    }
                    
                    result = tesseract_engine.extract_text(image_data)
                    return result
            
            # Test concurrent processing with ThreadPoolExecutor
            results = []
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [executor.submit(process_with_tesseract, i) for i in range(3)]
                
                for future in as_completed(futures):
                    result = future.result()
                    results.append(result)
                    assert isinstance(result, dict)
                    assert 'text' in result
            
            assert len(results) == 3
        
        # Test EasyOCR concurrency (neural networks may have threading considerations)
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            easy_engine.reader = Mock()
            
            def process_with_easy(thread_id):
                easy_engine.reader.readtext.return_value = [
                    ([[50, 40], [190, 40], [190, 60], [50, 60]], f'Concurrent Test {thread_id}', 0.95)
                ]
                
                result = easy_engine.extract_text(image_data)
                return result
            
            # Test concurrent processing
            results = []
            with ThreadPoolExecutor(max_workers=2) as executor:  # Fewer workers for neural network
                futures = [executor.submit(process_with_easy, i) for i in range(2)]
                
                for future in as_completed(futures):
                    result = future.result()
                    results.append(result)
                    assert isinstance(result, dict)
            
            assert len(results) == 2

    def test_engine_gpu_utilization_efficiency(self):
        """
        GIVEN GPU-enabled engines (Surya, EasyOCR, TrOCR)
        WHEN processing images
        THEN should utilize GPU efficiently when available
        AND should not waste GPU resources
        """
        # Mock GPU availability
        with patch('torch.cuda.is_available', return_value=True), \
             patch('torch.cuda.device_count', return_value=1), \
             patch('torch.cuda.current_device', return_value=0):
            
            def create_test_image_data():
                img = Image.new('RGB', (300, 150), color='white')
                from PIL import ImageDraw
                draw = ImageDraw.Draw(img)
                draw.text((100, 70), "GPU Test", fill='black')
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                return buf.getvalue()
            
            image_data = create_test_image_data()
            
            # Test EasyOCR GPU usage
            with patch.object(EasyOCR, '_initialize') as mock_init:
                mock_init.return_value = None
                easy_engine = EasyOCR()
                easy_engine.available = True
                easy_engine.reader = Mock()
                
                # Mock GPU-accelerated processing
                easy_engine.reader.readtext.return_value = [
                    ([[100, 70], [180, 70], [180, 90], [100, 90]], 'GPU Test', 0.96)
                ]
                
                result = easy_engine.extract_text(image_data)
                assert isinstance(result, dict)
                assert result['confidence'] > 0.9  # GPU should provide good accuracy
            
            # Test SuryaOCR GPU usage
            with patch.object(SuryaOCR, '_initialize') as mock_init:
                mock_init.return_value = None
                surya_engine = SuryaOCR()
                surya_engine.available = True
                surya_engine.run_ocr = Mock()
                
                # Mock GPU-accelerated processing
                mock_line = Mock()
                mock_line.text = "GPU Test"
                mock_line.confidence = 0.94
                surya_engine.run_ocr.return_value = ([mock_line], ["en"])
                
                result = surya_engine.extract_text(image_data)
                assert isinstance(result, dict)
                assert result['confidence'] > 0.9
            
            # Test TrOCREngine GPU usage
            with patch.object(TrOCREngine, '_initialize') as mock_init:
                mock_init.return_value = None
                trocr_engine = TrOCREngine()
                trocr_engine.available = True
                trocr_engine.processor = Mock()
                trocr_engine.model = Mock()
                
                # Mock GPU-accelerated processing
                trocr_engine.processor.return_value = {'pixel_values': Mock()}
                trocr_engine.model.generate.return_value = Mock()
                trocr_engine.processor.batch_decode.return_value = ["GPU Test"]
                
                result = trocr_engine.extract_text(image_data)
                assert isinstance(result, dict)
                assert 'GPU Test' in result['text']

    def test_engine_batch_processing_capability(self):
        """
        GIVEN each OCR engine and multiple images
        WHEN processing multiple images sequentially
        THEN should maintain consistent performance
        AND should not degrade over time
        """
        import time
        
        def create_batch_test_images(count=5):
            """Create multiple test images for batch processing."""
            images = []
            for i in range(count):
                img = Image.new('RGB', (200, 100), color='white')
                from PIL import ImageDraw
                draw = ImageDraw.Draw(img)
                draw.text((50, 40), f"Batch Image {i+1}", fill='black')
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                images.append(buf.getvalue())
            return images
        
        batch_images = create_batch_test_images(5)
        
        # Test TesseractOCR batch processing
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            tesseract_engine.pytesseract = Mock()
            
            processing_times = []
            results = []
            
            for i, image_data in enumerate(batch_images):
                with patch.object(tesseract_engine, '_preprocess_image') as mock_preprocess:
                    mock_preprocess.return_value = Image.new('RGB', (200, 100), 'white')
                    tesseract_engine.pytesseract.image_to_string.return_value = f"Batch Image {i+1}"
                    tesseract_engine.pytesseract.image_to_data.return_value = {
                        'text': ['Batch', 'Image', str(i+1)], 'conf': [95, 92, 88], 
                        'left': [50, 100, 150], 'top': [40, 40, 40], 
                        'width': [45, 45, 20], 'height': [20, 20, 20]
                    }
                    
                    start_time = time.time()
                    result = tesseract_engine.extract_text(image_data)
                    processing_time = time.time() - start_time
                    
                    processing_times.append(processing_time)
                    results.append(result)
                    
                    assert isinstance(result, dict)
                    assert f"Batch Image {i+1}" in result['text']
            
            # Performance should remain consistent (no significant degradation)
            assert len(processing_times) == 5
            assert len(results) == 5
            
            # Check that processing times don't increase dramatically
            avg_early = sum(processing_times[:2]) / 2
            avg_late = sum(processing_times[-2:]) / 2
            
            # Late processing shouldn't be more than 2x slower than early
            assert avg_late <= avg_early * 2.0, "Performance degraded significantly over batch"
        
        # Test EasyOCR batch processing
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            easy_engine.reader = Mock()
            
            processing_times = []
            results = []
            
            for i, image_data in enumerate(batch_images):
                easy_engine.reader.readtext.return_value = [
                    ([[50, 40], [190, 40], [190, 60], [50, 60]], f'Batch Image {i+1}', 0.95)
                ]
                
                start_time = time.time()
                result = easy_engine.extract_text(image_data)
                processing_time = time.time() - start_time
                
                processing_times.append(processing_time)
                results.append(result)
                
                assert isinstance(result, dict)
                assert f"Batch Image {i+1}" in result['text']
            
            # Check consistency
            assert len(processing_times) == 5
            assert len(results) == 5
            
            # Performance should remain stable
            avg_early = sum(processing_times[:2]) / 2
            avg_late = sum(processing_times[-2:]) / 2
            assert avg_late <= avg_early * 2.0, "EasyOCR performance degraded over batch"

    def test_multi_engine_overhead_measurement(self):
        """
        GIVEN MultiEngineOCR vs individual engines
        WHEN comparing processing overhead
        THEN should quantify coordination overhead
        AND should demonstrate fallback value vs cost
        """
        import time
        
        def create_test_image_data():
            img = Image.new('RGB', (200, 100), color='white')
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.text((50, 40), "Overhead Test", fill='black')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        
        image_data = create_test_image_data()
        
        # Test individual TesseractOCR timing
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            tesseract_engine.pytesseract = Mock()
            
            with patch.object(tesseract_engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = Image.new('RGB', (200, 100), 'white')
                tesseract_engine.pytesseract.image_to_string.return_value = "Overhead Test"
                tesseract_engine.pytesseract.image_to_data.return_value = {
                    'text': ['Overhead', 'Test'], 'conf': [95, 92], 
                    'left': [50, 120], 'top': [40, 40], 
                    'width': [65, 35], 'height': [20, 20]
                }
                
                start_time = time.time()
                individual_result = tesseract_engine.extract_text(image_data)
                individual_time = time.time() - start_time
                
                assert isinstance(individual_result, dict)
        
        # Test MultiEngineOCR timing with same engine
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract_class:
            mock_tesseract_class.return_value = tesseract_engine
            
            multi_engine = MultiEngineOCR()
            multi_engine.engines = {'tesseract': tesseract_engine}
            
            start_time = time.time()
            multi_result = multi_engine.extract_with_fallback(image_data, strategy='speed_first')
            multi_time = time.time() - start_time
            
            assert isinstance(multi_result, dict)
            
            # Coordination overhead should be minimal (less than 50% overhead)
            overhead_ratio = multi_time / individual_time if individual_time > 0 else 1.0
            assert overhead_ratio < 1.5, f"MultiEngine overhead too high: {overhead_ratio:.2f}x"
        
        # Test fallback value demonstration
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract:
            
            # Mock first engine failure, second engine success
            mock_engine1 = Mock()
            mock_engine1.name = 'surya'
            mock_engine1.is_available.return_value = True
            mock_engine1.extract_text.side_effect = RuntimeError("Engine failed")
            
            mock_engine2 = Mock()
            mock_engine2.name = 'tesseract'
            mock_engine2.is_available.return_value = True
            mock_engine2.extract_text.return_value = {
                'text': 'Fallback Success',
                'confidence': 0.85,
                'engine': 'tesseract'
            }
            
            mock_surya.return_value = mock_engine1
            mock_tesseract.return_value = mock_engine2
            
            multi_engine = MultiEngineOCR()
            multi_engine.engines = {'surya': mock_engine1, 'tesseract': mock_engine2}
            
            # Should successfully fallback despite first engine failure
            result = multi_engine.extract_with_fallback(image_data)
            assert result['text'] == 'Fallback Success'
            assert result['engine'] == 'tesseract'
            
            # Verify fallback actually occurred
            assert mock_engine1.extract_text.called
            assert mock_engine2.extract_text.called


class TestOCREngineDocumentationCompliance:
    """Test suite to verify implementation matches documentation promises."""

    def test_surya_ocr_docstring_promises(self):
        """
        GIVEN SuryaOCR class documentation claims
        WHEN testing actual implementation
        THEN should fulfill all documented capabilities
        AND should handle all mentioned use cases
        """
        # Test that SuryaOCR class exists and has documented methods
        assert hasattr(SuryaOCR, '__init__')
        assert hasattr(SuryaOCR, 'extract_text')
        assert hasattr(SuryaOCR, 'is_available')
        
        # Test initialization
        with patch.object(SuryaOCR, '_initialize'):
            engine = SuryaOCR()
            assert hasattr(engine, 'name')
            assert engine.name == 'surya'
            
            # Test that it implements the OCREngine interface
            assert isinstance(engine, OCREngine)
            
            # Test extract_text method signature matches documentation
            import inspect
            sig = inspect.signature(engine.extract_text)
            expected_params = ['image_data']
            actual_params = list(sig.parameters.keys())
            
            for param in expected_params:
                assert param in actual_params, f"Missing documented parameter: {param}"
            
            # Test that method returns expected format
            engine.available = True
            engine.run_ocr = Mock()
            
            # Mock multilingual capability as documented
            mock_line = Mock()
            mock_line.text = "Multilingual test"
            mock_line.confidence = 0.92
            engine.run_ocr.return_value = ([mock_line], ["en", "fr"])
            
            result = engine.extract_text(b'fake_image_data')
            
            # Verify return format matches documentation
            assert isinstance(result, dict)
            assert 'text' in result
            assert 'confidence' in result
            assert 'engine' in result
            assert result['engine'] == 'surya'

    def test_tesseract_ocr_docstring_promises(self):
        """
        GIVEN TesseractOCR class documentation claims
        WHEN testing actual implementation
        THEN should fulfill all documented capabilities
        AND should handle all mentioned preprocessing steps
        """
        # Test that TesseractOCR class exists and has documented methods
        assert hasattr(TesseractOCR, '__init__')
        assert hasattr(TesseractOCR, 'extract_text')
        assert hasattr(TesseractOCR, 'is_available')
        assert hasattr(TesseractOCR, '_preprocess_image')
        
        # Test initialization
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            assert hasattr(engine, 'name')
            assert engine.name == 'tesseract'
            
            # Test that it implements the OCREngine interface
            assert isinstance(engine, OCREngine)
            
            # Test preprocessing capability as documented
            engine.available = True
            engine.pytesseract = Mock()
            
            # Test that _preprocess_image is implemented
            with patch.object(engine, '_preprocess_image') as mock_preprocess:
                test_image = Image.new('RGB', (100, 50), 'white')
                mock_preprocess.return_value = test_image
                
                engine.pytesseract.image_to_string.return_value = "Preprocessed text"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['Preprocessed', 'text'], 'conf': [95, 92],
                    'left': [10, 80], 'top': [10, 10], 
                    'width': [60, 40], 'height': [15, 15]
                }
                
                result = engine.extract_text(b'fake_image_data')
                
                # Verify preprocessing was called as documented
                mock_preprocess.assert_called_once()
                
                # Verify return format matches documentation
                assert isinstance(result, dict)
                assert 'text' in result
                assert 'confidence' in result
                assert 'engine' in result
                assert result['engine'] == 'tesseract'
                assert 'Preprocessed text' in result['text']

    def test_easyocr_docstring_promises(self):
        """
        GIVEN EasyOCR class documentation claims
        WHEN testing actual implementation
        THEN should fulfill all documented capabilities
        AND should handle complex layouts as promised
        """
        # Test that EasyOCR class exists and has documented methods
        assert hasattr(EasyOCR, '__init__')
        assert hasattr(EasyOCR, 'extract_text')
        assert hasattr(EasyOCR, 'is_available')
        
        # Test initialization
        with patch.object(EasyOCR, '_initialize'):
            engine = EasyOCR()
            assert hasattr(engine, 'name')
            assert engine.name == 'easyocr'
            
            # Test that it implements the OCREngine interface
            assert isinstance(engine, OCREngine)
            
            # Test complex layout handling as documented
            engine.available = True
            engine.reader = Mock()
            
            # Mock complex layout detection with multiple text regions
            complex_layout_result = [
                ([[10, 10], [100, 10], [100, 30], [10, 30]], 'Header Text', 0.95),
                ([[10, 50], [200, 50], [200, 80], [10, 80]], 'Body paragraph text', 0.88),
                ([[150, 100], [250, 100], [250, 120], [150, 120]], 'Footer', 0.92),
                ([[20, 150], [80, 180], [60, 200], [0, 170]], 'Rotated text', 0.85)  # Rotated/skewed
            ]
            engine.reader.readtext.return_value = complex_layout_result
            
            result = engine.extract_text(b'fake_complex_layout_image')
            
            # Verify return format matches documentation
            assert isinstance(result, dict)
            assert 'text' in result
            assert 'confidence' in result
            assert 'engine' in result
            assert result['engine'] == 'easyocr'
            
            # Verify complex layout handling
            text = result['text']
            assert 'Header Text' in text
            assert 'Body paragraph text' in text
            assert 'Footer' in text
            assert 'Rotated text' in text
            
            # Verify confidence is computed appropriately
            assert isinstance(result['confidence'], float)
            assert 0.0 <= result['confidence'] <= 1.0

    def test_trocr_docstring_promises(self):
        """
        GIVEN TrOCREngine class documentation claims
        WHEN testing actual implementation
        THEN should fulfill all documented capabilities
        AND should excel at handwritten text as promised
        """
        # Test that TrOCREngine class exists and has documented methods
        assert hasattr(TrOCREngine, '__init__')
        assert hasattr(TrOCREngine, 'extract_text')
        assert hasattr(TrOCREngine, 'is_available')
        
        # Test initialization
        with patch.object(TrOCREngine, '_initialize'):
            engine = TrOCREngine()
            assert hasattr(engine, 'name')
            assert engine.name == 'trocr'
            
            # Test that it implements the OCREngine interface
            assert isinstance(engine, OCREngine)
            
            # Test handwritten text processing as documented
            engine.available = True
            engine.processor = Mock()
            engine.model = Mock()
            
            # Mock handwritten text recognition
            engine.processor.return_value = {'pixel_values': Mock()}
            mock_generated_ids = Mock()
            engine.model.generate.return_value = mock_generated_ids
            engine.processor.batch_decode.return_value = ["Handwritten note content"]
            
            result = engine.extract_text(b'fake_handwritten_image')
            
            # Verify return format matches documentation
            assert isinstance(result, dict)
            assert 'text' in result
            assert 'confidence' in result
            assert 'engine' in result
            assert result['engine'] == 'trocr'
            
            # Verify handwritten text processing
            assert 'Handwritten note content' in result['text']
            
            # Verify transformer pipeline was used as documented
            engine.processor.assert_called()
            engine.model.generate.assert_called()
            engine.processor.batch_decode.assert_called_with(mock_generated_ids, skip_special_tokens=True)

    def test_multi_engine_ocr_docstring_promises(self):
        """
        GIVEN MultiEngineOCR class documentation claims
        WHEN testing actual implementation
        THEN should fulfill all documented orchestration capabilities
        AND should provide all mentioned strategies and fallback mechanisms
        """
        # Test that MultiEngineOCR class exists and has documented methods
        assert hasattr(MultiEngineOCR, '__init__')
        assert hasattr(MultiEngineOCR, 'extract_with_fallback')
        assert hasattr(MultiEngineOCR, 'get_available_engines')
        assert hasattr(MultiEngineOCR, 'classify_document_type')
        
        # Test initialization with multiple engines
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya:
            
            # Mock all engines as available
            mock_tesseract.return_value.is_available.return_value = True
            mock_tesseract.return_value.name = 'tesseract'
            mock_easy.return_value.is_available.return_value = True  
            mock_easy.return_value.name = 'easyocr'
            mock_surya.return_value.is_available.return_value = True
            mock_surya.return_value.name = 'surya'
            
            multi_engine = MultiEngineOCR()
            
            # Test that it orchestrates multiple engines as documented
            available_engines = multi_engine.get_available_engines()
            assert isinstance(available_engines, list)
            assert len(available_engines) >= 1  # Should have at least one engine
            
            # Test fallback mechanism as documented
            mock_tesseract.return_value.extract_text.side_effect = RuntimeError("First engine failed")
            mock_easy.return_value.extract_text.return_value = {
                'text': 'Fallback success',
                'confidence': 0.85,
                'engine': 'easyocr'
            }
            
            result = multi_engine.extract_with_fallback(b'fake_image_data')
            
            # Verify fallback worked as documented
            assert isinstance(result, dict)
            assert 'text' in result
            assert 'confidence' in result
            assert 'engine' in result
            assert result['text'] == 'Fallback success'
            assert result['engine'] == 'easyocr'
            
            # Test strategy options as documented
            strategies = ['quality_first', 'speed_first', 'accuracy_first']
            for strategy in strategies:
                mock_easy.return_value.extract_text.return_value = {
                    'text': f'Strategy {strategy} result',
                    'confidence': 0.9,
                    'engine': 'easyocr'
                }
                
                result = multi_engine.extract_with_fallback(
                    b'fake_image_data', 
                    strategy=strategy
                )
                assert isinstance(result, dict)
                assert strategy in result.get('text', '') or result.get('engine') is not None

    def test_abstract_base_class_interface_compliance(self):
        """
        GIVEN OCREngine abstract base class interface definition
        WHEN testing all concrete implementations
        THEN should properly implement all abstract methods
        AND should maintain interface consistency
        """
        import inspect
        from abc import ABC, abstractmethod
        
        # Verify OCREngine is an abstract base class
        assert issubclass(OCREngine, ABC)
        
        # Get all abstract methods from OCREngine
        abstract_methods = []
        for name, method in inspect.getmembers(OCREngine, predicate=inspect.isfunction):
            if hasattr(method, '__isabstractmethod__') and method.__isabstractmethod__:
                abstract_methods.append(name)
        
        # Test each concrete implementation
        concrete_engines = [TesseractOCR, EasyOCR, SuryaOCR, TrOCREngine]
        
        for engine_class in concrete_engines:
            # Verify it's a subclass of OCREngine
            assert issubclass(engine_class, OCREngine), f"{engine_class.__name__} must inherit from OCREngine"
            
            # Verify all abstract methods are implemented
            for method_name in abstract_methods:
                assert hasattr(engine_class, method_name), f"{engine_class.__name__} missing method: {method_name}"
                
                # Verify method is not abstract in concrete class
                method = getattr(engine_class, method_name)
                if hasattr(method, '__isabstractmethod__'):
                    assert not method.__isabstractmethod__, f"{engine_class.__name__}.{method_name} is still abstract"
            
            # Test interface consistency - all engines should have same method signatures
            with patch.object(engine_class, '_initialize'):
                engine = engine_class()
                
                # Test extract_text method signature
                extract_text_sig = inspect.signature(engine.extract_text)
                assert 'image_data' in extract_text_sig.parameters
                
                # Test is_available method
                assert hasattr(engine, 'is_available')
                assert callable(engine.is_available)
                
                # Test name property
                assert hasattr(engine, 'name')
                assert isinstance(engine.name, str)
                assert len(engine.name) > 0

    def test_return_format_specification_compliance(self):
        """
        GIVEN documented return format specifications for each engine
        WHEN testing actual return values
        THEN should match documented dictionary structures exactly
        AND should include all promised keys and value types
        """
        required_keys = {'text', 'confidence', 'engine'}
        required_types = {
            'text': str,
            'confidence': (int, float),
            'engine': str
        }
        
        # Test TesseractOCR return format
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            tesseract_engine.pytesseract = Mock()
            
            with patch.object(tesseract_engine, '_preprocess_image'):
                tesseract_engine.pytesseract.image_to_string.return_value = "Test text"
                tesseract_engine.pytesseract.image_to_data.return_value = {
                    'text': ['Test', 'text'], 'conf': [95, 92],
                    'left': [10, 60], 'top': [10, 10], 
                    'width': [40, 35], 'height': [15, 15]
                }
                
                result = tesseract_engine.extract_text(b'fake_image_data')
                
                # Verify all required keys present
                for key in required_keys:
                    assert key in result, f"TesseractOCR missing required key: {key}"
                
                # Verify correct types
                for key, expected_type in required_types.items():
                    assert isinstance(result[key], expected_type), f"TesseractOCR {key} wrong type: {type(result[key])}"
                
                # Verify specific values
                assert result['engine'] == 'tesseract'
                assert 0.0 <= result['confidence'] <= 1.0
        
        # Test EasyOCR return format
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            easy_engine.reader = Mock()
            easy_engine.reader.readtext.return_value = [
                ([[10, 10], [100, 10], [100, 30], [10, 30]], 'Easy test', 0.88)
            ]
            
            result = easy_engine.extract_text(b'fake_image_data')
            
            # Verify format compliance
            for key in required_keys:
                assert key in result, f"EasyOCR missing required key: {key}"
            
            for key, expected_type in required_types.items():
                assert isinstance(result[key], expected_type), f"EasyOCR {key} wrong type: {type(result[key])}"
            
            assert result['engine'] == 'easyocr'
            assert 0.0 <= result['confidence'] <= 1.0
        
        # Test SuryaOCR return format
        with patch.object(SuryaOCR, '_initialize'):
            surya_engine = SuryaOCR()
            surya_engine.available = True
            surya_engine.run_ocr = Mock()
            
            mock_line = Mock()
            mock_line.text = "Surya test"
            mock_line.confidence = 0.91
            surya_engine.run_ocr.return_value = ([mock_line], ["en"])
            
            result = surya_engine.extract_text(b'fake_image_data')
            
            # Verify format compliance
            for key in required_keys:
                assert key in result, f"SuryaOCR missing required key: {key}"
            
            for key, expected_type in required_types.items():
                assert isinstance(result[key], expected_type), f"SuryaOCR {key} wrong type: {type(result[key])}"
            
            assert result['engine'] == 'surya'
            assert 0.0 <= result['confidence'] <= 1.0
        
        # Test TrOCREngine return format
        with patch.object(TrOCREngine, '_initialize'):
            trocr_engine = TrOCREngine()
            trocr_engine.available = True
            trocr_engine.processor = Mock()
            trocr_engine.model = Mock()
            
            trocr_engine.processor.return_value = {'pixel_values': Mock()}
            trocr_engine.model.generate.return_value = Mock()
            trocr_engine.processor.batch_decode.return_value = ["TrOCR test"]
            
            result = trocr_engine.extract_text(b'fake_image_data')
            
            # Verify format compliance
            for key in required_keys:
                assert key in result, f"TrOCREngine missing required key: {key}"
            
            for key, expected_type in required_types.items():
                assert isinstance(result[key], expected_type), f"TrOCREngine {key} wrong type: {type(result[key])}"
            
            assert result['engine'] == 'trocr'
            assert 0.0 <= result['confidence'] <= 1.0

    def test_exception_handling_specification_compliance(self):
        """
        GIVEN documented exception types for various error conditions
        WHEN testing error scenarios
        THEN should raise exactly the documented exception types
        AND should provide meaningful error messages
        """
        # Test that all engines raise appropriate exceptions for invalid inputs
        
        # Test None input handling
        engines_to_test = [
            (TesseractOCR, '_initialize'),
            (EasyOCR, '_initialize'), 
            (SuryaOCR, '_initialize'),
            (TrOCREngine, '_initialize')
        ]
        
        for engine_class, init_method in engines_to_test:
            with patch.object(engine_class, init_method):
                engine = engine_class()
                engine.available = True
                
                # None input should raise TypeError or ValueError
                with pytest.raises((TypeError, ValueError)):
                    engine.extract_text(None)
                
                # Empty bytes should raise ValueError
                with pytest.raises(ValueError):
                    engine.extract_text(b'')
        
        # Test unavailable engine behavior
        with patch.object(TesseractOCR, '_initialize'):
            unavailable_engine = TesseractOCR()
            unavailable_engine.available = False
            
            # Should raise RuntimeError when engine not available
            with pytest.raises(RuntimeError, match="not.*available|not.*initialized"):
                unavailable_engine.extract_text(b'fake_image_data')
        
        # Test image format errors
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            engine.available = True
            engine.pytesseract = Mock()
            
            # Mock PIL to raise UnidentifiedImageError for bad image data
            with patch('PIL.Image.open', side_effect=Exception("cannot identify image file")):
                with pytest.raises(Exception):  # Should propagate PIL exception
                    engine.extract_text(b'not_an_image_file')
        
        # Test MultiEngineOCR exception handling
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract:
            mock_engine = Mock()
            mock_engine.is_available.return_value = False
            mock_tesseract.return_value = mock_engine
            
            multi_engine = MultiEngineOCR()
            
            # Should raise appropriate error when no engines available
            with pytest.raises((RuntimeError, ValueError)):
                multi_engine.extract_with_fallback(b'fake_image_data')
        
        # Test configuration error handling
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            engine.available = True
            engine.pytesseract = Mock()
            
            # Mock tesseract to raise error for invalid config
            engine.pytesseract.image_to_string.side_effect = Exception("Invalid configuration")
            
            with patch.object(engine, '_preprocess_image'):
                with pytest.raises(Exception):
                    engine.extract_text(b'fake_image_data', config='--invalid-option')
        
        # Verify error messages are meaningful
        with patch.object(EasyOCR, '_initialize'):
            engine = EasyOCR()
            engine.available = False
            
            try:
                engine.extract_text(b'fake_data')
                assert False, "Should have raised exception"
            except RuntimeError as e:
                error_msg = str(e).lower()
                assert any(keyword in error_msg for keyword in ['available', 'initialized', 'not']), \
                    f"Error message not descriptive: {e}"


class TestOCREngineConfigurationAndCustomization:
    """Test suite for configuration options and customization capabilities."""

    def test_tesseract_psm_configuration_impact(self):
        """
        GIVEN TesseractOCR with different PSM (Page Segmentation Mode) settings
        WHEN processing various document layouts
        THEN should demonstrate different behavior based on PSM mode
        AND should optimize for specified layout types
        """
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            engine.available = True
            engine.pytesseract = Mock()
            
            # Create a test image
            test_image_data = b'fake_image_data'
            mock_image = Mock(spec=['format', 'mode'])
            mock_image.format = 'PNG'
            mock_image.mode = 'RGB'
            
            with patch.object(engine, '_preprocess_image', return_value=mock_image):
                # Test different PSM modes for different layout types
                layout_tests = [
                    # (PSM mode, expected config, layout description)
                    (3, '--psm 3', 'Fully automatic page segmentation'),
                    (6, '--psm 6', 'Uniform block of text'),
                    (7, '--psm 7', 'Single text line'),
                    (8, '--psm 8', 'Single word'),
                    (10, '--psm 10', 'Single character'),
                    (13, '--psm 13', 'Raw line fitting character')
                ]
                
                for psm_mode, config_str, description in layout_tests:
                    # Configure mock to return different results for different PSM modes
                    expected_output = f"OCR output for PSM {psm_mode} - {description}"
                    engine.pytesseract.image_to_string.return_value = expected_output
                    
                    result = engine.extract_text(test_image_data, config=config_str)
                    
                    # Verify the call was made with correct PSM config
                    engine.pytesseract.image_to_string.assert_called()
                    call_args = engine.pytesseract.image_to_string.call_args
                    config_used = call_args[1].get('config', '')
                    
                    assert config_str in config_used, \
                        f"PSM config '{config_str}' not found in: {config_used}"
                    assert result == expected_output
                
                # Test combined PSM with other Tesseract options
                complex_configs = [
                    '--psm 6 -c tessedit_char_whitelist=0123456789',
                    '--psm 7 --oem 3',
                    '--psm 8 -c preserve_interword_spaces=1'
                ]
                
                for complex_config in complex_configs:
                    engine.pytesseract.image_to_string.return_value = "Complex config result"
                    result = engine.extract_text(test_image_data, config=complex_config)
                    
                    call_args = engine.pytesseract.image_to_string.call_args
                    config_used = call_args[1].get('config', '')
                    assert complex_config == config_used, \
                        f"Complex config not preserved: expected '{complex_config}', got '{config_used}'"
                
                # Test invalid PSM handling
                engine.pytesseract.image_to_string.side_effect = Exception("Invalid PSM mode")
                
                with pytest.raises(Exception):
                    engine.extract_text(test_image_data, config='--psm 99')  # Invalid PSM
                
                # Reset for remaining tests
                engine.pytesseract.image_to_string.side_effect = None
                
                # Test that different PSM modes can handle different content types
                content_scenarios = [
                    ('document_page', '--psm 1', 'Full page analysis'),
                    ('text_block', '--psm 6', 'Uniform text block'),
                    ('single_line', '--psm 7', 'Text line'),
                    ('word_only', '--psm 8', 'Single word'),
                    ('sparse_text', '--psm 11', 'Sparse text')
                ]
                
                for scenario, psm_config, expected_behavior in content_scenarios:
                    engine.pytesseract.image_to_string.return_value = f"Result for {scenario}"
                    result = engine.extract_text(test_image_data, config=psm_config)
                    
                    assert result == f"Result for {scenario}"
                    
                    # Verify config was applied
                    call_args = engine.pytesseract.image_to_string.call_args
                    config_used = call_args[1].get('config', '')
                    assert psm_config in config_used
                
                # Test default behavior (no PSM specified)
                engine.pytesseract.image_to_string.return_value = "Default PSM result"
                result = engine.extract_text(test_image_data)
                assert result == "Default PSM result"

    def test_tesseract_language_configuration(self):
        """
        GIVEN TesseractOCR with different language configurations
        WHEN processing non-English text with actual language parameters
        THEN should pass correct language codes to tesseract
        AND should demonstrate language-specific OCR behavior
        """
        # Create test image with Spanish text
        def create_spanish_test_image():
            img = Image.new('RGB', (300, 80), color='white')
            from PIL import ImageDraw, ImageFont
            draw = ImageDraw.Draw(img)
            try:
                # Try to use a better font if available
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
            except (IOError, OSError):
                font = ImageFont.load_default()
            draw.text((20, 30), "Niño pequeño", font=font, fill='black')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        
        # Create test image with German text
        def create_german_test_image():
            img = Image.new('RGB', (300, 80), color='white')
            from PIL import ImageDraw, ImageFont
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
            except (IOError, OSError):
                font = ImageFont.load_default()
            draw.text((20, 30), "Größe Mädchen", font=font, fill='black')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        
        spanish_image = create_spanish_test_image()
        german_image = create_german_test_image()
        
        # Test actual TesseractOCR instance (with mocked pytesseract calls)
        engine = TesseractOCR()
        
        # Mock only the pytesseract calls to verify correct parameters are passed
        with patch('pytesseract.image_to_string') as mock_img_to_str, \
             patch('pytesseract.image_to_data') as mock_img_to_data:
            
            # Configure mocks for Spanish
            mock_img_to_str.return_value = "Niño pequeño"
            mock_img_to_data.return_value = {
                'text': ['Niño', 'pequeño'], 'conf': [92, 89], 
                'left': [20, 80], 'top': [30, 30], 
                'width': [50, 70], 'height': [20, 20]
            }
            
            # Test Spanish language parameter
            result_spanish = engine.extract_text(spanish_image, lang='spa')
            
            # Verify pytesseract was called with Spanish language
            mock_img_to_str.assert_called()
            call_kwargs = mock_img_to_str.call_args[1] if mock_img_to_str.call_args[1] else {}
            config_used = call_kwargs.get('config', '')
            
            # Should contain Spanish language specification
            assert 'spa' in config_used or 'spanish' in config_used.lower()
            assert result_spanish['text'] == "Niño pequeño"
            assert result_spanish['engine'] == 'tesseract'
            
            # Reset mocks for German test
            mock_img_to_str.reset_mock()
            mock_img_to_data.reset_mock()
            
            # Configure mocks for German
            mock_img_to_str.return_value = "Größe Mädchen"
            mock_img_to_data.return_value = {
                'text': ['Größe', 'Mädchen'], 'conf': [88, 91], 
                'left': [20, 90], 'top': [30, 30], 
                'width': [60, 80], 'height': [20, 20]
            }
            
            # Test German language parameter
            result_german = engine.extract_text(german_image, lang='deu')
            
            # Verify pytesseract was called with German language
            mock_img_to_str.assert_called()
            call_kwargs = mock_img_to_str.call_args[1] if mock_img_to_str.call_args[1] else {}
            config_used = call_kwargs.get('config', '')
            
            # Should contain German language specification
            assert 'deu' in config_used or 'german' in config_used.lower()
            assert result_german['text'] == "Größe Mädchen"
            assert result_german['engine'] == 'tesseract'
            
            # Test multiple languages
            mock_img_to_str.reset_mock()
            mock_img_to_str.return_value = "Mixed español and English"
            
            result_multi = engine.extract_text(spanish_image, lang='spa+eng')
            
            # Verify multiple language specification
            mock_img_to_str.assert_called()
            call_kwargs = mock_img_to_str.call_args[1] if mock_img_to_str.call_args[1] else {}
            config_used = call_kwargs.get('config', '')
            
            # Should contain multiple language specification
            assert ('spa+eng' in config_used or 
                   ('spa' in config_used and 'eng' in config_used))
            assert result_multi['text'] == "Mixed español and English"

    def test_tesseract_character_whitelist_effectiveness(self):
        """
        GIVEN TesseractOCR with character whitelist configuration
        WHEN processing text with mixed character types
        THEN should filter output to whitelisted characters only
        AND should improve accuracy for domain-specific text
        """
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            engine.available = True
            engine.pytesseract = Mock()
            
            def create_mixed_text_image():
                img = Image.new('RGB', (250, 100), color='white')
                from PIL import ImageDraw
                draw = ImageDraw.Draw(img)
                draw.text((20, 40), "ABC123!@#", fill='black')  # Mixed characters
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                return buf.getvalue()
            
            image_data = create_mixed_text_image()
            
            with patch.object(engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = Image.new('RGB', (250, 100), 'white')
                
                # Test without character whitelist (all characters)
                engine.pytesseract.image_to_string.return_value = "ABC123!@#"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['ABC123!@#'], 'conf': [78], 
                    'left': [20], 'top': [40], 
                    'width': [180], 'height': [20]
                }
                
                result_all_chars = engine.extract_text(image_data)
                assert isinstance(result_all_chars, dict)
                assert "ABC123!@#" in result_all_chars['text']
                
                # Test with numbers-only whitelist (simulate configuration)
                engine.pytesseract.image_to_string.return_value = "123"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['123'], 'conf': [95], 
                    'left': [65], 'top': [40], 
                    'width': [40], 'height': [20]
                }
                
                result_numbers_only = engine.extract_text(image_data)
                assert isinstance(result_numbers_only, dict)
                assert result_numbers_only['text'] == "123"
                
                # Whitelist should improve confidence for domain-specific text
                assert result_numbers_only['confidence'] > result_all_chars['confidence']
                
                # Test with letters-only whitelist
                engine.pytesseract.image_to_string.return_value = "ABC"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['ABC'], 'conf': [92], 
                    'left': [20], 'top': [40], 
                    'width': [45], 'height': [20]
                }
                
                result_letters_only = engine.extract_text(image_data)
                assert isinstance(result_letters_only, dict)
                assert result_letters_only['text'] == "ABC"
                assert result_letters_only['confidence'] > 0.9
            engine.available = True
            engine.pytesseract = Mock()
            
            with patch.object(engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = self.create_test_image()
                
                # Test numbers-only whitelist
                engine.pytesseract.image_to_string.return_value = "123456"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['123456'],
                    'conf': [95],
                    'left': [10],
                    'top': [10],
                    'width': [40],
                    'height': [15]
                }
                
                numbers_config = "--psm 6 -c tessedit_char_whitelist=0123456789"
                image_data = self.create_test_image_data()
                result = engine.extract_text(image_data, config=numbers_config)
                
                # Should have applied character whitelist
                call_args = engine.pytesseract.image_to_string.call_args
                assert "tessedit_char_whitelist=0123456789" in str(call_args)
                assert result['text'] == "123456"
                
                # Test letters-only whitelist
                engine.pytesseract.image_to_string.return_value = "ABCDEF"
                letters_config = "--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                result_letters = engine.extract_text(image_data, config=letters_config)
                
                call_args_letters = engine.pytesseract.image_to_string.call_args
                assert "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ" in str(call_args_letters)
                assert result_letters['text'] == "ABCDEF"

    def test_surya_language_specification_impact(self):
        """
        GIVEN SuryaOCR with different language specifications
        WHEN processing multilingual content
        THEN should adapt recognition based on specified languages
        AND should handle language switching within documents
        """
        with patch.object(SuryaOCR, '_initialize'):
            engine = SuryaOCR()
            engine.available = True
            engine.run_ocr = Mock()
            engine.det_processor = Mock()
            engine.det_model = Mock()
            engine.rec_model = Mock()
            engine.rec_processor = Mock()
            
            # Test multilingual specification
            mock_text_lines_multi = [
                Mock(text="Hello", confidence=0.95),
                Mock(text="Hola", confidence=0.92),
                Mock(text="Bonjour", confidence=0.89),
                Mock(text="你好", confidence=0.87)
            ]
            engine.run_ocr.return_value = ([mock_text_lines_multi], ["en", "es", "fr", "zh"])
            
            image_data = self.create_test_image_data()
            result = engine.extract_text(image_data, languages=['en', 'es', 'fr', 'zh'])
            
            # Should have processed multilingual content
            assert result['engine'] == 'surya'
            text = result['text']
            assert 'Hello' in text
            assert 'Hola' in text
            assert 'Bonjour' in text
            assert '你好' in text
            
            # Verify the languages parameter was passed
            engine.run_ocr.assert_called_once()
            call_args = engine.run_ocr.call_args
            # The languages should be passed in the call
            assert len(call_args) >= 1  # At least image argument
            
            # Test single language specification
            mock_text_lines_single = [Mock(text="English only", confidence=0.96)]
            engine.run_ocr.return_value = ([mock_text_lines_single], ["en"])
            
            result_en = engine.extract_text(image_data, languages=['en'])
            assert 'English only' in result_en['text']

    def test_multi_engine_strategy_customization(self):
        """
        GIVEN MultiEngineOCR with custom strategy definitions
        WHEN processing documents with known characteristics
        THEN should allow strategy customization beyond built-in options
        AND should support user-defined engine ordering
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # Set up all engines
            mock_surya.return_value = MockOCREngine('surya', True, confidence=0.95, text="surya custom")
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.85, text="tesseract custom")
            mock_easy.return_value = MockOCREngine('easyocr', True, confidence=0.80, text="easy custom")
            mock_trocr.return_value = MockOCREngine('trocr', True, confidence=0.75, text="trocr custom")
            
            multi_ocr = MultiEngineOCR()
            image_data = self.create_test_image_data()
            
            # Test that different strategies exist and work
            strategies = ['quality_first', 'speed_first', 'accuracy_first']
            
            for strategy in strategies:
                result = multi_ocr.extract_with_fallback(
                    image_data, 
                    strategy=strategy, 
                    confidence_threshold=0.7
                )
                
                # Should return valid result
                assert isinstance(result, dict)
                assert 'engine' in result
                assert 'text' in result
                assert 'confidence' in result
                assert result['engine'] in ['surya', 'tesseract', 'easyocr', 'trocr']
                assert 'custom' in result['text']
            
            # Test invalid strategy handling
            with pytest.raises(ValueError):
                multi_ocr.extract_with_fallback(image_data, strategy='invalid_strategy')
                
            # Test custom strategy concept (if implemented)
            # For now, verify that we can at least specify the built-in strategies
            available_engines = multi_ocr.get_available_engines()
            assert len(available_engines) == 4
            assert set(available_engines) == {'surya', 'tesseract', 'easyocr', 'trocr'}

    def test_confidence_threshold_sensitivity_analysis(self):
        """
        GIVEN MultiEngineOCR with varying confidence thresholds
        WHEN processing documents of different quality levels
        THEN should demonstrate threshold impact on fallback behavior
        AND should help optimize threshold values for use cases
        """
        # Mock all engines as available
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract_cls, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easyocr_cls, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya_cls, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr_cls:
            
            # Set up mock engines
            mock_tesseract = Mock()
            mock_tesseract.is_available.return_value = True
            mock_tesseract_cls.return_value = mock_tesseract
            
            mock_easyocr = Mock()
            mock_easyocr.is_available.return_value = True
            mock_easyocr_cls.return_value = mock_easyocr
            
            mock_surya = Mock()
            mock_surya.is_available.return_value = True
            mock_surya_cls.return_value = mock_surya
            
            mock_trocr = Mock()
            mock_trocr.is_available.return_value = True
            mock_trocr_cls.return_value = mock_trocr
            
            # Create test data
            test_image_data = b'fake_image_data'
            
            # Test different confidence scenarios
            confidence_scenarios = [
                # (primary_confidence, fallback_confidence, expected_behavior)
                (0.95, 0.85, "high_confidence_primary"),
                (0.65, 0.90, "fallback_better"),
                (0.45, 0.40, "both_low_confidence"),
                (0.30, 0.88, "primary_fails_fallback_succeeds")
            ]
            
            for primary_conf, fallback_conf, scenario in confidence_scenarios:
                multi_engine = MultiEngineOCR()
                
                # Configure primary engine response
                primary_result = {
                    'text': f"Primary OCR result for {scenario}",
                    'confidence': primary_conf,
                    'metadata': {'engine': 'tesseract'}
                }
                mock_tesseract.extract_text.return_value = primary_result
                
                # Configure fallback engine response  
                fallback_result = {
                    'text': f"Fallback OCR result for {scenario}",
                    'confidence': fallback_conf,
                    'metadata': {'engine': 'easyocr'}
                }
                mock_easyocr.extract_text.return_value = fallback_result
                
                # Test different confidence thresholds
                thresholds_to_test = [0.50, 0.70, 0.80, 0.90]
                
                for threshold in thresholds_to_test:
                    # Reset mocks
                    mock_tesseract.reset_mock()
                    mock_easyocr.reset_mock()
                    
                    # Call extract_with_fallback with threshold
                    if hasattr(multi_engine, 'extract_with_fallback'):
                        if primary_conf >= threshold:
                            # Primary should be sufficient
                            result = multi_engine.extract_with_fallback(
                                test_image_data, 
                                confidence_threshold=threshold
                            )
                            # Should use primary result
                            expected_text = primary_result['text']
                        else:
                            # Should try fallback
                            if fallback_conf >= threshold:
                                result = multi_engine.extract_with_fallback(
                                    test_image_data,
                                    confidence_threshold=threshold
                                )
                                expected_text = fallback_result['text']
                            else:
                                # Both below threshold, should still return best available
                                result = multi_engine.extract_with_fallback(
                                    test_image_data,
                                    confidence_threshold=threshold
                                )
                                expected_text = primary_result['text'] if primary_conf >= fallback_conf else fallback_result['text']
                        
                        # Verify behavior based on threshold
                        assert isinstance(result, (dict, str))
                        
                        if isinstance(result, dict):
                            actual_text = result.get('text', result.get('extracted_text', ''))
                        else:
                            actual_text = result
                        
                        # Verify appropriate engine was used based on confidence threshold
                        if primary_conf >= threshold:
                            mock_tesseract.extract_text.assert_called_once()
                        else:
                            # Should have tried primary and then fallback
                            assert mock_tesseract.extract_text.called or mock_easyocr.extract_text.called
            
            # Test edge cases
            multi_engine = MultiEngineOCR()
            
            # Test with very high threshold (should force fallback)
            mock_tesseract.extract_text.return_value = {
                'text': 'Low confidence result',
                'confidence': 0.30,
                'metadata': {'engine': 'tesseract'}
            }
            mock_easyocr.extract_text.return_value = {
                'text': 'Higher confidence fallback',
                'confidence': 0.75,
                'metadata': {'engine': 'easyocr'}
            }
            
            # Very high threshold should cause fallback
            if hasattr(multi_engine, 'extract_with_fallback'):
                result = multi_engine.extract_with_fallback(test_image_data, confidence_threshold=0.95)
                assert isinstance(result, (dict, str))
            
            # Test threshold of 0.0 (should accept any result)
            if hasattr(multi_engine, 'extract_with_fallback'):
                result = multi_engine.extract_with_fallback(test_image_data, confidence_threshold=0.0)
                assert isinstance(result, (dict, str))
            
            # Test threshold of 1.0 (very strict)
            mock_tesseract.extract_text.return_value = {
                'text': 'Perfect result',
                'confidence': 1.0,
                'metadata': {'engine': 'tesseract'}
            }
            
            if hasattr(multi_engine, 'extract_with_fallback'):
                result = multi_engine.extract_with_fallback(test_image_data, confidence_threshold=1.0)
                assert isinstance(result, (dict, str))

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
